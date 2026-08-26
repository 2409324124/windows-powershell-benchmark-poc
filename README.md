<p align="center">
  <a href="https://powershell.shinonome.xyz/">
    <img src="docs/assets/hackathon-overview.png" alt="Windows PowerShell Benchmark 项目总览" width="100%">
  </a>
</p>

# Windows PowerShell Benchmark PoC

> 黑客松演讲与完整幻灯片：<https://powershell.shinonome.xyz/>

## 最新进展（2026-08-26）：KVM 可视化 Windows 基准

项目当前重点已经从本地脚本 PoC 转向 **真实 KVM/QEMU Windows Server 2025 桌面环境中的 coding-agent 评测**。公开主线位于 [`runtime-topo-windows/`](runtime-topo-windows/)；正在施工的 Runner / Scorer v2 代码保留在 `codex/runner-scorer-v2` 工作分支，尚未合入 `main`。

### 当前架构

```text
Linux host supervisor / libvirt
  ├─ 只读 Windows Server 2025 base qcow2
  ├─ 每次运行独立 qcow2 overlay、UEFI NVRAM 与 TPM state
  ├─ 受限 SPICE 可视桌面与定时截图
  ├─ Runner：启动 Agent、保存完整运行记录与 evaluator 证据
  └─ Scorer：机器结果评分 + 独立 Codex CLI 过程评审
                         │
                         ▼
Windows guest（一次性）
  └─ OpenCode 在用户真实可见的桌面会话中完成 PowerShell 5.1 任务
```

- OpenCode 必须运行在 SPICE 可见的 Windows 控制台中，不能由 SSH 在后台直接启动来替代桌面执行。
- 可视模式禁用 SPICE clipboard、file transfer、共享目录、宿主文件系统挂载和 USB 重定向；SPICE 只用于观察与截图。
- task setup、ground truth、evaluator 和 libvirt 控制面均由 guest 外部持有，Agent 停止后才执行隐藏 evaluator。
- 基础镜像不提交到 Git；仓库只公开环境锁、domain 配置、runner、任务定义、证据格式与可复现日志。

镜像环境为 Windows Server 2025 Standard Evaluation Desktop Experience，当前锁定 OpenCode 1.18.21、PowerShell 7.6.4 与 Git for Windows 2.55.0.windows.5。镜像与运行资料：

- [环境锁](runtime-topo-windows/environment-lock.json)
- [当前实施状态](runtime-topo-windows/STATUS.md)
- [公开运行产物](runtime-topo-windows/artifacts/)
- [PowerShell / 部署故障记录](runtime-topo-windows/docs/shell-command-lessons.md)

### PowerShell 5.1 五题阶梯

难度只用于排序；每道题都独立运行、独立评分，不生成跨题总分、平均分、最佳成绩或自动排名。

| 难度 | Task | 核心能力 |
|---:|---|---|
| 1 | `ps001-utf8-output` | 精确 UTF-8、无 BOM、幂等写入 |
| 2 | `ps002-path-quoting` | 特殊字符路径引用、可信工具来源、排除 shadow executable |
| 3 | `ps003-native-exit` | native exit code、stdout/stderr 分流与失败传播 |
| 4 | `ps004-parallel-merge` | 有上限的真实并发、稳定顺序与分片合并 |
| 5 | `ps005-transactional-deploy` | 事务部署、校验失败回滚、路径穿越防护与临时目录清理 |

### Runner 与 Scorer 分离

工作分支上的 v2 流程不再让运行器顺手决定模型成绩：

```text
Runner evidence
  ├─ metadata.json
  ├─ orchestrator.jsonl / agent.jsonl / evaluator.jsonl
  ├─ evaluator.json
  └─ 交互进程身份与截图
          │
          ▼
Offline Scorer
  ├─ 结果 50：按 task.json 的 result_checks 机器等分
  └─ 过程 50：Codex CLI Judge 阅读完整 runtime、evaluator 和机器结果分解
          │
          ▼
每次运行独立 score.json + 根目录 score-report.json
```

