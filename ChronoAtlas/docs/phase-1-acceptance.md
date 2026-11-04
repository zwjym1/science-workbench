# 第一阶段验收记录

日期：2026-10-20。

已交付 `out/hexi-corridor.mp4`：《为什么河西走廊如此重要？》地图动画原型，30秒、900帧、30fps、1280×720、H.264、约8.9MB，无旁白音轨。

## 已验证

- Windows 环境具备 Node、Git、FFmpeg、Chrome。
- npm run typecheck 与 npm run build 通过。
- npm install 完成，安装时审计显示0 vulnerabilities（仅代表当时依赖审计结果）。
- catalog验证4份非空GeoJSON，4个城市坐标与来源精确一致；生成来源SHA256与SQLite目录。
- API health/places/sources/projects返回200，无效项目输入返回400。
- 视频已用FFprobe确认编码、尺寸和时长，并用FFmpeg完整解码通过；机器结果见 out/verification.json。
- 已目视检查网页1600×1100截图，以及视频四段抽帧和18秒关键帧。地图、河流、地形面、中文、箭头和进度正常。
- 原始地理数据完整存档；运行时terrain.json仅保留祁连山、戈壁、青藏高原，属性与几何不变；前端生产JS约2.89MB/gzip974KB。

## 实施范围

网页编辑器支持预览、分镜跳转、标题/颜色/分镜文字编辑、本机草稿和JSON导出。渲染与预览共用Remotion组件。SQLite基础API和数据目录已建，但前端尚未连接项目API；后台渲染队列尚未实现。

首片仅展示现代地理参照和通道节点示意，非古代道路复原。没有采用未核验的历史疆界、古城址或战役轨迹。AI编导、经史学审核的历史数据库、配音音乐和一键后台合成仍按roadmap开发，尚不能自动完成任意选题纪录片。

原会话已读取全部可用轮次，但其助手正文是引用标记，无法恢复原长提示词；当前完整用户提示已存档 user-prompt.md，缺失情况见 project-brief.md。
