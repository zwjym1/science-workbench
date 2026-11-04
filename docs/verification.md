# 实际验证记录

日期：2026-10-20，Windows，Python 3.11.15、Node 24.19.0。

## 已执行

- 后端 `python -m pytest -q`：8 passed。测试使用隔离内存 SQLite；包含登录/限流、幂等/去重、资料原始保存、快照、缺失值、模拟隔离、删除、事务失败重试、局部补采、历史包晚到和显式字段清除。
- 测试有1条 Starlette TestClient 对 httpx 的弃用警告；未忽略测试失败。
- SQLite `alembic upgrade head`：成功；`alembic current`：0001 head；`alembic check`：No new upgrade operations detected。
- 实际启动 Uvicorn 于127.0.0.1:8000；HTTP health 200、登录200、示例导入200/succeeded、资料库1视频2评论。
- 重启后端后 HTTP读取：仍为1视频、2评论、1指标快照，验证资料不依赖进程内状态。
- `docker compose --env-file .env.example config --quiet`：退出码0。修复了中文工作区目录造成默认项目名为空的问题。
- 只读代码审查后修复了补采资料覆盖、评论不更新、历史包晚到覆盖、摘要忽略字段显式提供状态的问题；同步导入放在线程池，避免阻塞异步事件循环。
- 前端 npm install 成功，audit报告0漏洞；TypeScript检查与 Next.js 生产构建退出码0。
- 实际生产前端与后端代理：首页200、登录200、会话200、资料列表200。
- 浏览器实际点击验收：登录→数据导入→填入明确模拟示例→提交→任务已完成→资料库保持1视频2评论→展开可读取两条模拟评论及null指标。

## 尚未执行或不能据此证明

- Docker引擎连接失败（dockerDesktopLinuxEngine管道不存在），未运行镜像构建与容器启动。
- 未验证真实PostgreSQL迁移/并发锁、备份恢复、实际云服务器部署、HTTPS证书及iPhone。
- 无采集器代码、模型密钥或真实数据；没有抖音接入、模型调用和费用测试。
- 没有容量压测；不能根据少量模拟数据宣称支持大规模导入。
