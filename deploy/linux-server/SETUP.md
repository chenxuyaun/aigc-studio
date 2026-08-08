# AIGC Studio Linux 服务器部署指南（另一台常开机电脑）

> 目标：把平台完整部署到一台 Linux 常开机电脑，实现公网访问 + 域名 HTTPS。

## 一、系统准备（一次性）

```bash
# Ubuntu 22.04/24.04 LTS（推荐）或 Debian 12
sudo apt update && sudo apt install -y docker.io docker-compose-plugin git curl
sudo systemctl enable --now docker

# 防火墙（只开需要端口）
sudo ufw allow 22/tcp      # SSH
sudo ufw allow 80,443/tcp  # HTTP/HTTPS（有公网 IP + Caddy 时）
sudo ufw allow 5000/tcp    # 平台前端（无域名穿透时用）
sudo ufw enable
```

## 二、部署平台

```bash
# 拉代码（从现电脑 git 仓库推送后克隆，或直接拷贝）
git clone <你的仓库地址> /opt/aigc-studio
cd /opt/aigc-studio

# 环境变量：把现电脑的 .env 复制过来（或按 .env.example 生成）
cp .env.example .env   # 然后填入与现电脑一致的密钥

# 启动（compose.cloud.yaml 是 Linux 版，含 Caddy 自动 HTTPS）
docker compose -f deploy/cloud/compose.cloud.yaml up -d --build
```

## 三、域名 HTTPS（公网 IP 方案）

1. 买域名（阿里云/腾讯云/Namesilo 均可，约 50 元/年）
2. DNS 添加 A 记录：`你的域名 → 公网 IP`（TTL 300）
3. 改 `deploy/cloud/Caddyfile`：`aigc.example.com` → 你的真实域名
4. `docker compose -f deploy/cloud/compose.cloud.yaml up -d caddy`
5. Caddy 自动申请 Let's Encrypt 证书（域名认证自动完成，90 天自动续期）

## 四、数据迁移（可选，整体搬家时）

```bash
# 现电脑备份（每日自动备份在 backups/ 已有）
# 把 backups/ 最新 sql.gz + storage + tdai-memory 传到新电脑
# 新电脑导入：gunzip -c xxx.sql.gz | docker exec -i <mysql> mysql ...
# 参考 docs/PROJECT_SUMMARY.md 第 10 节迁移步骤
```

## 五、grok2api / 注册机（LLM 网关）

- 新电脑网络若能直连 grok.com：同样部署 grok2api + 注册机（本地运行）
- 不能直连：平台自动降级 cpa 网关（如果新电脑也部署 cli-proxy-api + 账号）
- 密钥文件务必 gitignore（.env 已忽略）

## 六、运维

- 每日备份：平台自带（凌晨 2:00 MySQL 备份到 backups/）
- 建议 crontab 加磁盘监控：`df -h / | awk 'NR==2 && $5+0>85 {print "磁盘告警"}' | mail -s "disk" you@x.com`
- 系统更新：`sudo apt update && sudo apt upgrade`
