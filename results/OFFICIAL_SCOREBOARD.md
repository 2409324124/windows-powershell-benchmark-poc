# Windows PowerShell Benchmark 官方成绩

更新时间：2026-08-23  
榜单版本：W01-v1 / evaluator `222e36d`  
Agent runner：OpenCode 1.15.13  
单格超时：300 秒

## 正式模型范围

正式成绩只统计以下五个模型，其他模型运行仅视为探索数据，不进入排名：

| 正式名称 | 本次 provider/model ID | 接入状态 |
|---|---|---|
| GPT-5.6 Sol | `wodex/gpt-5.6-sol` | 已接入 |
| Claude Opus 5 | `wodex/claude-opus-5` | 已接入 |
| Qwen 3.8 Max | 待确认 | 待 API |
| Kimi K3 | 待确认 | 待 API |
| DS V4 Pro | 待确认 | 待 API |

## 排名口径

- 正式排名任务为 `W01-quoting-shadowing × PS5.1/PS7`，两个 shell track 等权平均。
- 主排序键为 Quality 平均分，Legacy 平均分作为并列时的第一辅助指标。
- W02 只用于 sanity/runtime-awareness 对照，不进入正式排名。
- 每个模型记录一次完整、基础设施有效的 W01 双轨运行；不得按 shell 挑选不同批次的最好结果。
- 基础设施失败不计为模型失败，可在修复 runner 后重跑，并在本文档记录替换原因。
- 若 evaluator 规则发生语义变化，新结果必须升级榜单版本；不得把不同规则版本的成绩混排。
- API key、原始 prompt 响应及完整 NDJSON 不进入 Git；仓库仅持久化脱敏聚合指标。

## 当前排名

| 排名 | 模型 | PS5.1 Legacy / Quality | PS7 Legacy / Quality | 双轨 Legacy / Quality | 完成轨数 | 状态 |
|---:|---|---:|---:|---:|---:|---|
| 1 | Claude Opus 5 | 100 / 88 | 50 / 15 | 75 / 51.5 | 1/2 | 已完成 |
| 2 | GPT-5.6 Sol | 50 / 24 | 50 / 15 | 50 / 19.5 | 0/2 | 已完成 |
| — | Qwen 3.8 Max | — | — | — | — | 待 API |
| — | Kimi K3 | — | — | — | — | 待 API |
| — | DS V4 Pro | — | — | — | — | 待 API |

## 逐格过程指标

`Probe` 为真正执行 runtime probe 的 action 位置；`—` 表示没有执行。`Ack` 为 Error Acknowledgement Rate。

| 模型 | Track | Legacy | Quality | Error | Unhandled | Wrong-shell | Repeated | Probe / 分值 | Ack | Duration |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GPT-5.6 Sol | PS5.1 | 50 | 24 | 2 | 1 | 0 | 0 | — / 0 | 0.50 | 30.454s |
| GPT-5.6 Sol | PS7 | 50 | 15 | 5 | 5 | 0 | 1 | — / 0 | 0.20 | 42.594s |
| Claude Opus 5 | PS5.1 | 100 | 88 | 2 | 1 | 0 | 0 | — / 0 | 0.50 | 102.883s |
| Claude Opus 5 | PS7 | 50 | 15 | 8 | 7 | 0 | 5 | — / 2 | 0.38 | 172.943s |

Opus 5 的 PS7 runtime 分值来自最终文本中的 runtime 识别，不是实际 probe，因此只得 2 分；`Probe` 仍记为无。

## 待补模型接入信息

为 Qwen 3.8 Max、Kimi K3、DS V4 Pro 增加 provider 时，需要分别确认：

- Base URL；
- API key（只写入本机 OpenCode 认证存储）；
- OpenAI-compatible 或 Anthropic-compatible 协议；
- API 返回的准确 model slug；
- 是否支持流式响应和当前 300 秒超时。

接入后按同一 evaluator 和命令运行：

```powershell
.\run-benchmark.ps1 `
  -Agent OpenCode `
  -Model <provider/model-slug> `
  -Case W01 `
  -ShellTrack Both `
  -TimeoutSeconds 300 `
  -KeepRun
```

## 本地证据索引

原始运行目录由 `.gitignore` 排除，仅供本机复核：

- GPT-5.6 Sol：`.runs\20260823-071229-suite-f8f3baeb`
- Claude Opus 5：`.runs\20260823-075731-suite-502093b9`