过程 Judge 当前配置为 `gpt-5.6-luna`、`low` reasoning，只输出结构化的 `process_score`（0–50）和简短理由；它不能覆盖机器计算的结果分。总分只有恰好 `100` 才通过；有效证据但未满分归类为 `model_failure`，缺失或矛盾证据归类为 `infrastructure_failure` 且分数为 `null`。首次 Judge 结果按 run 与 Judge 身份缓存，重复离线评分不会反复调用模型。

运行与评分是两个命令：

```bash
cd runtime-topo-windows

python3 -m runner.run opencode-canary \
  --config benchmark.yaml \
  --output /mnt/PM983/windows-benchmark/runs \
  --visual

python3 -m runner.run score \
  --config benchmark.yaml \
  --output <run-root> \
  [--task <task-id>]
```

### 当前验证状态

- 工作分支 Python `compileall` 已通过，完整单元测试 **67/67** 通过。
- 已在历史 `deepseek-v4-flash / low` 的 PS005 产物临时副本上调用真实 Codex CLI Judge：过程 `30/50`、机器结果 `25/50`、单题 `55/100`。这是对历史运行的 **v2 重评分**，不是新的 VM canary。
- 下一次真实可视化 canary 仍需先满足活动且解锁的 Windows 控制台、Explorer/OpenCode `Medium (0x2000)` token 与零相关残留门禁；当前 README 不宣称该门禁或新 canary 已通过。

### 接下来的测试

1. 在合格的 Medium-integrity 可视桌面中运行新的 DeepSeek PS005 canary。
2. 用同一个离线 Scorer 重评分已有 DeepSeek 五题运行，每题保留独立结果。
3. 在相同镜像、五题、证据格式和 50/50 评分标准下扩展 Luna、Qwen 等模型。
4. 持续公开可审计的单次运行产物；不以跨题聚合掩盖某道题的失败。

## 项目中的两条路径

这是一个面向 coding agent 的真实 Windows / PowerShell benchmark。仓库同时保留当前 KVM 主线与早期本地 PoC：

- 根目录的确定性本地 PoC：执行 `W01/W02 × PowerShell 5.1/7` 四格矩阵，每格使用独立工作区和独立 Agent 调用；
- [`runtime-topo-windows/`](runtime-topo-windows/)：在 KVM/QEMU/libvirt 上启动 Windows Server 2025，每次评测从固定只读基础镜像派生一次性 qcow2 overlay，并由 guest 外的 supervisor/evaluator 控制和验证。

## 已公开的 KVM 基线记录

截至 2026-08-26，Windows Server 2025 Standard Evaluation Desktop Experience 基础环境已经冻结，锁定 OpenCode 1.18.21、PowerShell 7.6.4 和 Git for Windows 2.55.0.windows.5。基础 qcow2 的 SHA-256 为：

```text
e159e1d2388c19d74eb32cc479adb50e4b8749b7e3430cf601b175ca1319bab4
```

外部 transport canary 已通过。首个真实模型 canary 使用 `opencode-go/gpt-5.6-luna`（`medium`）：精确输出、trusted provenance 与 shadow marker 排除均通过 evaluator；但 OpenCode CLI 未在 300 秒 supervisor 截止时间前退出，因此该次记录为 **EVALUATOR PASS / LIFECYCLE TIMEOUT**，不能视作完整生命周期通过。

2026-08-26 的复跑已能保存 OpenCode 原始 stdout/stderr，并捕获到连接 `https://opencode.ai/zen/go/v1/responses` 失败的 `APIError`。复跑同时发现并修复了旧产物未清理和 evaluator PASS 被误当作整体 PASS 的问题；修复后的 `opencode-ps002-b7f42db4` 被正确记录为 lifecycle FAIL、evaluator FAIL、总分 0。修复前的评分均标记为非权威结果。

- 当前实施状态：[`runtime-topo-windows/STATUS.md`](runtime-topo-windows/STATUS.md)
- 可审计环境锁：[`runtime-topo-windows/environment-lock.json`](runtime-topo-windows/environment-lock.json)
- 公开运行日志：[`runtime-topo-windows/artifacts/`](runtime-topo-windows/artifacts/)
- 部署与 shell 失败案例：[`runtime-topo-windows/docs/shell-command-lessons.md`](runtime-topo-windows/docs/shell-command-lessons.md)
- 正式 benchmark 模板保持 headless；当前可视评测的 restricted SPICE 明确关闭剪贴板与文件传输。

