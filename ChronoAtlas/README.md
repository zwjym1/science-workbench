# ChronoAtlas

中国古代史 AI 地图纪录片自动化系统，第一阶段：可编辑、可渲染的河西走廊地图短片。

## 启动

Windows PowerShell，进入本目录，Node.js 24：

```powershell
npm ci
node scripts/catalog.mjs
npm run dev
```

打开终端显示的本地网址。支持播放/拖动进度、分镜跳转、编辑标题/朱红色/四段解说、浏览器草稿和导出JSON。配套 Remotion Studio：`npm run studio`。

## 渲染与验收

```powershell
npm run typecheck
npm run build
npm run render -- --browser-executable="C:/Program Files/Google/Chrome/Application/chrome.exe"
node scripts/verify-video.mjs
```

输出 `out/hexi-corridor.mp4`，30秒、1280×720、30fps、H.264、无旁白音轨。导出的配置可通过 `npm run render -- --props="C:/完整路径/hexi-props.json"` 使用；覆盖同名视频前请保留需要的版本。

`node server/index.mjs` 启动本地 API（127.0.0.1:4318）。GET `/api/health`、`/api/places`、`/api/sources`、`/api/projects`；POST `/api/projects` 保存含 title 的 JSON。编辑器当前保存到浏览器，并可导出配置；SQLite API 尚未连接到编辑器。渲染使用命令行，后台队列尚未实现。

## 数据真实性与授权

地图是 Natural Earth 的现代地理参考，公共领域、允许商业使用，见 https://www.naturalearthdata.com/about/terms-of-use/ 。所有原始地理数据已离线打包，来源及 SHA256 在 `docs/sources.json`；`scripts/catalog.mjs` 验证城市坐标与原始数据完全一致。下载记录固定，但源分支为master，复现以本地SHA256为准。

兰州、武威、张掖、敦煌表示现代城市位置；朱红连线仅为方向和节点关系示意，不是古代道路或精确行军。水系为现代概化数据；首版不绘制未经证实的古代河道、疆域或战役。城池符号为项目原创通用图标，不代表遗址形制。

事实依据 UNESCO 长安—天山廊道路网说明：https://whc.unesco.org/en/list/1442/ 。仅核对历史事实并独立撰写短片文字，未下载或复用网页影像；网页说明自身许可为 CC-BY-SA IGO 3.0，不应套用到站内所有图片。

## 工程边界与后续

已具备地图/河流/城池参考点、四镜头、朱红通道、时间轴、纸张质感、缩放镜头、可编辑预览和基本 SQLite API。AI编导、历史精确疆域与战役、配音音乐、后台渲染队列仍待开发；不以模板冒充AI研究。

完整当前提示词：`docs/user-prompt.md`；旧对话可恢复内容与缺失说明：`docs/project-brief.md`；架构规范与验收：`AGENTS.md`；阶段交接：`docs/roadmap.md`。
