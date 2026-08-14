"""数据导入/导出/备份端点测试（zip 打包、manifest 校验、导入合并语义、备份全流程）。"""
import io
import json
import zipfile

from fastapi.testclient import TestClient

from app.models import CheckResult

DATA_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


def _make_package(
    *,
    app: dict | None = None,
    s3: dict | None = None,
    webhook: dict | None = None,
    targets: list[dict] | None = None,
    results: list[CheckResult] | None = None,
    with_manifest: bool = True,
) -> bytes:
    """构造一个导出包 zip 字节串，供导入测试使用。"""
    cfg = {
        "version": 1,
        "last_updated": "2026-08-13T00:00:00+08:00",
        "check_targets": targets or [],
        "webhook": webhook
        or {"enabled": True, "url": None, "fail_threshold": 3},
        "app": app
        or {
            "result_max_records": 50000,
            "ping_count": 4,
            "connect_timeout": 3.0,
            "http_timeout": 5.0,
            "stats_window": 50,
            "log_level": "INFO",
            "log_cleanup_mode": "delete",
            "log_retention_days": 30,
            "storage_mode": "local",
            "brand_icon": None,
        },
        "s3": s3
        or {
            "enabled": False,
            "endpoint": "",
            "bucket": "",
            "region": None,
            "datapath": "",
        },
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        if with_manifest:
            zf.writestr(
                "manifest.json",
                json.dumps({"app": "connection-checker", "schema": 1, "created_at": "x"}),
            )
        zf.writestr("config.json", json.dumps(cfg, ensure_ascii=False))
        if results:
            lines = "".join(r.model_dump_json() + "\n" for r in results)
            zf.writestr("results.jsonl", lines)
    return buf.getvalue()


def _make_result(rid: str, checked_at: str = "2026-08-13T10:00:00+08:00") -> CheckResult:
    return CheckResult.model_validate(
        {
            "id": rid,
            "target_id": "t-1",
            "target_name": "目标",
            "ip": "127.0.0.1",
            "check_method": "ping",
            "status": "success",
            "latency_ms": 1.0,
            "message": "ok",
            "extra": {},
            "checked_at": checked_at,
        }
    )


def _import(logged_client: TestClient, pkg: bytes, **include) -> object:
    data = {
        "include_records": "true",
        "include_targets": "true",
        "include_settings": "true",
    }
    data.update({k: "true" if v else "false" for k, v in include.items()})
    return logged_client.post(
        "/api/v1/data/import",
        files={"file": ("pkg.zip", pkg, "application/zip")},
        data=data,
        headers=DATA_HEADERS,
    )


def test_export_zip_structure(logged_client: TestClient, settings):
    """导出 zip：含 manifest/config，不含 secrets 与 backups。"""
    resp = logged_client.get("/api/v1/data/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "config.json" in names
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["app"] == "connection-checker"
        assert "secrets.json" not in names
        assert not any(n.startswith("backups/") for n in names)


def test_export_requires_auth(client: TestClient):
    assert client.get("/api/v1/data/export").status_code == 401


def test_import_rejects_invalid_package(logged_client: TestClient):
    # 非 zip 文件
    resp = logged_client.post(
        "/api/v1/data/import",
        files={"file": ("pkg.zip", b"not a zip", "application/zip")},
        data={"include_records": "true"},
        headers=DATA_HEADERS,
    )
    assert resp.status_code == 422
    # 合法 zip 但缺 manifest（不是本应用导出包）
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("config.json", "{}")
    resp = logged_client.post(
        "/api/v1/data/import",
        files={"file": ("pkg.zip", buf.getvalue(), "application/zip")},
        data={"include_records": "true"},
        headers=DATA_HEADERS,
    )
    assert resp.status_code == 422
    assert "manifest" in resp.json()["detail"]


def test_import_requires_selection(logged_client: TestClient):
    resp = logged_client.post(
        "/api/v1/data/import",
        files={"file": ("pkg.zip", _make_package(), "application/zip")},
        data={"include_records": "false", "include_targets": "false", "include_settings": "false"},
        headers=DATA_HEADERS,
    )
    assert resp.status_code == 422


def test_import_multipart_requires_xrw_header(logged_client: TestClient):
    """multipart 上传不带 X-Requested-With 头 → 415（CSRF 纵深防御例外条件）。"""
    resp = logged_client.post(
        "/api/v1/data/import",
        files={"file": ("pkg.zip", _make_package(), "application/zip")},
        data={"include_records": "true"},
    )
    assert resp.status_code == 415


def test_import_records_appends_and_dedupes(logged_client: TestClient, settings):
    """检查记录追加导入：按 id 去重，重复导入不产生重复记录。"""
    pkg = _make_package(results=[_make_result("r-1"), _make_result("r-2")])
    resp = _import(logged_client, pkg, include_records=True)
    assert resp.status_code == 200
    assert resp.json()["records"] == 2
    # 再次导入同包：id 去重，不重复追加
    resp2 = _import(logged_client, pkg, include_records=True)
    assert resp2.json()["records"] == 0
    # 第三次导入含已存在的 r-1 与新的 r-3：只追加 r-3
    pkg3 = _make_package(results=[_make_result("r-1"), _make_result("r-3")])
    resp3 = _import(logged_client, pkg3, include_records=True)
    assert resp3.json()["records"] == 1
    lines = (settings.data_dir / "results.jsonl").read_text(encoding="utf-8").strip().splitlines()
    ids = {json.loads(line)["id"] for line in lines}
    assert ids == {"r-1", "r-2", "r-3"}


def test_import_targets_merges_by_id(logged_client: TestClient, settings):
    """目标按 id 合并：同 id 覆盖、新 id 新增、其余保留。"""
    # 现有目标：将被覆盖的 t-1 与保留的 t-2（API 创建的目标 id 由服务端生成，
    # 无法指定，因此直接构造内存目标；导入端点的 save 会把它们一并写盘）
    from app.models import Target

    store = logged_client.app.state.config_store
    for tid, ip in (("t-1", "1.1.1.1"), ("t-2", "2.2.2.2")):
        store.targets[tid] = Target.model_validate(
            {"id": tid, "name": tid, "ip": ip, "check_method": "ping"}
        )
    def _target(tid: str, name: str, ip: str) -> dict:
        return {
            "id": tid, "name": name, "ip": ip, "check_method": "ping",
            "check_interval": 60, "enabled": True, "notify_enabled": True,
            "time_ranges": [{"start": "00:00", "end": "23:59"}], "port": None,
            "ping_count": None, "scheme": "http", "url_path": "/",
            "http_success_codes": None, "timeout": None,
        }

    pkg = _make_package(
        targets=[_target("t-1", "覆盖", "9.9.9.9"), _target("t-3", "新增", "3.3.3.3")]
    )
    resp = _import(logged_client, pkg, include_targets=True)
    assert resp.status_code == 200
    assert resp.json()["targets"] == 2
    raw = json.loads((settings.data_dir / "config.json").read_text(encoding="utf-8"))
    by_id = {t["id"]: t for t in raw["check_targets"]}
    assert by_id["t-1"]["ip"] == "9.9.9.9"  # 同 id 覆盖
    assert by_id["t-1"]["name"] == "覆盖"
    assert by_id["t-2"]["ip"] == "2.2.2.2"  # 未覆盖的保留
    assert by_id["t-3"]["ip"] == "3.3.3.3"  # 新增


def test_import_settings_merges_per_key(logged_client: TestClient, settings):
    """设置逐键合并：zip 有的键覆盖，zip 缺失的当前键保留。"""
    # zip 只带部分 app 键（模拟旧版本导出的包）
    pkg = _make_package(
        app={"result_max_records": 123, "log_level": "DEBUG"},
        s3={"enabled": False, "endpoint": "https://s3.example.com", "bucket": "b",
            "region": None, "datapath": "cc"},
    )
    resp = _import(logged_client, pkg, include_settings=True)
    assert resp.status_code == 200
    assert resp.json()["settings"] is True
    raw = json.loads((settings.data_dir / "config.json").read_text(encoding="utf-8"))
    assert raw["app"]["result_max_records"] == 123
    assert raw["app"]["log_level"] == "DEBUG"
    assert raw["app"]["ping_count"] == 4  # zip 缺失的键保持默认
    assert raw["s3"]["endpoint"] == "https://s3.example.com"
    assert raw["webhook"]["fail_threshold"] == 3  # zip 未带 webhook 时保持当前


def test_import_s3_falls_back_without_credentials(
    logged_client: TestClient, settings, caplog
):
    """zip 的 s3.enabled=true 但当前无凭据（导出不含密钥）→ 回落禁用 + WARN。"""
    pkg = _make_package(
        s3={"enabled": True, "endpoint": "https://s3.example.com", "bucket": "b",
            "region": None, "datapath": "cc"}
    )
    with caplog.at_level("WARNING"):
        resp = _import(logged_client, pkg, include_settings=True)
    assert resp.status_code == 200
    raw = json.loads((settings.data_dir / "config.json").read_text(encoding="utf-8"))
    assert raw["s3"]["enabled"] is False
    assert any("credentials missing; s3 disabled" in rec.message for rec in caplog.records)


def test_import_s3_keeps_enabled_with_credentials(logged_client: TestClient, settings):
    """已有 S3 凭据时，zip 的 s3.enabled=true 如实导入。"""
    logged_client.app.state.secrets_store.set_s3_credentials("id", "key")
    pkg = _make_package(
        s3={"enabled": True, "endpoint": "https://s3.example.com", "bucket": "b",
            "region": None, "datapath": "cc"}
    )
    resp = _import(logged_client, pkg, include_settings=True)
    assert resp.status_code == 200
    raw = json.loads((settings.data_dir / "config.json").read_text(encoding="utf-8"))
    assert raw["s3"]["enabled"] is True


def test_import_creates_auto_backup(logged_client: TestClient, settings):
    resp = _import(logged_client, _make_package(), include_settings=True)
    assert resp.status_code == 200
    backups = list((settings.data_dir / "backups").glob("backup-*.zip"))
    assert len(backups) == 1
    assert resp.json()["backup"] == backups[0].name


def test_backup_flow(logged_client: TestClient, settings):
    """备份：创建 → 列表 → 下载 → 恢复 → 删除。"""
    # 写方法强制 JSON 内容类型（CSRF 纵深防御），无 body 也需显式带 JSON
    resp = logged_client.post("/api/v1/data/backups", json={})
    assert resp.status_code == 200
    name = resp.json()["name"]

    listed = logged_client.get("/api/v1/data/backups").json()["backups"]
    assert listed and listed[0]["name"] == name
    assert listed[0]["size"] > 0

    dl = logged_client.get(f"/api/v1/data/backups/{name}/download")
    assert dl.status_code == 200
    with zipfile.ZipFile(io.BytesIO(dl.content)) as zf:
        assert "config.json" in zf.namelist()

    restored = logged_client.post(
        f"/api/v1/data/backups/{name}/restore", json={"include_settings": True}
    )
    assert restored.status_code == 200
    assert restored.json()["ok"] is True

    deleted = logged_client.delete(f"/api/v1/data/backups/{name}")
    assert deleted.status_code == 200
    assert not (settings.data_dir / "backups" / name).exists()


def test_backup_name_validation(logged_client: TestClient, settings):
    # 不安全的备份名一律 422（防路径穿越/任意文件访问）：
    # 非 .zip 结尾、以 . 开头（含分隔符的穿越名在 URL 层即被 HTTP 客户端规范化，
    # 无法到达路由；该防御由 rename 端点的 body 用例覆盖）
    bad_names = (
        "config.json",
        "backup-20260813-120000.txt",
        "..zip",
        ".hidden.zip",
        "backup.zip;rm",
    )
    for bad in bad_names:
        assert logged_client.get(f"/api/v1/data/backups/{bad}/download").status_code == 422
        assert logged_client.delete(f"/api/v1/data/backups/{bad}").status_code == 422
        restore = logged_client.post(
            f"/api/v1/data/backups/{bad}/restore", json={"include_records": True}
        )
        assert restore.status_code == 422
    # 合法名字（含自定义重命名名）但文件不存在 → 404
    for ok_name in ("backup-20260813-120000.zip", "backup-123.zip", "自定义备份.zip"):
        assert (
            logged_client.get(f"/api/v1/data/backups/{ok_name}/download").status_code == 404
        )


def test_backup_rename(logged_client: TestClient, settings):
    """备份重命名：新名可列表/下载/删除、旧名 404、重名 409、非法名 422。"""
    from urllib.parse import quote

    old = logged_client.post("/api/v1/data/backups", json={}).json()["name"]
    new_name = "周备份.zip"
    encoded = quote(new_name)
    # 重命名成功：新名出现在列表、旧名 404
    resp = logged_client.put(
        f"/api/v1/data/backups/{old}/rename", json={"new_name": new_name}
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == new_name
    names = [b["name"] for b in logged_client.get("/api/v1/data/backups").json()["backups"]]
    assert new_name in names and old not in names
    # 旧名 404（须在 restore 之前断言：restore 的自动备份可能复用该秒级文件名）
    assert logged_client.get(f"/api/v1/data/backups/{old}/download").status_code == 404
    # 重命名后的备份可下载/恢复（恢复只看 zip 内容合法与否，与文件名无关）
    assert logged_client.get(f"/api/v1/data/backups/{encoded}/download").status_code == 200
    restored = logged_client.post(
        f"/api/v1/data/backups/{encoded}/restore", json={"include_settings": True}
    )
    assert restored.status_code == 200
    # 重命名为已存在的备份名 → 409（拒绝覆盖）
    # 两次创建须跨秒：create_backup 以秒级时间戳命名，同秒会重名覆盖
    import time

    time.sleep(1.1)
    name2 = logged_client.post("/api/v1/data/backups", json={}).json()["name"]
    conflict = logged_client.put(
        f"/api/v1/data/backups/{name2}/rename", json={"new_name": new_name}
    )
    assert conflict.status_code == 409
    # 非法新名 → 422；空名 → 422
    for bad in ("../x.zip", "x.txt", ".h.zip"):
        resp = logged_client.put(
            f"/api/v1/data/backups/{name2}/rename", json={"new_name": bad}
        )
        assert resp.status_code == 422
    assert (
        logged_client.put(
            f"/api/v1/data/backups/{name2}/rename", json={"new_name": "   "}
        ).status_code
        == 422
    )
    # 清理
    assert logged_client.delete(f"/api/v1/data/backups/{encoded}").status_code == 200
    assert logged_client.delete(f"/api/v1/data/backups/{name2}").status_code == 200