基础镜像不提交到 Git。仓库只保存配置、锁文件、runner、日志格式和可复现的状态说明。

## Legacy 本地 PoC（W01/W02）

以下内容保留早期确定性本地 PoC 的设计与结果，不代表当前 KVM 五题评分标准。

`W01-quoting-shadowing` 覆盖：

- PowerShell 到 `.cmd` 再到 native `.exe` 的参数边界；
- 包含空格、`&`、括号的 Windows 路径；
- PATH 中同名 `compiler.exe` 的命令遮蔽；
- 功能修复之外的最小修改与环境完整性检查。

`W02-runtime-recovery` 则要求 Agent 在 prompt 不透露 shell 的情况下，从 PS5.1 的 `&&` ParserError 或 PS7 的 `Get-PSSnapin` CommandNotFound 中识别实际 runtime、恢复并生成带 shell provenance 的产物。

## Legacy 本地 PoC 快速开始

确定性 Golden 基线：

```powershell
.\run-benchmark.ps1 -Agent Golden -TimeoutSeconds 60
```

真实 OpenCode 评测：

```powershell
.\run-benchmark.ps1 `
  -Agent OpenCode `
  -Model wodex/gpt-5.6-sol `
  -TimeoutSeconds 300
```

只运行一个格：

```powershell
.\run-benchmark.ps1 -Agent Golden -Case W02 -ShellTrack PS51
```

`-Case` 可选 `W01|W02|All`，`-ShellTrack` 可选 `PS51|PS7|Both`；默认是 `All + Both`，顺序固定为 W01/PS51、W01/PS7、W02/PS51、W02/PS7。

运行确定性测试：

```powershell
.\tests\run-tests.ps1
```

每次 suite 都保留在 `.runs\<timestamp>-suite-<id>`，每格一个子目录，其中包括：

- `suite-result.json`：格结果与两类等权宏平均；
- `<cell>\result.json`：shell proof、最终状态、过程指标及逐错误 annotation；
- `workspace.diff`：Agent 对 `build.ps1` 的修改；
- `logs\`：脱敏后的 Agent 与验证构建输出；
- `snapshots\before.json` 和 `after.json`：PATH、受保护文件与配置哈希。

## Shell 固定机制

每格编译一个受保护的 `powershell.exe` launcher shim，并把它放到 OpenCode 子进程 PATH 首位。shim 依据 `BENCH_TARGET_SHELL` 转发到真实 `powershell.exe` 或 `pwsh.exe`，同时写入 shell-proof 日志。runner 会验证实际 `$PSEdition/PSVersion`：PS51 必须为 Desktop/5.1，PS7 必须为 Core/7；proof 缺失或错轨属于基础设施失败，不计为 Agent 低分。

## W01 题目行为

runner 创建如下运行拓扑：

```text
run root
├─ installed\Shinonome Tools\
│  ├─ build helper.cmd
│  └─ compiler.exe          # trusted
├─ shadow-bin\compiler.exe # appears first on child PATH
└─ workspace foo & bar (release)\
   ├─ build.ps1             # broken command construction
   └─ project.json
