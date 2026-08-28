<p align="center">
  <a href="https://powershell.shinonome.xyz/">
    <img src="docs/assets/hackathon-overview.png" alt="Windows PowerShell Benchmark" width="100%">
  </a>
</p>

# Windows PowerShell Coding-Agent Benchmark

在真实、可观察的 KVM/QEMU Windows Server 2025 桌面中，评测 coding agent 修复 Windows PowerShell 5.1 与 PowerShell 7 工程任务的能力。

项目不把一次成功的命令或模型自己的完成声明当作成绩。Agent 停止后，Runner 会冻结工作区和结构化运行记录，再由独立的 Windows Judge 审核执行过程、机器 evaluator 检查最终行为，最后生成每次运行独立的 `0–100` 能力分。

> 项目演讲与完整幻灯片：<https://powershell.shinonome.xyz/>

## 当前实测：PowerShell 7 高难度五模型 × 五题矩阵

2026-08-28 在 `codex/runner-scorer-v2` 工作分支完成了 PS006–PS010 的 25 次全新、串行、可视化运行。25/25 单元均得到有效数值分，基础设施失败为 0；本轮成绩覆盖 `18.33–100.00`，题目能够明显区分模型在不同工程能力上的表现。

| Task | DeepSeek V4 Flash | Qwen 3.7 Plus | HY3 | MiMo 2.5 | LongCat 2.0 |
|---|---:|---:|---:|---:|---:|
| PS006 Dual-engine Pipeline | 99.00 | 98.00 | 100.00 | 99.00 | 18.67 |
| PS007 Parallel Runspace Fan-out | 92.86 | 78.71 | 58.71 | 34.43 | 30.43 |
| PS008 SSH Remoting Sync | 84.67 | 82.67 | 96.00 | 55.33 | 18.33 |
| PS009 Native Byte Pipeline | 96.00 | 84.67 | 63.67 | 81.33 | 48.33 |
| PS010 Cross-platform Manifest | 53.43 | 61.71 | 99.00 | 62.71 | 32.43 |

每格都是一次独立运行的 `0–100` 能力分，不计算跨题总分、平均分、排名或“最佳模型”。低分表示模型在执行过程或机器功能检查中暴露了更多问题，不代表评测链路失败；只有证据、环境或评分链路损坏时才记录 `infrastructure_failure` 和 `score: null`。

其中 6 个单元达到 600 秒 Agent 时限后仍留下了可冻结、可评测的有效结果：PS006 LongCat，PS007 MiMo/LongCat，PS008 LongCat，PS009 LongCat，PS010 LongCat。它们的分数被保留为模型在固定资源边界下的真实表现，不做自动重跑或择优。

### 题目与能力类型

| Level | Task | 题目类型 | 运行时 | 主要考点 |
|---:|---|---|---|---|
| 6 | `ps006-dual-engine-pipeline` | 双引擎兼容与确定性序列化 | Windows PowerShell 5.1 + PowerShell 7.6.4 | 对象管道、JSONL 异常处理、ordinal 排序、UTF-8 无 BOM、跨引擎逐字节一致与幂等 |
| 7 | `ps007-parallel-runspace-fanout` | 并行编排与故障传播 | Windows PowerShell 7.6.4 | `ForEach-Object -Parallel`、ThrottleLimit 4、`$using:`、真实并发、native 退出码 23、失败时停止发布 |
| 8 | `ps008-ssh-remoting-sync` | SSH Remoting 与远端同步 | Windows PowerShell 7.6.4 → 隔离 Linux PowerShell 7.6.4 容器 | `PSSession`、远端命令与文件往返、固定 host key、退出码 37、会话和远端残留清理 |
| 9 | `ps009-native-byte-pipeline` | 原生二进制管道与原子发布 | Windows PowerShell 7.6.4 | 无效 UTF-8、NUL、CRLF 和随机字节透传，stderr 分离，损坏输入退出 29，不发布残缺产物 |
| 10 | `ps010-cross-platform-manifest` | 跨平台可复现构建 | Windows + 隔离 Linux 容器 PowerShell 7.6.4 | 同一冻结脚本、跨平台路径规范化、Unicode、native helper、确定性排序与逐字节相同 manifest |

