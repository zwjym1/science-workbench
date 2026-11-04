# 后续开发交接

当前先验收可渲染地图和编辑预览。AI、精确历史疆域、战役路线、配音与音乐不在首个演示里伪装完成。

历史数据库下一版建立 source、license、place、place_alias、historical_geometry、claim、claim_evidence；geometry记录 valid_from/valid_to、年代精度、空间精度和审核状态。古今地点关联不等于相同坐标。CHGIS、历史地图集等需逐项确认许可，不能因可下载就认定可商用。

AI 分镜结构：topic、researchClaims[{text,sourceIds,status}]、scenes[{start,duration,narration,camera,layers,sourceIds}]。执行前校验场景总长、已知地点ID、坐标范围、来源许可、史实审核状态。服务端使用供应商适配器，不在浏览器存密钥。未接入模型时返回明确的未配置状态，不返回冒充AI的模板结果。

镜头指令仅允许 camera、route、label、territory、time，限制坐标、缩放与时长。后续疆域/行军引擎复用 GeoJSON Feature 的时间有效区间，不让模型直接生成未经核验的边界点。
