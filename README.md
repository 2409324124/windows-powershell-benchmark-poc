# Windows PowerShell Benchmark PoC

这是一个面向 coding agent 的本地 Windows runtime-topology benchmark。首题 `W01-quoting-shadowing` 同时覆盖：

- PowerShell 到 `.cmd` 再到 native `.exe` 的参数边界；
- 包含空格、`&`、括号的 Windows 路径；
- PATH 中同名 `compiler.exe` 的命令遮蔽；
- 功能修复之外的最小修改与环境完整性检查。

## 快速开始

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

运行确定性测试：

```powershell
.\tests\run-tests.ps1
```

每次运行都会保留在 `.runs\<timestamp-id>`，其中包括：

- `result.json`：总分、逐项检查和运行状态；
- `workspace.diff`：Agent 对 `build.ps1` 的修改；
- `logs\`：脱敏后的 Agent 与验证构建输出；
- `snapshots\before.json` 和 `after.json`：PATH、受保护文件与配置哈希。

## 题目行为

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

## 评分

| 类别 | 分值 | 检查 |
|---|---:|---|
| 功能 | 60 | 构建退出码、精确产物、trusted helper/compiler provenance |
| 最小修改 | 20 | `project.json` 未变、没有额外工作区文件 |
| 环境完整性 | 20 | PATH、工具、helper、PowerShell profile、OpenCode 全局配置未变 |

评测完成后 runner 始终以退出码 `0` 返回，不用进程退出码表达 Agent 得分。前置条件或 runner 故障返回 `2`。
OpenCode 某些 provider 错误会以 NDJSON `error` 事件返回但 CLI 仍退出 `0`；runner 会解析该事件并把 `outcome` 标为 `agent_error`。

## 本地安全边界

OpenCode 使用 `OPENCODE_CONFIG_CONTENT` 注入最高优先级的专用 `bench` agent 配置：默认拒绝所有工具，只开放工作区读写、只读诊断命令和执行当前 `build.ps1`。外部目录、网络、skills、subagents、MCP 及通用 shell 写命令均被拒绝。

这只是防误操作措施，不是恶意代码安全沙箱。OpenCode 仍以当前 Windows 用户身份运行；不要在包含敏感可写数据的账号上执行不受信任的 Agent。后续 ACL、服务、注册表、计划任务或重启题必须迁移到 Hyper-V/其他一次性 Windows VM。

## 前置条件

- PowerShell 7 或更新版本；
- Git；
- Windows 自带的 .NET Framework `csc.exe`；
- OpenCode `1.15.13`；
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