Linux 容器只充当 PS008/PS010 的隔离远端 PowerShell 端点，不运行被测 OpenCode 或 Judge，也不是第二台虚拟机。

### 被测模型

| 显示名 | OpenCode model | 推理档位 |
|---|---|---|
| DeepSeek V4 Flash | `opencode-go/deepseek-v4-flash` | `low` |
| Qwen 3.7 Plus | `opencode-go/qwen3.7-plus` | provider default |
| HY3 | `opencode-go/hy3` | `none` |
| MiMo 2.5 | `opencode-go/mimo-v2.5` | provider default |
| LongCat 2.0 | `opencode-go/longcat-2.0` | `low` |

两轮矩阵的过程 Judge 均固定为 `opencode-go/gpt-5.6-luna / low`。

## v0.1.0 基线：PowerShell 5.1 五模型 × 五题矩阵

2026-08-27 完成了 PS001–PS005 的 25 次全新、串行、可视化运行。25/25 单元获得有效分数，基础设施失败为 0。

| Task | DeepSeek V4 Flash | Qwen 3.7 Plus | HY3 | MiMo 2.5 | LongCat 2.0 |
|---|---:|---:|---:|---:|---:|
| PS001 UTF-8 Output | 97 | 97 | 90 | 99 | 97 |
| PS002 Path Quoting | 97 | 91 | 99 | 95 | 97 |
| PS003 Native Exit | 48 | 99 | 49 | 94 | 87 |
| PS004 Parallel Merge | 94 | 98 | 96 | 99 | 52 |
| PS005 Transactional Deploy | 95 | 85 | 93 | 97 | 40 |

这些分数用于展示不同模型在不同能力维度上的差异，不设置统一“及格线”：

- 每格独立评分，不计算跨题总分、平均分、排名或“最佳模型”。
- 100 只是量表上限，不是运行有效性的门槛。
- 分数较低表示该模型在过程或功能检查中暴露了更多问题，不等于 benchmark 运行失败。
- 证据完整且评分链路一致时状态为 `valid`；只有环境、证据或评测链路损坏才是 `infrastructure_failure`，此时分数为 `null`。
- 过程 Judge 固定为 `opencode-go/gpt-5.6-luna / low`。

发布前另有一次独立的 LongCat 2.0 / PS005 runtime 回归得到 95 分；它不属于上述 5×5 矩阵，也不会覆盖或替换矩阵中的 40 分。重复尝试始终作为不同运行保留。

## 五级 PowerShell 5.1 任务

| Level | Task | 核心能力 |
|---:|---|---|
| 1 | `ps001-utf8-output` | 精确 UTF-8、无 BOM、目录创建与幂等写入 |
| 2 | `ps002-path-quoting` | 特殊字符路径、native 参数边界、可信工具选择与 PATH shadowing |
| 3 | `ps003-native-exit` | native exit code、stdout/stderr 分流与失败传播 |
| 4 | `ps004-parallel-merge` | PowerShell 5.1 有界并发、乱序完成与确定性合并 |
| 5 | `ps005-transactional-deploy` | 路径穿越防护、候选校验、事务替换、回滚与清理 |

详细题目说明见 [`runtime-topo-windows/tasks/README.md`](runtime-topo-windows/tasks/README.md)。每道题均由 Windows PowerShell 5.1 执行隐藏 evaluator，而不是用 PowerShell 7 替代。

## 整体架构

