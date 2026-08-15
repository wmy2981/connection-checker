"""数据导入/导出/备份端点。

导出与备份：把可导入数据打包为 zip（config + results + logs，不含密钥/备份）；
导入与恢复：上传 zip（multipart + X-Requested-With 头，见 auth.require_auth 的 CSRF 例外），
先自动备份当前数据再按勾选内容导入；备份管理：创建/列表/恢复/下载/删除。
"""
import asyncio
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth import require_auth
from app.data_transfer import (
    apply_import,
    build_package,
    create_backup,
    list_backups,
    rename_backup,
    resolve_backup,
    validate_package,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data", dependencies=[Depends(require_auth)])

CHUNK = 1024 * 1024


class RestoreRequest(BaseModel):
    """恢复备份 / 导入内容的勾选（至少一项为 True）。"""

    include_records: bool = False
    include_targets: bool = False
    include_settings: bool = False


class RenameBackupRequest(BaseModel):
    """备份重命名请求。"""

    new_name: str = Field(min_length=1, max_length=255)


def _tmp_zip() -> Path:
    """创建可安全删除的临时 zip 文件（mkstemp 的 fd 必须关闭，否则 Windows 上无法 unlink）。"""
    fd, name = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    return Path(name)


def _attachment_header(fname: str) -> str:
    """Content-Disposition：HTTP 头仅 latin-1，中文文件名用 RFC 5987 filename* 编码。"""
    ascii_name = fname.encode("ascii", errors="ignore").decode().strip() or "download.zip"
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(fname)}'


def _stream_zip(tmp: Path, fname: str) -> StreamingResponse:
    """流式发送 zip 临时文件，发送完后删除临时文件。"""

    def gen():
        try:
            with tmp.open("rb") as f:
                while chunk := f.read(CHUNK):
                    yield chunk
        finally:
            tmp.unlink(missing_ok=True)

    return StreamingResponse(
        gen(),
        media_type="application/zip",
        headers={"Content-Disposition": _attachment_header(fname)},
    )


@router.get("/export")
async def export_data(request: Request) -> StreamingResponse:
    """导出数据包 zip（config + results + logs，不含密钥与备份）。"""
    data_dir = request.app.state.settings.data_dir
    fname = f"connection-checker-data-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    tmp = _tmp_zip()
    try:
        count = await asyncio.to_thread(build_package, tmp, data_dir)
    except Exception as e:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        logger.error("Data export failed: %s", e)
        raise HTTPException(status_code=500, detail="数据导出失败") from None
    logger.info("Data export prepared: %s (%d files)", fname, count)
    return _stream_zip(tmp, fname)


@router.post("/import")
async def import_data(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008
    include_records: bool = Form(False),
    include_targets: bool = Form(False),
    include_settings: bool = Form(False),
) -> dict:
    """导入数据包 zip：先自动备份当前数据，再按勾选内容导入（至少选一项）。"""
    if not (include_records or include_targets or include_settings):
        raise HTTPException(status_code=422, detail="至少选择一项导入内容")
    tmp = _tmp_zip()
    try:
        with tmp.open("wb") as out:
            while chunk := await file.read(CHUNK):
                out.write(chunk)
        try:
            await asyncio.to_thread(validate_package, tmp)
        except ValueError as e:
            logger.warning("Import rejected: %s", e)
            raise HTTPException(status_code=422, detail=str(e)) from None
        data_dir = request.app.state.settings.data_dir
        try:
            backup_path = await asyncio.to_thread(create_backup, data_dir)
        except Exception as e:  # noqa: BLE001
            logger.error("Auto backup failed before import (%s); import aborted", e)
            raise HTTPException(status_code=500, detail="导入前自动备份失败，导入已中止") from None
        logger.info("Auto backup created before import: %s", backup_path.name)
        stats = await apply_import(
            request,
            tmp,
            records=include_records,
            targets=include_targets,
            settings=include_settings,
        )
        logger.info(
            "Data import completed: records=%d targets=%d settings=%s backup=%s",
            stats["records"],
            stats["targets"],
            stats["settings"],
            backup_path.name,
        )
        return {"ok": True, **stats, "backup": backup_path.name}
    finally:
        tmp.unlink(missing_ok=True)


