# Shell 与跨 Windows/Linux 命令复盘

本文只记录本次 Windows Coding Benchmark 部署中真实发生过的错误和修正模式，供后续 runner、运维脚本和 agent 参考。不得在此类文档、日志或命令行中记录密码、token、OAuth 内容或私钥正文。

## 总原则

1. Linux shell、`sg -c`、SSH 远程 shell、`cmd.exe`、Windows PowerShell 是不同解析层。每增加一层引号，错误概率都会显著增加。
2. 复杂 PowerShell 不写进 SSH 单行命令。优先保存为 `.ps1`，通过 QGA 的 UTF-16LE `EncodedCommand` 执行，或通过 SSH stdin 传输。
3. libvirt 命令始终显式指定 `--connect qemu:///system`。
4. 长复合命令必须 `set -euo pipefail`，或拆成可独立验收的步骤。不能让前一步失败后继续执行定义域、安装或重命名。
5. 所有可变文件先写 `.part`/`.tmp`，验证大小、SHA-256 或语法后再原子重命名。

## Case 1：下载路径存在，但 curl 报 Permission denied

症状：

```text
curl: (23) Failure writing output to destination
```

根因：目录属于 `root:libvirt` 且模式为 `2770`。用户虽然是 libvirt 成员，但当前执行上下文没有继承该补充组。

正确模式：

```bash
sg libvirt -c 'curl ... --output /mnt/.../file.part URL'
```

下载后必须分别核对字节数和 SHA-256，再执行 `mv file.part file`。不要因 URL 返回 200 就认为下载成功。

## Case 2：virsh 错误报告“找不到域”

症状：已经运行的 VM 被查询为不存在。

根因：命令落到了默认 session URI，而域实际位于 system URI。

错误模式：

```bash
virsh domstate ws2025-base-build-v001
```

正确模式：

```bash
virsh --connect qemu:///system domstate ws2025-base-build-v001
```

脚本中不依赖 libvirt 默认 URI。

## Case 3：把新版 .NET API 写进 Windows PowerShell 5.1

症状：

```text
RandomNumberGenerator does not contain a method named GetBytes
```

根因：`RandomNumberGenerator.GetBytes(length)` 是较新的静态 API，Windows PowerShell 5.1 所用 .NET Framework 不支持。

兼容写法：

```powershell
$bytes = New-Object byte[] 48
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
```

基线初始化脚本默认按 Windows PowerShell 5.1 能力编写；安装 PowerShell 7 之后才能使用新版 API。

## Case 4：sshd 配置正确，但没有 host keys

症状：

```text
sshd: no hostkeys available -- exiting
```

根因：OpenSSH Server capability 已安装，但服务从未成功启动，因此 ProgramData 下没有 host keys。

正确顺序：

```powershell
& "$env:WINDIR\System32\OpenSSH\ssh-keygen.exe" -A
& "$env:WINDIR\System32\OpenSSH\sshd.exe" -t
```

只有 `sshd -t` 返回 0 后才能启动或重启服务。

## Case 5：修改 sshd_config 后仍使用旧配置

症状：文件和 ACL 均正确，但公钥持续被拒绝。

根因：对已经运行的服务调用 `Start-Service` 不会重载配置。

正确模式：

```powershell
$service = Get-Service sshd
if ($service.Status -eq 'Running') {
    Restart-Service sshd -Force
} else {
    Start-Service sshd
}
```

配置切换后必须再执行一次严格的 `BatchMode=yes` SSH 测试。

## Case 6：Windows 管理员账户的 authorized_keys 位置

症状：客户端确实提交了正确 ED25519 key，但 Windows OpenSSH 拒绝认证。

根因：管理员账户与普通账户的密钥文件处理不同，用户 profile 内 `.ssh/authorized_keys` 容易受管理员 Match/ACL 规则影响。

本项目采用：

```text
AuthorizedKeysFile __PROGRAMDATA__/ssh/wcb-administrator-authorized_keys
AllowUsers Administrator
PasswordAuthentication no
```

密钥文件仅允许 SYSTEM 和 Administrators。`AllowUsers` 必须保留，否则 ProgramData 管理员密钥可能被其他管理员账户复用。

## Case 7：PowerShell 单引号不会展开反引号转义

症状：transport canary 期望 CRLF，实际文件包含字面字符 `` `r`n ``。

错误模式：

```powershell
'text`r`n'
```

正确模式：

```powershell
[IO.File]::WriteAllBytes($path, [Text.Encoding]::UTF8.GetBytes("text`r`n"))
```

跨 transport 验证必须比较原始字节或 Base64，不能只用 `Get-Content` 的视觉输出判断。

## Case 8：SSH、cmd.exe、PowerShell 多层内嵌引号

症状：远端 PowerShell 出现 `ParserError`，尤其是 `$PSVersionTable`、带空格路径和嵌套双引号。

错误模式：把完整 PowerShell 程序塞进：

```text
bash -> sg -c -> ssh -> cmd.exe -> powershell -Command
```

正确优先级：

1. 本地 `.ps1` + QGA `-EncodedCommand`。
2. SSH stdin + `powershell.exe -File -`。
3. 仅在命令非常短时使用 `powershell -Command`。

程序路径有空格时，在 PowerShell 中使用调用运算符：