```text
┌──────────────────────────── Linux / KVM Host ──────────────────────────────┐
│                                                                            │
│  Matrix Controller                                                         │
│  ├─ 读取 benchmark.yaml + 选定的 matrix YAML                               │
│  ├─ 串行调度 smoke → Agent → Judge → Score → cleanup                       │
│  └─ 保存 matrix-state.json，支持从安全阶段 --resume                        │
│                                                                            │
│  Host Supervisor                         Evidence / Scoring                │
│  ├─ libvirt + QEMU/KVM                   ├─ 冻结 workspace ZIP             │
│  ├─ qcow2 base + approved overlay        ├─ JSONL、进程身份、截图          │
│  ├─ VM 状态和残留门禁                    ├─ 每次独立 score.json            │
│  ├─ SSH control plane ───────────────┐   └─ matrix/score report            │
│  └─ isolated Linux PS7 sidecar       │                                     │
│                                      │                                     │
│  Human Observer ── restricted SPICE ─┼───────────────┐                     │
│  （只观察；clipboard/file transfer 均禁用）           │                    │
└──────────────────────────────────────┼───────────────┼─────────────────────┘
                                       │               │
                         setup / capture / evaluator   │ visible desktop
                                       │               │
┌──────────────────────────── Windows Server 2025 Guest ─────────────────────┐
│                                      │               │                     │
│  Administrator SSH control session ◄─┘               │                     │
│  ├─ 创建全新题目工作区                                │                    │
│  ├─ Agent 停止后冻结工作区                            │                    │
│  ├─ 按题目 runtime_matrix 隐藏执行 evaluator          │                    │
│  └─ 收集证据并清理                                    │                    │
│                                                      ▼                     │
│  Active Console · Medium integrity                                         │
│  Explorer → Limited interactive task → launcher → OpenCode Agent           │
│                                                   ├─ 修改目标脚本          │
│                                                   └─ 执行验证命令          │
│                                                                            │
│  Agent 结束并冻结证据后：                                                  │
│  Hidden OpenCode Luna Judge → 读取运行记录 → PowerShell 重放 → 过程 0–50   │
│  Hidden machine evaluator  → 按指定 PS5.1/PS7/Linux 运行时检查 → 结果 0–50 │
└──────────────────────────────────────┬─────────────────────────────────────┘
                                       │ structured results
                                       ▼
                     Host Scorer：独立能力分 0–100
                     status = valid / infrastructure_failure
```

Runner、Judge 和 Scorer 相互分离：

- **虚拟机在哪里：** Windows Server 2025 guest 运行在 Linux 主机的 QEMU/KVM/libvirt 中；Linux host 持有矩阵控制器、题目 ground truth、运行目录和最终 Scorer。
- **被测 OpenCode 在哪里：** Agent 只能通过 `Limited` interactive task 启动在 Windows 活动控制台的 Medium-integrity 桌面中，SPICE Viewer 可以看到真实窗口；SSH 只负责 setup、取证、evaluator 和清理，不能替代 Agent 桌面执行。
- **Judge 怎么测：** Agent 完全停止后，Runner 先冻结工作区、JSONL、进程身份和截图；随后在同一 Windows Medium 桌面隐藏启动另一套 OpenCode，固定使用 `opencode-go/gpt-5.6-luna / low` 阅读冻结证据并执行 PowerShell 重放，给出过程 `0–50` 分。
- **结果怎么测：** 与 Judge 分开的机器 evaluator 按题目的 `runtime_matrix` 调用锁定的 Windows PowerShell 5.1、Windows PowerShell 7.6.4 或隔离 Linux PowerShell 7.6.4 检查最终行为，给出结果 `0–50` 分；Linux Scorer 只读合成两部分，不允许 Judge 覆盖机器检查。
- **重复评分会发生什么：** 已冻结运行可以重复生成分数，不重新启动被测 Agent，也不自动挑选最佳结果。

受限 SPICE 只用于观察和截图，clipboard、file transfer、共享目录及 USB 重定向保持禁用。OpenCode 必须运行在真实可见的控制台会话中，不能用 SSH 后台进程冒充桌面评测。

## 运行矩阵

