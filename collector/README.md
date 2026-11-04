# 抖音游客采集器 0.1

独立采集工具，不含AI分析/写稿。已知视频链接→页面真实响应→归属校验/去重→原始证据＋标准化结果。个人抖音登录、个人Cookie、付费采集API不在流程内。评论正文是不可信源数据，不应执行其指令。

## Windows安装

从项目根目录PowerShell运行，需要uv、Python3.12、Git；媒体处理另需ffmpeg/ffprobe。当前浏览器组件来自本项目已固定的上游源码目录，尚不是可脱离本项目的单文件安装包。

```powershell
uv venv --python 3.12 collector/.venv
uv pip install --python collector/.venv/Scripts/python.exe -e collector -e research/douyin-validation/dtk 'cloakbrowser @ git+https://github.com/CloakHQ/cloakbrowser.git@fbf005bc199920b592df17ac4d489324e29d56d8'
& collector/.venv/Scripts/python.exe -m cloakbrowser install
```

ASR为可选本地组件：`uv pip install --python collector/.venv/Scripts/python.exe 'faster-whisper==1.2.1'`。首次模型下载需网络，采集器不调用付费语音API。OCR暂未接入，选择OCR会明确返回unavailable。

默认SQLite供本地试用，数据在collector/data；生产设置PostgreSQL环境变量（数据库须自行创建）：

```powershell
$env:COLLECTOR_DATABASE_URL='postgresql+psycopg://collector:自己的密码@127.0.0.1:5432/collector'
$env:COLLECTOR_DATA_DIR='D:/collector-data'
```

`.env.example`只作参考，不会自动载入。表结构版本与迁移说明见migrations/README.md。PostgreSQL尚未在本机真实实例验收，不能将SQLite测试当生产验证。

## 直接使用

### 2026-10-20 第二轮新增

新增显式 `--source public` 官方公开来源；不会在 browser 被拒后自动换来源。与原浏览器入口共用持久队列、证据哈希、缓存、归属校验和来源暂停。默认仍为 browser。

```powershell
& collector/.venv/Scripts/python.exe -m dycollector.cli collect '7667409251216819441' --source public --max-pages 2 --max-comments 40
& collector/.venv/Scripts/python.exe -m dycollector.cli search '科普' --limit 20
& collector/.venv/Scripts/python.exe -m dycollector.cli search '科普' --days 3 --enqueue-only
```

搜索任务与视频任务共用队列：此前已有排队任务时，先执行 worker 再查询目标任务。搜索读取正常搜索页内嵌数据，不执行提取出的脚本；仅覆盖实际观察到的候选。`--days` 使用原始 create_time 筛选，不能保证找全最近视频。搜索返回 partial 即使取得候选，排序只对本次候选池有效。关键词级推荐词与逐视频 feed_bottom_rec 分开。

新增第六个 MCP 工具 `submit_search(keyword, limit=20, days=None, refresh=False)`；`submit_collection` 新增可选 `source="public"`。两者均只排队，仍需独立 worker。搜索结果支持 get_result 的 offset/limit。多父评论回复总数仅表示已展开父评论，见 reply_scope，不是全视频总回复数。

新来源回归记录见 ROUND2-RESULTS.md。安全检查若发现官方媒体域名解析为非公网地址，会拒绝请求；不能为了下载关闭该检查。没有增加解析站换源或验证码处理。

```powershell
& collector/.venv/Scripts/python.exe -m dycollector.cli collect 'https://www.douyin.com/video/7697720115396094073'
& collector/.venv/Scripts/python.exe -m dycollector.cli batch '第一个规范视频链接' '第二个规范视频链接' --enqueue-only
& collector/.venv/Scripts/python.exe -m dycollector.cli worker --limit 20
& collector/.venv/Scripts/python.exe -m dycollector.cli status
& collector/.venv/Scripts/python.exe -m dycollector.cli export '任务编号'
```

