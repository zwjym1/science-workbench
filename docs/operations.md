# 部署、备份和恢复

生产使用私有 Ubuntu 主机与域名，先确认 Docker Compose 可运行。不要把管理密码或 `.env` 提交到 Git。Caddy 自动管理证书；首次部署需实际确认域名、证书和 iPhone Cookie 登录。当前没有远程服务器凭证，因此没有执行云部署。

## 单机部署（2026-11-04 在 Windows + Docker Desktop 实测）

```sh
cp .env.example .env      # 填 ADMIN_PASSWORD / SESSION_SECRET / POSTGRES_PASSWORD，
                          # 并把 DATABASE_URL 里的密码改成同一个
docker compose up -d --build
docker compose ps         # backend/db 应为 healthy
curl http://127.0.0.1/api/health
```

实测结果：`db`、`backend`、`worker`、`frontend`、`caddy` 五个服务启动，根路径 200、`/api/health` 返回 `{"status":"ok"}`，用 `.env` 里的管理员密码登录后 `/api/videos` 返回 200。

一个已修复的启动问题：`alembic` 控制台脚本的 `sys.path` 不含工作目录，容器里直接跑 `alembic upgrade head` 会报 `ModuleNotFoundError: app`。Dockerfile 已改成 `python -m alembic upgrade head`，这样当前目录进入 `sys.path`。

没有域名时用 `SITE_ADDRESS=:80` 且 `COOKIE_SECURE=false`，只能 HTTP；有域名时把 `SITE_ADDRESS` 设成域名，Caddy 自动签证书，并把 `COOKIE_SECURE=true`。

临时公网演示可用 Cloudflare quick tunnel（无账号、无 uptime 保证，本机或隧道停止即失效，地址每次重启都会变）：

```sh
cloudflared tunnel --url http://localhost:80 --no-autoupdate
```

这套 Compose 部署的是采集与选题台（FastAPI + PostgreSQL + Next.js），不是 `agent/` 的评测台；对外描述时不要把两者混为一谈。

## PostgreSQL 备份（Ubuntu shell，项目根目录）

```sh
mkdir -p backups
chmod 700 backups
docker compose exec -T db pg_dump -U workbench -d workbench -Fc > backups/workbench.dump
test -s backups/workbench.dump
```

文件含私人评论；应加密复制到另一存储，并配置每日备份、30天轮换。上面固定文件名仅用于手工验收，自动备份需使用时间戳避免覆盖。另行保护 `.env` 与 Compose 配置；不要将密钥放进公开备份。

## 恢复到隔离数据库验证（Ubuntu shell）

```sh
docker compose exec -T db createdb -U workbench workbench_restore
docker compose exec -T db pg_restore -U workbench -d workbench_restore --no-owner < backups/workbench.dump
docker compose exec -T db psql -U workbench -d workbench_restore -c 'select count(*) from videos;'
```

对比任务、视频、评论、指标数量；在隔离实例以恢复库启动服务，登录确认资料一致。确认后再安排正式切换，勿直接覆盖当前库。此恢复演练尚未实际执行。

SQLite 开发备份：停止后端后复制 workbench.db；恢复时也先停止后端，保留旧文件再替换。重启执行 `alembic upgrade head`，查 health 与核心资料。不得依赖复制运行中数据库文件作为一致性备份。

日志通过 `docker compose logs` 查看，记录路径、状态码、耗时、失败任务ID，不记录密码/请求正文。为 Docker 配置日志轮转。任务 pending/failed 通过重试 API 恢复；先查看失败日志，反复失败需修正适配数据，不能无限重试。M1不发生模型扣费。
