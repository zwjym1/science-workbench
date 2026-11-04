# science-workbench — AI 科普内容采集与自动化评测工作台

[![tests](https://github.com/zwjym1/science-workbench/actions/workflows/tests.yml/badge.svg)](https://github.com/zwjym1/science-workbench/actions/workflows/tests.yml)

一个面向科普视频生产的 Agent 工作台：公开数据采集与规范化管道、FastAPI 服务端与后台 worker、
Next.js 控制台，以及配套的 unittest/pytest 测试集。

## 我能说清楚的部分（面试可现场演示）

- `collector/`：抖音公开内容采集管道。6 个 stdio MCP 工具、独立 worker 领任务、按视频与采集选项做缓存命中、
  结果标准化与评论去重/父子关系还原、原始证据哈希、来源暂停与恢复。
  **62 项 unittest 全绿**（含真实 MCP 子进程握手、发现、提交与非法 URL 负例）。
- `backend/`：FastAPI + SQLAlchemy 2 + Alembic 迁移 + SQLite/PostgreSQL 双方言，15 项 pytest 用例。
- `agent/`：自写的 ReAct 循环（规划→行动→观察→重规划），5 个 Function Calling 工具，
  按 `sha256(tool, args)` 做内容寻址的产物复用，失败即观察、由模型重新规划而不盲目重试；
  附带一份等价的 LangChain 实现做对照，并有参数面一致性测试；`rag.py` 是不依赖训练权重的
  检索（CJK 二元组 + BM25 + 哈希特征向量 + 短语重排 + 引用校验）。**55 项 unittest**，
  `clipagent demo` 在干净环境跑完整条链路：4 镜头、40.000 秒、320×180 的 h264，
  第二次运行 `attempts=0, reused=5`。
- `bench/`：批量评测。**25 个带约束的 case**（6 个已知失败/边界拒绝案例）、四个指标
  （任务成功率 / 质量分 / 时延 / 成本）、规则层校验（时长、镜头数、引用覆盖、素材数量、
  ffprobe 回读、时延上限）、按 case 断点续跑、两次运行的逐 case 回归对比，以及从 trace
  读出的失败归因（五类：环境 / 参数生成 / 工具选择 / 上下文 / 规划，无法归类时如实标
  unclassified）。另有固定提示词、固定温度的 LLM-as-a-Judge 与人工标注一致性计算
  （Cohen's kappa、二次加权 kappa），以及同一 case 集上的多模型对比（`matrix`）。**63 项 unittest**。质量分在 judge 真正跑过之前一律留空，
  不把未评分的 case 平均成"质量"。
- `compose.yaml`：db / backend / worker / frontend / caddy 四个服务一键起。
- **合计 195 项自动化测试**，CI 四个 job（collector / backend / agent / bench）每次 push 全跑。

## 诚实边界（不宣称已完成）

- PostgreSQL 迁移脚本已提供，但**尚未在真实 PG 实例上验证**，SQLite 测试不能替代它。
- OCR 返回 unavailable；短链接明确拒绝，仅支持规范 HTTPS 视频链接/ID。
- 分析模型客户端未做真实联调。部署已在本机 Docker Compose 实测（db/backend/worker/frontend/caddy 五服务，`/api/health` 200，登录后 `/api/videos` 200），但公网只是临时 quick tunnel：无固定域名、无 SLA，本机或隧道停止即失效。认证仍只有单一管理员口令。
- 评测里的"模型"一栏在本地跑的是 `scripted-reference-policy`，它由 case 约束推出工具序列，
  只证明 runner 与判据可用，**不是模型能力测量**；真实模型跑分与四模型选型对比需要 API key，
  在跑出来之前不作宣称。judge 的 Rubric 权重是初始值，需人工标 10 条后按 kappa 校准。
- 数据规模：截至 2026-10-20 为 21 条视频、129 条一级评论、50 条合并回复（去除 3 条重复），
  其中 20 条来自标记 `replay=true` 的历史回放，不是实时采集。
- 交接打包件（handoff/*.zip）内含真实采集到的评论与回复原文，**不公开发布**；仓库只保留代码、测试与聚合后的规模数字。
- 合规硬约束写在代码里而非文档：不使用个人账号与 Cookie（检测到常见个人登录 Cookie 名称即拒绝启动）、
  不使用第三方付费数据 API、不绕过验证码与访问限制、缺失字段不得由模型补造。

## 运行

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env          # 自行填写 ADMIN_PASSWORD / SESSION_SECRET
cd collector && python -m unittest discover -s tests
```

Agent 单独一个包，不依赖上面任何一个：

```bash
cd agent && pip install -e . && python -m unittest discover -s tests
clipagent demo --workdir /tmp/clipagent-demo     # 不需要模型 key
```

`clipagent` 的 `synthesize_tts` 在未配置语音引擎时返回 `unavailable` 并写一条等长静音轨：
时长是真的、声音不是，状态如实标注。`render_and_check` 用 ffprobe 回读时长与分辨率再判定，
没有 ffmpeg 时同样返回 `unavailable`，不会伪造成功。
