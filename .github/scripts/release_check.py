#!/usr/bin/env python3
"""发行检查：版本号从 pyproject.toml 的 project.version 读取（手动维护，不再自动 bump）。

规则：
- 合法正式版 x.y.z；合法预发行 x.y.z.alpha.n / x.y.z.beta.n
- main 分支：只接受正式版。与仓库最大版本 tag 比较，无变化或倒退则报错退出；前进则发行
- dev 分支：只接受预发行。无变化则跳过（成功退出，不发版）；倒退则报错退出；前进则预发行
- 发行说明范围：最后一个正式版 tag 到 HEAD（预发行与正式发行一致）

输出（写入 GITHUB_OUTPUT）：
- version: 当前版本号
- is_prerelease: true/false
- skip: true（dev 无变化，跳过）
- last_release_tag: 最后一个正式版 tag（空串表示无）
同时生成 .release-notes.md。
"""
import os
import re
import subprocess
import sys
from pathlib import Path

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:\.(alpha|beta)\.(\d+))?$")
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:\.(alpha|beta)\.(\d+))?$")


def parse(v: str) -> tuple | None:
    """版本转排序元组：(major, minor, patch, rank, pre_n)，rank: alpha=0 beta=1 正式版=2。"""
    m = VERSION_RE.match(v)
    if not m:
        return None
    major, minor, patch = (int(x) for x in m.group(1, 2, 3))
    pre = m.group(4)
    n = int(m.group(5) or 0)
    rank = {"alpha": 0, "beta": 1}.get(pre, 2)
    return (major, minor, patch, rank, n)


def is_prerelease(v: str) -> bool:
    m = VERSION_RE.match(v)
    return bool(m and m.group(4))


def fail(msg: str) -> None:
    print(f"::error::{msg}")
    print(msg)
    sys.exit(1)


def all_tags() -> list[tuple]:
    out = subprocess.run(["git", "tag"], capture_output=True, text=True).stdout
    tags: list[tuple] = []
    for line in out.splitlines():
        m = TAG_RE.match(line.strip())
        if not m:
            continue
        base = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
        if m.group(4):
            base += f".{m.group(4)}.{m.group(5)}"
        p = parse(base)
        if p:
            tags.append(p)
    return tags


def fmt(v: tuple) -> str:
    major, minor, patch, rank, n = v
    if rank == 2:
        return f"{major}.{minor}.{patch}"
    pre = "alpha" if rank == 0 else "beta"
    return f"{major}.{minor}.{patch}.{pre}.{n}"


def build_notes(version: str, last_release_tag: str) -> None:
    """发行说明：从最后一个正式版 tag 到 HEAD 的提交列表。"""
    if last_release_tag:
        range_spec = f"{last_release_tag}..HEAD"
        header = f"自 {last_release_tag} 以来的提交："
    else:
        range_spec = "HEAD"
        header = "全部提交："
    out = subprocess.run(
        ["git", "log", range_spec, "--pretty=format:%h %s"],
        capture_output=True,
        text=True,
    ).stdout
    commits = [line for line in out.splitlines() if line.strip()]
    lines = [
        f"# Connection Checker {version}",
        "",
        header,
        "",
    ]
    lines.extend(f"- `{c}`" for c in commits)
    if not commits:
        lines.append("- （无提交）")
    Path(".release-notes.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    branch = sys.argv[1] if len(sys.argv) > 1 else ""
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
    if not m:
        fail("pyproject.toml 中找不到 project.version")
    version = m.group(1)

    if not VERSION_RE.match(version):
        fail(
            f"非法版本号 {version!r}：正式版必须为 x.y.z，预发行必须为 x.y.z.alpha.n 或 x.y.z.beta.n"
        )

    tags = all_tags()
    last = max(tags) if tags else None
    cur = parse(version)

    if branch == "main":
        if is_prerelease(version):
            fail(f"main 分支只接受正式版（x.y.z），当前 {version} 是预发行版")
        if last is None:
            action = "release"
        elif cur == last:
            fail(f"版本号无变化：{version} 与已发版 tag v{fmt(last)} 相同")
        elif cur < last:
            fail(f"版本号倒退：{version} < 已发版 v{fmt(last)}")
        else:
            action = "release"
        notes_tag = fmt(last) if last and not is_prerelease(fmt(last)) else ""
    elif branch == "dev":
        if not is_prerelease(version):
            fail(
                f"dev 分支只接受预发行版本（x.y.z.alpha.n / x.y.z.beta.n），"
                f"当前 {version} 是正式版号"
            )
        if last is None or cur > last:
            action = "prerelease"
        elif cur == last:
            action = "skip"
        else:
            fail(f"版本号倒退：{version} < 已发版 v{fmt(last)}")
        notes_tag = fmt(last) if last and not is_prerelease(fmt(last)) else ""
    else:
        fail(f"不支持的触发分支 {branch!r}（仅 main / dev）")

    if action != "skip":
        build_notes(version, notes_tag)

    payload = (
        f"version={version}\n"
        f"is_prerelease={'true' if action == 'prerelease' else 'false'}\n"
        f"skip={'true' if action == 'skip' else 'false'}\n"
        f"last_release_tag={notes_tag}\n"
    )
    out_path = os.environ.get("GITHUB_OUTPUT")
    if out_path:
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(payload)
    else:
        print(payload, end="")
    print(f"action={action} ({branch})")


if __name__ == "__main__":
    main()
