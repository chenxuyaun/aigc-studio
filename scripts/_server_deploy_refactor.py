# -*- coding: utf-8 -*-
"""refactor/v1 部署：只同步 apps/api/ 到服务器，服务器 .env 与 compose 原地不动。

安全设计（与 _server_sync.py 整体替换不同）：
- 服务器 ~/aigc-studio/.env 与 compose.prod.yaml 不被触碰（md5 前后校验）
- 仅上传解压 apps/api/ 树（tar 内路径 apps/api/...，解压 -C ~/aigc-studio）
- 解压校验新结构关键文件（app/applications 等）才继续
- 构建走 nohup 三件套（< /dev/null & disown），轮询日志与容器状态
- 验证：容器健康 → 容器内 health/live → 重启 frontend（nginx 重解析）→
  nginx 链路 health + 登录状态码（只打状态码，不回显任何凭据/响应体）
- 回滚：~/backups/aigc-studio-pre-refactor-api-*.tar.gz 恢复 + rebuild
"""
import hashlib
import os
import sys
import tarfile
import time
from pathlib import Path

import paramiko

sys.stdout.reconfigure(encoding="utf-8")

env = {}
for line in open("D:/.env", encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

root = Path("D:/software/code/ideas/list/aigc-studio")
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "node_modules"}
EXCLUDE_FILES = {".pyc", ".pyo", ".log", ".tar", ".db"}
# 仅排除顶层死重 apps/api/storage（3k+ 旧媒体文件，运行时用命名卷 storage_data 与之
# 无关）；❗不能用裸名字 "storage"——会误杀任意深度的 storage 包（app/storage、
# app/core/runtime/storage 曾因此缺席 → 生产 ModuleNotFoundError，2026-09-01 实战）。
EXCLUDE_REL_DIRS = {"apps/api/storage"}

api_dir = root / "apps" / "api"
tar_path = root / ".deploy-api-sync.tar"
count = 0
with tarfile.open(tar_path, "w") as tar:
    for dirpath, dirnames, filenames in os.walk(api_dir):
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        dirnames[:] = [
            d for d in dirnames
            if d not in EXCLUDE_DIRS
            and f"{rel_dir}/{d}".replace("\\", "/") not in EXCLUDE_REL_DIRS
        ]
        for f in filenames:
            if any(f.endswith(e) for e in EXCLUDE_FILES):
                continue
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            tar.add(full, arcname=rel)
            count += 1
print(f"[pack] {count} files, {tar_path.stat().st_size / 1024 / 1024:.1f} MB")

priv_key = paramiko.Ed25519Key(filename=str(root / ".server-keys/id_ed25519"))
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(env["host"], port=int(env["port"]), username="ubuntu",
               pkey=priv_key, timeout=20, allow_agent=False, look_for_keys=False)


def run(cmd: str, timeout: int = 120) -> tuple[str, str]:
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace").strip()
    return out, err


def phase(title: str) -> None:
    print(f"\n===== {title} =====")


# ── Phase 1: 服务器基线 ──────────────────────────────────────────
phase("1. baseline")
out, err = run(
    "cd ~/aigc-studio && docker compose -f compose.prod.yaml ps --format "
    "'{{.Name}} {{.Status}}' && md5sum .env && df -h / | tail -1 && "
    "docker compose -f compose.prod.yaml config --services | tr '\\n' ' '"
)
print(out)
if err:
    print("[stderr]", err[:300])

# ── Phase 1.5: 覆盖前备份服务器现有 apps/api ─────────────────────
phase("1.5 backup server apps/api")
out, err = run(
    "mkdir -p ~/backups && B=~/backups/aigc-studio-pre-refactor-api-$(date +%Y%m%d%H%M).tar.gz && "
    "tar -czf $B -C ~/aigc-studio apps/api && ls -lh $B | awk '{print $5, $9}'"
    , timeout=300)
print(out)
if err:
    print("[stderr]", err[:200])
if ".tar.gz" not in out:
    print("!! 服务器备份未生成，中止（不覆盖）")
    client.close()
    tar_path.unlink(missing_ok=True)
    raise SystemExit(2)

# ── Phase 2: 上传 + 解压 + 校验（.env 不受影响）──────────────────
phase("2. upload apps/api")
sftp = client.open_sftp()
sftp.put(str(tar_path), "/home/ubuntu/aigc-api-sync.tar", confirm=False)
sftp.close()
print("uploaded")

out, err = run(
    "set -e; "
    "tar -xf /home/ubuntu/aigc-api-sync.tar -C ~/aigc-studio && "
    "rm -f /home/ubuntu/aigc-api-sync.tar && "
    "test -f ~/aigc-studio/apps/api/app/main.py && "
    "test -f ~/aigc-studio/apps/api/app/applications/task_runner.py && "
    "test -f ~/aigc-studio/apps/api/app/data/models/user.py && "
    "test -f ~/aigc-studio/apps/api/app/providers/models/openai_compatible.py && "
    "test -f ~/aigc-studio/apps/api/app/core/runtime/storage/registry.py && "
    "test -f ~/aigc-studio/apps/api/app/storage/quark_provider.py && "
    "test -d ~/aigc-studio/apps/api/alembic && "
    "test -f ~/aigc-studio/apps/api/seed_data.py && "
    "test -f ~/aigc-studio/apps/api/docker-entrypoint.sh && "
    "test -f ~/aigc-studio/.env && "
    "echo EXTRACT_OK"
    , timeout=300)
