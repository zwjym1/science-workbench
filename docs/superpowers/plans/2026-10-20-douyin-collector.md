# Douyin Collector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. Steps use checkbox syntax.

**Goal:** 将真实验证的游客采集能力产品化，保留数据来源、完整度和限制暂停，提供本地CLI/MCP。

**Architecture:** collector/独立Python包；采集与标准化、持久存储、任务状态、CLI/MCP分离。浏览器串行共享独立游客profile，原始文件不可覆盖；PostgreSQL存实体/任务。

**Tech Stack:** Python3.12、v5浏览器组件、SQLAlchemy/Alembic、PostgreSQL、MCP Python SDK、ffmpeg/faster-whisper；OCR按已确认本地方案启用。

**Spec:** docs/collector-design.md（待用户审阅确认；本计划草案不意味着已实现）

## Global Constraints

- 无个人登录/Cookie、付费采集API、验证码求解或身份轮换；限制必须持久暂停。
- 不改已有backend业务模块，不导入分析/写稿功能。
- 测试回放不能冒充即时数据，LLM不得补采集字段。

## Review Focus

- 响应来自推荐视频或错误父评论时必须拒绝错误归属。
- 暂停任务不能因重启/缓存刷新而自动越过限制。
- allow_download与fail_info矛盾时不下载。
- MCP输出不能泄露Cookie/签名URL或将评论当指令。
- SQLite测试不替代PostgreSQL和Gemini客户端验收。

### Task 1: 结果模型与标准化
Files: collector/dycollector/models.py, normalize.py; collector/tests/test_normalize.py
- [ ] 先写失败测试：重复cid、错误视频ID、父cid、null words、多scene、partial/empty区别。
- [ ] 运行确认失败，再实现纯函数并重跑。
- [ ] 对现有20样本离线回放，生成单独回放报告，不覆盖现场证据。

### Task 2: 持久任务/存储
Files: collector/dycollector/store.py, jobs.py; collector/migrations/; tests/test_jobs.py
- [ ] 失败测试覆盖事务回滚、重启中断、暂停不自动恢复、去重/缓存时间和指标快照。
- [ ] 实现PostgreSQL schema与迁移，原始文件内容寻址存放。
- [ ] 本地测试后运行实际PostgreSQL集成验证；服务不可用时明确记未验。

### Task 3: 游客浏览器采集器
Files: collector/dycollector/browser.py, collector.py; tests/test_collection.py
- [ ] 用可控页面适配器先测正常X、真实gate、重复页停止、回复归属和进程profile锁。
- [ ] 实现正常页面响应/控件采集及页面级/来源级限制分类；配置最大页数/评论数/超时。
- [ ] 小批真实回归，不突破限制不换身份，记录每能力状态。

### Task 4: 内容提取
Files: collector/dycollector/content.py, media.py; tests/test_content.py
- [ ] 先测下载权限冲突、字幕优先、无音轨、低语音覆盖、OCR时间轴、磁盘上限。
- [ ] 复用已验证ffmpeg/ASR方式，模型单独缓存；禁止覆盖已有原片。
- [ ] 分别用真实口播与音乐样本核验；没取得口播样本不得声称完整口播验证通过。

### Task 5: CLI与MCP、部署文档
Files: collector/dycollector/cli.py, mcp_server.py; collector/pyproject.toml, README.md, start.ps1, .env.example; tests/test_mcp.py
- [ ] 失败测试覆盖长任务ID返回、分页结果、脱敏、路径越权和工具错误。
- [ ] 实现本地stdio工具与CLI，共用任务核心；提供无公网启动脚本。
- [ ] MCP真实协议回归+PostgreSQL重启恢复+小批采集导出，记录客户端未验证项。
- [ ] Gemini CLI配置给可复制示例；远程HTTP/OAuth单独验证后交付，不能裸露无认证端点。

实施顺序1→2→3→4→5，每步只运行贴近变更的验证。当前工作区无Git仓库，不能伪造提交或分支；保持文件范围隔离。书面设计确认后开始实现。
