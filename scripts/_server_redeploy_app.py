# -*- coding: utf-8 -*-
"""一键重新部署 aigc-studio 应用层（api/worker/frontend）。

根治「502 第三形态」：重建 api/worker 容器后其 IP 变化，frontend 容器内的 nginx
进程仍缓存旧解析结果 → 公网登录/刷新 token 全 502（AGENTS.md 已记录必须手动
`docker restart frontend`）。本脚本把整条链路自动化，避免人为遗漏重启 frontend。

流程：同步本地代码 → 服务器 docker compose build api worker → 等待 api 健康 →
强制重建 frontend（让其 nginx 重新解析 api 的 IP）→ 公网健康验证。

用法： python scripts/_server_redeploy_app.py
       python scripts/_server_redeploy_app.py --no-sync   # 跳过代码同步，只重建
"""
import sys
import time

import paramiko

sys.stdout.reconfigure(encoding="utf-8")

env = {}
for line in open("D:/.env", encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

ROOT = "D:/software/code/ideas/list/aigc-studio"
REMOTE_DIR = "/home/ubuntu/aigc-studio"
no_sync = "--no-sync" in sys.argv

priv_key = paramiko.Ed25519Key(filename=f"{ROOT}/.server-keys/id_ed25519")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(env["host"], port=int(env["port"]), username="ubuntu",
               pkey=priv_key, timeout=20, allow_agent=False, look_for_keys=False)


def run(cmd: str, timeout: int = 600) -> tuple[str, str]:
    """执行远程命令，返回 (stdout, stderr)。"""
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    return out, err


# 1. 同步代码（除非 --no-sync）
if not no_sync:
    print("[1/5] 同步代码...")
    out, err = run(f"cd {REMOTE_DIR} && git status --short 2>&1 | head -3", timeout=30)
    print("  服务器当前 git 状态（参考）：", out.strip() or "(clean)")
    # 复用 _server_sync.py 的打包逻辑（直接调用它更省事）
    print("  调用 _server_sync.py 打包并传输...")
    import subprocess
    r = subprocess.run([sys.executable, f"{ROOT}/scripts/_server_sync.py"],
                       capture_output=True, text=True, cwd=ROOT)
    print("  ", (r.stdout or "").strip()[-400:])
    if r.returncode != 0:
        print("  [stderr]", (r.stderr or "")[:300])
        print("  同步失败，终止。请手动跑 _server_sync.py 排查。")
        client.close()
        sys.exit(1)
else:
    print("[1/5] 跳过代码同步（--no-sync）")

# 2. 重建 api + worker（如果只改了 compose/后端代码）
print("[2/5] 重建 api + worker 容器...")
out, err = run(
    f"cd {REMOTE_DIR} && docker compose up -d --build api worker 2>&1 | tail -8",
    timeout=600,
)
print("  ", out.strip())
if "error" in err.lower() or "error" in out.lower():
    print("  [警告] 构建可能有错误，检查上方输出。")

# 3. 等 api 健康（最长 90s）
# 不依赖容器内 curl（api 镜像未安装），用 python 探测；同时 docker healthcheck 状态作为兜底。
print("[3/5] 等待 api 容器健康...")
healthy = False
for i in range(18):
    # 优先：宿主机直连容器映射端口（127.0.0.1:8002）
    out, _ = run("curl -fs http://127.0.0.1:8002/api/v1/health/live 2>/dev/null && echo OK_HOST",
                 timeout=15)
    if "OK_HOST" in out:
        print(f"  api 健康·宿主机直连（{(i+1)*5}s）")
        healthy = True
        break
    # 兜底：查 docker healthcheck 状态（不依赖容器内任何工具）
    out, _ = run('docker inspect --format "{{.State.Health.Status}}" aigc-studio-api-1 2>/dev/null',
                 timeout=10)
    if "healthy" in out:
        print(f"  api 健康·healthcheck（{(i+1)*5}s）")
        healthy = True
        break
    time.sleep(5)
if not healthy:
    print("  [错误] api 90s 内未健康，终止。请手动 `docker logs aigc-studio-api-1` 排查。")
    client.close()
    sys.exit(1)

# 4. 强制重建 frontend —— 「502 第三形态」的根治步骤
print("[4/5] 强制重建 frontend（刷新 nginx 对 api 新 IP 的解析）...")
out, _ = run(f"cd {REMOTE_DIR} && docker compose up -d --force-recreate frontend 2>&1 | tail -4",
             timeout=120)
print("  ", out.strip())
# frontend 起 nginx 需几秒
time.sleep(8)

# 5. 公网健康验证
print("[5/5] 公网健康验证...")
out, _ = run(f"curl -fs http://127.0.0.1:5000/api/v1/health/live 2>&1; "
             f"echo '|公网|'; curl -fs -o /dev/null -w '%{{http_code}}' http://{env['host']}/saios",
             timeout=20)
print("  ", out.strip())

# 公网 API 也验一下（经宿主机 nginx + 容器 nginx 两层）
out2, _ = run(f"curl -fs -o /dev/null -w '%{{http_code}}' http://{env['host']}/api/v1/health/live",
              timeout=20)
api_code = out2.strip()
if api_code == "200":
    print(f"  ✅ 公网 API 健康（{api_code}）—— 502 第三形态已规避")
else:
    print(f"  ⚠️ 公网 API 返回 {api_code}，可能仍需 `docker restart aigc-studio-frontend-1`")

client.close()
print("\n部署完成。worker 日志可用 `docker logs --tail 20 aigc-studio-worker-1` 查看。")