```powershell
& 'C:\Program Files\OpenCode\1.18.21\opencode.exe' --version
```

## Case 9：QGA 进程不是交互用户

症状：通过 QGA 执行 `opencode debug paths`，得到：

```text
C:\Windows\System32\config\systemprofile
```

根因：QEMU Guest Agent 以 SYSTEM 身份运行。其 HOME、AppData、用户 PATH 和 OpenCode auth 目录都不是 Administrator 的目录。

规则：

- 系统服务、注册表、文件哈希可通过 QGA 查询。
- 用户 auth、OpenCode config 合并结果、用户 PATH 必须从对应用户的 SSH/交互会话验证。
- 不根据 SYSTEM 的 `debug paths` 判断 Administrator 是否已登录。

## Case 10：CLIXML 出现在 stderr 不等于命令失败

症状：QGA 执行 PowerShell 时 stderr 出现 `#< CLIXML` 和模块初始化 progress record。

根因：Windows PowerShell 会将 progress/warning 序列化到错误数据通道，但进程退出码仍可能为 0。

规则：以退出码和预期结构化 stdout 为主；保存 stderr 供诊断，但不要看到 CLIXML 就直接判 FAIL。

## Case 11：QEMU 身份不是 libvirt 组

症状：域定义成功，但启动时报 qcow2 或 NVRAM `Permission denied`。

实际身份：

```text
libvirt-qemu:kvm
```

根因：冻结目录使用了 `root:libvirt 2770`，这适合 evaluator 管理，但 QEMU 的主组是 `kvm`，不能自动遍历或写入。

推荐稳定布局：

- base：`root:kvm 0440`，管理者通过 sudo 或明确 ACL 读取。
- overlay/NVRAM：运行所有者或 `libvirt-qemu:kvm`，文件 `0660`。
- run 目录：受控所有者，组 `kvm`，目录 `0770`。
- 在创建工件时一次设置正确 owner/group，不要在启动失败后反复叠加 ACL。

## Case 12：`sg` 会改变组上下文并可能失去路径访问

症状：`sg kvm -c 'chgrp ...'` 反而无法访问父目录。

根因：父目录依赖 `libvirt` 组，而 `sg kvm` 的执行上下文没有保留所需的 libvirt 路径权限。

规则：

- 执行前用 `namei -l` 检查完整父目录链。
- 不把 `sg libvirt`、`sg kvm` 当作可随意互换的 sudo。
- 需要同时调整 owner/group 且涉及 root-owned 父目录时，使用一份路径固定、fail-closed 的 sudo 脚本。

## Case 13：sudo 缓存通常不能跨终端复用

症状：用户刚在本地终端执行 sudo，自动化进程的 `sudo -n` 仍返回需要密码。

根因：sudo ticket 常按 TTY/session 隔离。非交互 agent 不能假设能复用用户终端缓存。

规则：

- 不向聊天索要或接收密码。
- 需要 root 时生成可审查脚本，让用户在自己的终端执行一条 `sudo script`。
- 不反复尝试 `sudo -n`。

## Case 14：复合 shell 命令可能掩盖中间失败

风险模式：

```bash
mkdir ...; qemu-img create ...; cp ...; virsh define ...
```

如果中间命令失败，后续命令仍可能执行，留下部分 domain 或不完整状态。

正确模式：脚本首行使用：

```bash
set -euo pipefail
```

并对每个目标先做“不存在”检查。域、overlay、NVRAM、日志必须使用同一个 run ID，任何已有目标都拒绝覆盖。

## Case 15：修改性操作不要混在一个高风险脚本里申请

症状：同时设置 Windows Update 策略并递归删除暂存目录，被安全审查整体拒绝。

规则：

- 将“配置策略”和“删除数据”拆开说明。
- 删除必须列出精确目标，例如仅 `C:\WCB\staging` 与 `C:\WCB\canary`。
- 得到明确批准后再执行；不要换另一种命令绕过拒绝。

## Case 16：基础镜像和交互登录不能混用

风险：在 base-build VM 中运行 `opencode auth login` 会把 OAuth 凭据写入磁盘，即使随后删除，数据仍可能在 qcow2 未分配/旧块中恢复。

正确顺序：

1. 确认 `auth_present=false`。
2. 正常关机并冻结只读 base。
3. 创建唯一 disposable overlay。
4. 只在 overlay 中执行交互登录。

## 后续命令审查清单

每次执行跨 guest 命令前检查：

- [ ] 是否显式使用 `qemu:///system`？
- [ ] 当前命令究竟由 miku、libvirt-qemu、SYSTEM 还是 Administrator 执行？
- [ ] 是否有超过两层 shell/引号解析？若有，改用脚本或 EncodedCommand。
- [ ] PowerShell 代码是否兼容 5.1，还是明确由 pwsh 7.6.4 执行？
- [ ] 路径是否含空格、括号、反引号、美元符号？
- [ ] 是否验证退出码、stdout 结构和实际字节，而非只看屏幕文本？
- [ ] 修改前是否确认目标不存在或精确匹配 run ID？
- [ ] QEMU 是否具有父目录遍历、base 只读、overlay/NVRAM 读写权限？
- [ ] sudo 是否需要用户在自己的终端执行？
- [ ] 日志是否可能包含 OAuth、token、密码、私钥或完整环境变量？