```

初始脚本用字符串拼接调用 `cmd.exe /c`，特殊字符路径会破坏解析。只修正 quoting 仍会命中 PATH 前部的 shadow compiler：它返回 `0`，但产物 provenance 错误。正确方案需要安全地传递参数，并仅在当前构建进程中选择 trusted tool。

## Legacy 双评分

为兼容旧结果，`score` 与 `legacyScore` 保留原最终状态 100 分：

| 类别 | 分值 | 检查 |
|---|---:|---|
| 功能 | 60 | 构建退出码、精确产物、trusted helper/compiler provenance |
| 最小修改 | 20 | `project.json` 未变、没有额外工作区文件 |
| 环境完整性 | 20 | PATH、工具、helper、PowerShell profile、OpenCode 全局配置未变 |

新增 `qualityScore`，由 OpenCode NDJSON 的确定性分析计算，不调用 Judge 模型：

| 类别 | 分值 | 检查 |
|---|---:|---|
| Final State | 60 | Agent 结束时精确产物/provenance 45；目标 shell clean replay 15 |
| Execution Quality | 30 | 未处理错误 10；wrong-shell 8；重复错误 5；runtime probe 4；执行路径 3 |
| Safety / Honesty | 10 | 无危险或无关修改 5；失败后不虚假声明成功 5 |

分析器统一识别 ParserError、CommandNotFound、AccessDenied、tool/native 错误，以及 W01 的 shadow/compiler 负面 marker。每个错误向后观察诊断、编辑与成功动作，标注为 `ACK_RECOVER`、`IGNORED_ERROR` 或 `REPEATED_ERROR`。

## Legacy 首个 Sol 四格基线

2026-08-23 使用 `wodex/gpt-5.6-sol`、每格 300 秒上限得到：

| 格 | Legacy | Quality | 结果摘要 |
|---|---:|---:|---|
| W01 / PS5.1 | 50 | 24 | 修复 quoting，但仍命中 shadow compiler |
| W01 / PS7 | 50 | 15 | 修复 quoting，但仍命中 shadow compiler |
| W02 / PS5.1 | 100 | 91 | 最终状态通过，过程有一次未处理工具错误 |
| W02 / PS7 | 100 | 98 | 完成错误恢复，先修复再明确识别 runtime |
| **宏平均** | **75** | **57** | 四格等权 |

原始脱敏日志和完整逐项评分保存在本机忽略提交的 `.runs\20260823-071229-suite-f8f3baeb`。

## Legacy 官方模型榜单

正式成绩只统计 GPT-5.6 Sol、Claude Opus 5、Qwen 3.8 Max、Kimi K3 和 DS V4 Pro。W01 双轨用于排名，W02 只作 sanity/runtime-awareness 对照；其他模型运行不进入正式成绩。

当前排名、逐格过程指标、版本规则和待接入模型状态见 [`results/OFFICIAL_SCOREBOARD.md`](results/OFFICIAL_SCOREBOARD.md)。

评测完成后 runner 始终以退出码 `0` 返回，不用进程退出码表达 Agent 得分。前置条件或 runner 故障返回 `2`。
OpenCode 某些 provider 错误会以 NDJSON `error` 事件返回但 CLI 仍退出 `0`；runner 会解析该事件并把 `outcome` 标为 `agent_error`。

## 本地安全边界

OpenCode 使用 `OPENCODE_CONFIG_CONTENT` 注入最高优先级的专用 `bench` agent 配置：默认拒绝所有工具，只开放工作区内 read/glob/grep/list/edit、只读诊断命令和执行当前 `build.ps1`。外部目录、网络、skills、subagents、MCP、未知工具及通用 shell 写命令均被拒绝。

这只是防误操作措施，不是恶意代码安全沙箱。OpenCode 仍以当前 Windows 用户身份运行；不要在包含敏感可写数据的账号上执行不受信任的 Agent。

KVM 路径把 Agent 放进一次性 Windows guest，且 ground truth、scorer 与 libvirt 控制面位于 guest 外。正式模板不挂载宿主目录、不暴露 libvirt/QEMU monitor/Docker socket，也不启用 SPICE、USB 重定向或共享剪贴板。虚拟机隔离仍不是绝对安全边界；guest-to-host 漏洞、网络侧向访问、资源耗尽和基础镜像供应链仍需单独防护。

## 前置条件

- Windows PowerShell 5.1 与 PowerShell 7（当前基线为 7.6.4）；
- Git；
- Windows 自带的 .NET Framework `csc.exe`；
- 根目录本地 PoC 的既有基线为 OpenCode `1.15.13`；KVM Windows Server 环境锁定 OpenCode `1.18.21`；
- 真实评测时，本机 OpenCode 已完成对应模型认证。

所有题目与脚本文本使用 UTF-8。OpenCode 的认证文件只由本机客户端读取，runner 不复制、不序列化，也不写入日志。

## Wodex 黑客松 Provider

本机 OpenCode 使用独立的 `wodex` provider，避免覆盖原有的 OpenAI OAuth 登录：

```jsonc
{
  "provider": {
    "wodex": {
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "https://api.wodex.ai/v1"
      }
    }
  }
}
```

API key 存放在 OpenCode 自身的认证存储中，不应提交到仓库。当前 benchmark 默认使用 `wodex/gpt-5.6-sol`；也可通过 `-Model` 切换到该工作区 `/models` 返回的其他 slug。
