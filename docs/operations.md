# 部署、备份和恢复

生产使用私有 Ubuntu 主机与域名，先确认 Docker Compose 可运行。不要把管理密码或 `.env` 提交到 Git。Caddy 自动管理证书；首次部署需实际确认域名、证书和 iPhone Cookie 登录。当前没有远程服务器凭证，因此没有执行云部署。

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