@router.post("/backups")
async def create_backup_endpoint(request: Request) -> dict:
    """创建备份 zip（内容同导出，不含密钥）。"""
    data_dir = request.app.state.settings.data_dir
    try:
        path = await asyncio.to_thread(create_backup, data_dir)
    except Exception as e:  # noqa: BLE001
        logger.error("Backup creation failed: %s", e)
        raise HTTPException(status_code=500, detail="备份创建失败") from None
    logger.info("Backup created: %s", path.name)
    return {"ok": True, "name": path.name, "size": path.stat().st_size}


@router.get("/backups")
async def get_backups(request: Request) -> dict:
    """备份列表（新→旧）。"""
    return {
        "backups": await asyncio.to_thread(list_backups, request.app.state.settings.data_dir)
    }


def _resolve_or_raise(data_dir: Path, name: str) -> Path:
    try:
        return resolve_backup(data_dir, name)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None


@router.post("/backups/{name}/restore")
async def restore_backup(request: Request, name: str, payload: RestoreRequest) -> dict:
    """从备份恢复：与导入相同的勾选语义，恢复前自动备份当前数据。"""
    if not (payload.include_records or payload.include_targets or payload.include_settings):
        raise HTTPException(status_code=422, detail="至少选择一项恢复内容")
    data_dir = request.app.state.settings.data_dir
    path = _resolve_or_raise(data_dir, name)
    try:
        await asyncio.to_thread(validate_package, path)
    except ValueError as e:
        logger.error("Backup %s failed validation: %s", name, e)
        raise HTTPException(status_code=422, detail=str(e)) from None
    try:
        backup_path = await asyncio.to_thread(create_backup, data_dir)
    except Exception as e:  # noqa: BLE001
        logger.error("Auto backup failed before restore (%s); restore aborted", e)
        raise HTTPException(status_code=500, detail="恢复前自动备份失败，恢复已中止") from None
    logger.info("Auto backup created before restore: %s", backup_path.name)
    stats = await apply_import(
        request,
        path,
        records=payload.include_records,
        targets=payload.include_targets,
        settings=payload.include_settings,
    )
    logger.info(
        "Backup %s restored: records=%d targets=%d settings=%s",
        name,
        stats["records"],
        stats["targets"],
        stats["settings"],
    )
    return {"ok": True, **stats, "backup": backup_path.name}


@router.put("/backups/{name}/rename")
async def rename_backup_endpoint(
    request: Request, name: str, payload: RenameBackupRequest
) -> dict:
    """重命名备份文件：新名须为安全 .zip 文件名，目标已存在返回 409。"""
    data_dir = request.app.state.settings.data_dir
    new_name = payload.new_name.strip()
    try:
        new_path = await asyncio.to_thread(rename_backup, data_dir, name, new_name)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except FileExistsError as e:
        logger.warning("Backup rename rejected (%s -> %s): %s", name, new_name, e)
        raise HTTPException(status_code=409, detail=str(e)) from None
    logger.info("Backup renamed: %s -> %s", name, new_path.name)
    return {"ok": True, "name": new_path.name}


@router.get("/backups/{name}/download")
async def download_backup(request: Request, name: str) -> StreamingResponse:
    """下载备份 zip（备份文件保留，不删除）。"""
    data_dir = request.app.state.settings.data_dir
    path = _resolve_or_raise(data_dir, name)
    logger.info("Backup downloaded: %s", name)

    def gen():
        with path.open("rb") as f:
            while chunk := f.read(CHUNK):
                yield chunk

    return StreamingResponse(
        gen(),
        media_type="application/zip",
        headers={"Content-Disposition": _attachment_header(name)},
    )


@router.delete("/backups/{name}")
async def delete_backup(request: Request, name: str) -> dict:
    """删除备份文件。"""
    data_dir = request.app.state.settings.data_dir
    path = _resolve_or_raise(data_dir, name)
    try:
        await asyncio.to_thread(path.unlink)
    except OSError as e:
        logger.error("Backup deletion failed (%s): %s", name, e)
        raise HTTPException(status_code=500, detail="备份删除失败") from None
    logger.info("Backup deleted: %s", name)
    return {"ok": True}
