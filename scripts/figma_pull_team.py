#!/usr/bin/env python3
"""从本机 .env 读取 FIGMA_TOKEN，拉取团队项目文件元数据与缩略图。

用法（在仓库根目录）:
  python scripts/figma_pull_team.py
  python scripts/figma_pull_team.py --project-id 355389888

说明:
  - Community 分类页（/resources/community/*）不是 REST 可列接口，本脚本只拉
    你有权限的 Team Project 文件。
  - Token 只从环境变量或仓库根 .env 读取，不会写入 imports 产物。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "imports" / "figma"


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def api_get(url: str, token: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "X-Figma-Token": token,
            "User-Agent": "aigc-studio-figma-pull/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise SystemExit(f"HTTP {exc.code} for {url}: {body}") from exc


def safe_name(name: str, key: str) -> str:
    base = re.sub(r"[^\w\-.]+", "_", name, flags=re.UNICODE).strip("_")[:80]
    return f"{base or 'file'}__{key[:8]}"


def download(url: str, dest: Path) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": "aigc-studio-figma-pull/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
        ctype = resp.headers.get("Content-Type", "")
    ext = ".png"
    if "jpeg" in ctype or "jpg" in ctype:
        ext = ".jpg"
    elif "webp" in ctype:
        ext = ".webp"
    elif "png" not in ctype and dest.suffix:
        ext = dest.suffix
    path = dest.with_suffix(ext)
    path.write_bytes(data)
    return len(data)


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Pull Figma team project files")
    parser.add_argument("--project-id", default=os.environ.get("FIGMA_PROJECT_ID", "355389888"))
    parser.add_argument("--team-id", default=os.environ.get("FIGMA_TEAM_ID", ""))
    args = parser.parse_args()

    token = (os.environ.get("FIGMA_TOKEN") or "").strip()
    if not token:
        print("缺少 FIGMA_TOKEN：请写入仓库根目录 .env（已 gitignore）", file=sys.stderr)
        return 2

    me = api_get("https://api.figma.com/v1/me", token)
    print(f"auth ok: {me.get('handle')} <{me.get('email')}>")

    if args.team_id:
        projects = api_get(f"https://api.figma.com/v1/teams/{args.team_id}/projects", token)
        print(f"team: {projects.get('name')} projects={len(projects.get('projects') or [])}")

    proj = api_get(f"https://api.figma.com/v1/projects/{args.project_id}/files", token)
    files = proj.get("files") or []
    print(f"project: {proj.get('name')} files={len(files)}")

    thumbs = OUT / "team-project"
    meta_dir = OUT / "meta"
    thumbs.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    index: dict = {
        "team_id": args.team_id or None,
        "project_id": args.project_id,
        "project_name": proj.get("name"),
        "files": [],
        "note": (
            "Community discovery pages under /resources/community/* are not "
            "listable via Personal Access Token REST API."
        ),
    }

    for f in files:
        key = f["key"]
        name = f.get("name") or key
        entry: dict = {
            "key": key,
            "name": name,
            "last_modified": f.get("last_modified"),
            "file_url": f"https://www.figma.com/file/{key}",
        }
        thumb_url = f.get("thumbnail_url")
        if thumb_url:
            dest = thumbs / safe_name(name, key)
            try:
                n = download(thumb_url, dest)
                entry["thumbnail_bytes"] = n
                print(f"  thumb {name}: {n} bytes")
            except Exception as exc:  # noqa: BLE001
                entry["thumbnail_error"] = str(exc)
                print(f"  thumb fail {name}: {exc}")

        try:
            doc = api_get(f"https://api.figma.com/v1/files/{key}?depth=1", token)
            reduced = {
                "name": doc.get("name"),
                "lastModified": doc.get("lastModified"),
                "version": doc.get("version"),
                "editorType": doc.get("editorType"),
                "children": [
                    {"id": c.get("id"), "name": c.get("name"), "type": c.get("type")}
                    for c in ((doc.get("document") or {}).get("children") or [])
                ],
            }
            (meta_dir / f"{key}.depth1.json").write_text(
                json.dumps(reduced, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            entry["pages"] = reduced["children"]
            print(f"  meta  {name}: {len(reduced['children'])} top nodes")
        except Exception as exc:  # noqa: BLE001
            entry["meta_error"] = str(exc)
            print(f"  meta fail {name}: {exc}")

        index["files"].append(entry)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "INDEX.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT / 'INDEX.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
