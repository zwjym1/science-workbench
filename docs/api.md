# M1 API 与数据契约

FastAPI `/docs` 提供实时 OpenAPI（本地8000端口）；界面通过同源 `/api` 访问后端。除了 health、login、logout，业务接口需要 session Cookie。API 默认不开放跨域。

| 方法 | 路径（后端） | 请求/结果 |
|---|---|---|
| POST | /auth/login | `{password}` → HttpOnly session |
| GET | /auth/me | 当前用户，未登录401 |
| POST | /auth/logout | 删除会话 Cookie |
| POST | /imports | 见 samples/demo-import.json → id/status/result/error/is_demo |
| GET | /imports | 最近100个任务，不返回原始内容 |
| POST | /imports/{id}/retry | 失败/pending重试；成功任务不重复执行 |
| GET | /videos | q、is_demo、offset、limit → items/total |
| GET | /videos/{id} | 标准视频、评论、历史指标快照 |
| DELETE | /library?is_demo=true或false | 删除对应资料及原始任务；调用前自行备份 |
| GET | /health | 数据库连通检查 |

输入必须显式提供 is_demo；数据提供者负责如实标记。示例只使用 example.com，不构成真实来源。标准JSON的data.videos结构包含 platform/external_id/title/source_url/collected_at/published_at/content/comments/related_searches/tags/metrics。comments 必须具有稳定 external_id 和 text；缺少稳定ID的采集器需在适配器中生成确定性ID并说明冲突策略。

采集器集成优先让现有工具输出此标准包；若输出结构不同，实现 CollectorAdapter.normalize，并注册到 ADAPTERS，同时扩充 ImportRequest 允许的 adapter。不要修改已有采集器抓取逻辑。M1尚无机器专用令牌；不要给采集器长期存储网页登录 Cookie。自动出站 Agent 接入前需实现可撤销、限权的机器凭证。

M2之后计划实体：evidence、demand_cluster、topic、score_rule、topic_score、project、decision、conversation_message、script_version、script_block、fact_check、storyboard、provider_config、ai_job、usage_ledger、performance_snapshot。此为设计，不是已创建的数据库表。