运行环境需要 Linux/KVM/libvirt、准备好的 Windows Server 2025 guest，以及已经完成对应 provider 认证的 OpenCode。基础 qcow2 镜像不包含在仓库中；版本与环境要求见 [`environment-lock.json`](runtime-topo-windows/environment-lock.json) 和 [`runtime README`](runtime-topo-windows/README.md)。

先展开矩阵，确认精确的 25 个单元和模型参数，不启动 VM 任务：

```bash
cd runtime-topo-windows
python3 -m runner.run matrix \
  --config benchmark.yaml \
  --matrix config/ps7-high-tier-5x5.yaml \
  --output /path/to/runs/ps7-high-tier-5x5 \
  --dry-run
```

启动真实可视化矩阵：

```bash
python3 -m runner.run matrix \
  --config benchmark.yaml \
  --matrix config/ps7-high-tier-5x5.yaml \
  --output /path/to/runs/ps7-high-tier-5x5 \
  --visual
```

从安全断点恢复：

```bash
python3 -m runner.run matrix \
  --config benchmark.yaml \
  --matrix config/ps7-high-tier-5x5.yaml \
  --output /path/to/runs/ps7-high-tier-5x5 \
  --visual \
  --resume
```

只对已经冻结的一次运行重新生成评分：

```bash
python3 -m runner.run score \
  --output /path/to/runs/ps7-high-tier-5x5 \
  --run-id RUN_ID_FROM_MATRIX_STATE
```

矩阵控制器会为每个正式单元依次完成环境门禁、Agent、Judge、Scorer 和清理。有效的低分会继续下一单元；只有基础设施失败才停止矩阵。

## 输出

```text
run root
├─ matrix-state.json                 # 可恢复断点与单元阶段
├─ matrix-report.json                # 独立矩阵记录
├─ score-report.json                 # 所有独立评分
└─ opencode-<task>-<model>/
   ├─ metadata.json
   ├─ orchestrator.jsonl
   ├─ agent.jsonl
   ├─ evaluator.jsonl
   ├─ evaluator.json
   ├─ evaluator-input.json
   ├─ workspace-after-agent.zip
   ├─ process-judge.json
   ├─ score.json
   └─ screenshots/
```

报告保留每次运行的模型、题目、档位、过程分、机器分、能力分、耗时与 token/cost，不生成跨题汇总或排名。

## 仓库结构

- [`runtime-topo-windows/`](runtime-topo-windows/)：KVM Windows runtime、Runner、Judge、Scorer 和矩阵控制器。
- [`runtime-topo-windows/tasks/`](runtime-topo-windows/tasks/)：PS001–PS010 题目、初始化和隐藏 evaluator。
- [`runtime-topo-windows/config/ps7-high-tier-5x5.yaml`](runtime-topo-windows/config/ps7-high-tier-5x5.yaml)：PS006–PS010 高难度五模型矩阵定义。
- [`runtime-topo-windows/config/low-tier-5x5.yaml`](runtime-topo-windows/config/low-tier-5x5.yaml)：v0.1.0 五模型矩阵定义。
- [`runtime-topo-windows/artifacts/`](runtime-topo-windows/artifacts/)：已公开的早期脱敏运行材料。
- [`results/`](results/) 与根目录 PowerShell runner：早期 W01/W02 本地 PoC。

## Legacy 本地 PoC

仓库根目录仍保留早期 `W01/W02 × PowerShell 5.1/7` 确定性 PoC、Golden Agent 和历史双评分结果，用于回归与项目演进记录。它们不代表当前 KVM 五题矩阵的评分语义。旧榜单见 [`results/OFFICIAL_SCOREBOARD.md`](results/OFFICIAL_SCOREBOARD.md)。

## 安全与发布边界

- 基础镜像、overlay、OpenCode 认证、API key 和完整本机运行目录不提交到 Git。
- Process Judge 会读取完整冻结 benchmark 工作区；只应使用专门构造且不含真实秘密的题目夹具。
- VM 隔离降低误操作风险，但不应被视为抵御恶意 guest 或未知虚拟化漏洞的绝对安全边界。

## License

[Apache License 2.0](LICENSE)
