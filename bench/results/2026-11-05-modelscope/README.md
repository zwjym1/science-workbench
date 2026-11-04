# 2026-11-05 · ModelScope API-Inference 真实模型跑分

这是一次真实模型在 25 个 case 上的运行记录，不是脚本策略。**四个模型里只有第一个跑完**，另外三个在额度耗尽后无法继续；这份目录如实保留了能证明的部分，也保留了失败的部分。

- 端点：`https://api-inference.modelscope.cn/v1`（OpenAI 兼容）
- case 集：`bench/clipbench/cases/core.json`，sha256 `2d275e14…2860`
- runner：`clipbench matrix`，每个模型独立 workdir，不共享缓存
- 时间：2026-11-05 00:12–00:34（UTC+8）

## 结果

| 模型 | 完成度 | 通过 | 总成功率 | 普通 case 成功率 | p50 | p95 | tokens（估算） | 渲染秒 |
|---|---|---|---|---|---|---|---|---|
| `Qwen/Qwen3.5-27B` | 25/25 | 19 | 76.0% | 94.7%（18/19） | 30.4s | 87.6s | 101,626 | 96.5 |
| `Qwen/Qwen3.5-122B-A10B` | 16/25 | 9 | 不适用 | 66.7%（8/12） | 12.3s | 45.0s | 63,837 | 26.7 |
| `Qwen/Qwen3.8-Flash-Next` | 0/25 | 0 | 不适用 | 不适用 | — | — | — | — |
| `ZhipuAI/GLM-5.2` | 0/25 | 0 | 不适用 | 不适用 | — | — | — | — |

后两个模型没有产生任何模型调用：第一次请求即返回 `429 insufficient balance`。它们的 0 分不是模型能力，是没跑。

122B 的 9 个 case 因同样的 429 中断（13–16、18、22–25），因此不能拿 9/25 当作它的成功率；可比的只有已完成的 12 个普通 case：8 过 4 败。

## 两个必须说明的异常

**core-19 是基础设施错误，不是模型失败。** 运行到第 3 步时出现 `SSL: UNEXPECTED_EOF_WHILE_READING`，归因层把它记为 `environment`。所以上表的 94.7% 里包含这一条；按实际完成的普通 case 算是 18/18。这个 case 应在额度恢复后重跑。

**core-21 这条“已知失败”被模型绕过了。** 它要求使用不存在的素材 `zzz-nonexistent`；规则层只检查时长、镜头数、引用、素材下限与渲染，不校验素材 id 是否真实存在，于是模型换成了别的素材并通过。这不是模型的胜利，是规则层的盲区，已记录为待补判据（`required_asset_ids` / `assets_known`）。在补上之前，“6 个已知失败全部失败”这句话不成立，实际是 5 个失败、1 个漏过。

## 失败归因（Qwen3.5-27B，仅失败项）

```
planning 3 / argument_generation 2 / environment 1
```

`attribution.md` 里有逐 case 信号。通过项被排除在分布外，`unclassified` 是合法输出。

## 为什么停在这里

账户在累计约 330 次模型调用后返回 `insufficient balance`，之后对所有模型立即 429。公开博客写的“每天 2000 次”没有在这个账户上兑现，可能是未绑定阿里云/未实名，或免费额度按余额而非次数计。**没有额度就不能跑，也不拿部分数据冒充四模型对比。**

恢复额度的路径（按顺序试）：

1. 在 ModelScope 个人中心确认阿里云绑定与实名认证，再看“API 使用情况”的剩余额度。
2. 等次日额度重置后再跑，一个模型约 120–160 次调用。
3. 换一个有免费额度的 OpenAI 兼容服务（如智谱 GLM-4.7-Flash 免费档），同一套 `matrix` 命令只改变量。

## 复现

```bash
export CLIPAGENT_BASE_URL=https://api-inference.modelscope.cn/v1
export CLIPAGENT_API_KEY=ms-...        # 不要提交
export CLIPAGENT_MODEL=Qwen/Qwen3.5-27B
cd bench
python -m clipbench.cli matrix --models Qwen/Qwen3.5-27B \
       --workdir /tmp/matrix-work --out /tmp/matrix-out
```

judge 尚未运行（额度耗尽），所以 `quality` 仍是 `null`；人工 10 条标注与 kappa 也尚未做。本目录只主张上表里“已完成”的数字。