print(out[-300:])
if err:
    print("[stderr]", err[:300])
if "EXTRACT_OK" not in out:
    print("!! 解压/结构校验未通过，请人工检查（服务器源码未被破坏，仅 apps/api 已覆盖）")
    client.close()
    tar_path.unlink(missing_ok=True)
    raise SystemExit(2)
print("[ok] 新结构关键文件就位，.env 仍在原位")

# ── Phase 3: 构建（nohup 三件套）────────────────────────────────
phase("3. build api worker (nohup)")
run("rm -f ~/aigc-api-build.log")
out, err = run(
    "cd ~/aigc-studio && nohup docker compose -f compose.prod.yaml build api worker "
    "> ~/aigc-api-build.log 2>&1 < /dev/null & disown; echo BUILD_LAUNCHED"
)
print(out.strip() or err)

deadline = time.time() + 900  # 15 分钟上限
build_done = False
while time.time() < deadline:
    time.sleep(15)
    # [l] 括号技防 pgrep 自匹配（bash -c 自身 cmdline 含模式曾致死循环）
    out, _ = run("tail -3 ~/aigc-api-build.log; "
                 "if ! pgrep -f 'compose -f compose.prod.yam[l] build' >/dev/null; "
                 "then echo BUILD_PROC_GONE; fi")
    tail = out.strip()
    if "BUILD_PROC_GONE" in out:
        print(tail[-400:])
        build_done = True
        break
    print(f"[waiting] {tail.splitlines()[-1][:120] if tail else ''}")
if not build_done:
    print("!! 构建超时，请人工检查 ~/aigc-api-build.log")
    client.close()
    tar_path.unlink(missing_ok=True)
    raise SystemExit(3)
out, err = run("tail -5 ~/aigc-api-build.log")
print(out)
if "ERROR" in out or "error" in (err or ""):
    print("!! 构建日志含错误，中止（未重启任何容器）")
    client.close()
    tar_path.unlink(missing_ok=True)
    raise SystemExit(4)

# ── Phase 4: 滚动重启 api worker ────────────────────────────────
phase("4. up -d api worker")
out, err = run(
    "cd ~/aigc-studio && docker compose -f compose.prod.yaml up -d --no-deps api worker 2>&1 | tail -5"
    , timeout=300)
print(out)
if err:
    print("[stderr]", err[:300])

deadline = time.time() + 180
healthy = False
while time.time() < deadline:
    time.sleep(10)
    # 容器内无 curl（slim 镜像），用 python urllib 探活
    out, _ = run("docker exec aigc-studio-api-1 python -c "
                 "\"import urllib.request;"
                 "print(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live').status)\" "
                 "2>&1 | tail -1")
    code = out.strip().splitlines()[-1] if out.strip() else ""
    if code == "200":
        healthy = True
        print(f"[ok] api 容器内 health/live = 200（等待 {(180 - (deadline - time.time())):.0f}s）")
        break
    print(f"[waiting] health/live = {code[:80] or 'n/a'}")
if not healthy:
    out, _ = run("cd ~/aigc-studio && docker compose -f compose.prod.yaml ps --format "
                 "'{{.Name}} {{.Status}}'; docker logs aigc-studio-api-1 --tail 30 2>&1")
    print(out)
    print("!! api 未在 180s 内转 healthy，请人工检查（frontend 未动，公网仍可能 502）")
    client.close()
    tar_path.unlink(missing_ok=True)
    raise SystemExit(5)

# ── Phase 5: frontend 重解析 + nginx 链路验证 ────────────────────
phase("5. frontend re-resolve + verification")
out, err = run(
    "cd ~/aigc-studio && docker compose -f compose.prod.yaml up -d --no-deps --force-recreate frontend 2>&1 | tail -3"
    , timeout=300)
print(out)
time.sleep(8)  # 等 nginx 起来 + wait-for-api 轮询

out, _ = run(
    "echo -n 'nginx_health='; curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5000/api/v1/health/live; echo; "
    "echo -n 'public_health='; curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/api/v1/health/live; echo; "
    "echo -n 'saios_page='; curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/saios; echo; "
    "PW=$(grep '^INITIAL_ADMIN_PASSWORD=' ~/aigc-studio/.env | cut -d= -f2-); "
    "echo -n 'login_status='; "
    "curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:5000/api/v1/auth/login "
    "-H 'Content-Type: application/json' "
    "-d \"{\\\"username\\\":\\\"admin\\\",\\\"password\\\":\\\"$PW\\\"}\"; echo; "
    "unset PW; "
    "echo -n 'env_md5_after='; md5sum ~/aigc-studio/.env | cut -d' ' -f1"
)
print(out)
if err:
    print("[stderr]", err[:200])

out, _ = run("cd ~/aigc-studio && docker compose -f compose.prod.yaml ps --format '{{.Name}} {{.Status}}'")
print("\n" + out)

client.close()
tar_path.unlink(missing_ok=True)
print("\n[done] 部署完成。回滚：~/backups/aigc-studio-pre-refactor-api-*.tar.gz + git checkout pre-refactor-v1")