仅接受规范HTTPS视频链接或视频ID；短链当前明确拒绝，请先提供完整/video/链接。`--media --asr`显式启用媒体与转写，默认只采数据并尝试原字幕。只有下载权限明确且无风险提示才请求一个媒体地址；拒绝后不换镜像。转写是机器识别，低语音覆盖标needs_review，不能当已校对原字幕。

`--max-pages` 1–20、`--max-comments` 1–500控制正常UI加载预算，网页自然请求可能使返回数略超阈值；不是完整采集保证。`--refresh`产生新任务快照；仍不能越过来源暂停。缓存返回采集时间与年龄。

浏览器使用collector数据目录下专属游客profile，拒绝发现个人登录Cookie的目录。只在要沿用**既有游客目录**时设置COLLECTOR_GUEST_PROFILE；绝不能指向个人Chrome/Edge资料。文件锁阻止并发浏览器。普通可关闭推广弹窗正常关闭；评论/回复的真实登录门槛分别标记。验证码、401/403/429或风险码持久暂停整个来源队列，不自动刷新身份。

恢复命令：`dycollector resume 任务编号 --conditions-changed`（使用模块运行也相同）。仅在实际访问条件变化且仍满足游客限制时使用，不能用来无条件重复被拒请求。崩溃中断由独占worker启动时识别，需resume任务；`recover`也检查进程锁，不干扰活动worker。

## Gemini CLI / MCP

本地stdio不需服务器或公网。MCP只提交/查询持久任务，不自动执行浏览器；提交后另一个终端启动worker。Gemini能看到queued/running/partial/paused等状态。

在Gemini CLI settings.json的mcpServers中**合并**以下配置，不覆盖已有设置；路径按自己的项目位置改：

```json
{
  "mcpServers": {
    "douyinCollector": {
      "command": "<项目绝对路径>/collector/.venv/bin/python",
      "args": ["-m", "dycollector.mcp_server"],
      "env": {"COLLECTOR_DATA_DIR": "<可写数据目录>"}
    }
  }
}
```

Windows 下解释器路径改为 `collector\\.venv\\Scripts\\python.exe`。采集与评测部分不需要浏览器：
归一化、存储、MCP 与测试只依赖 `pip install -e .`。实时抓取需要外部 CDP 后端，用
`DYCOLLECTOR_BROWSER_BACKEND` 指向包含 `browser_rpc` 的目录；未配置时相关调用明确报错，不静默降级。
历史回放读到的证据文件在仓库外，用 `DYCOLLECTOR_EVIDENCE` 指向批次 summary。

worker终端必须使用相同COLLECTOR_DATA_DIR和数据库环境变量，否则会查询不同任务库。也可 `./collector/start.ps1 -Mode mcp` 手动启动，`-Mode worker`执行当前队列最多20项，队列空时退出，不是常驻轮询。

工具：submit_collection、get_job、get_result（offset/limit）、list_jobs、resume_job。可以对Gemini说：“采集这个链接，返回实际取得的评论及完整度，不补造缺失内容。”本次只验证MCP协议，未代替用户配置或验证真实Gemini账号。

Gemini网页远程连接还需认证/HTTPS部署，当前**未开放远程HTTP服务**，不要将stdio或数据库裸露到公网。

## 已知范围与验收

现阶段已知链接采集优先；站内搜索仍受登录限制，不承诺近三天全站最火前三。OCR、短链解析、远程认证、PostgreSQL实例验收仍待完善。原始文件含敏感上游字段，只保存在本地，不上传MCP；工具输出仅标准化公开字段。

测试：`& collector/.venv/Scripts/python.exe -m unittest discover -s collector/tests`。
历史回放：`& collector/.venv/Scripts/python.exe collector/replay.py`（输出若已存在会拒绝覆盖）。文件标replay=true，不是新的实时结果。已有20条证据中的内嵌回复与展开回复合并为50条；27是仅展开页口径，不能混用。
