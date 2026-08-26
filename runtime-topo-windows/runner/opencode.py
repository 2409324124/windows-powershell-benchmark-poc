from __future__ import annotations

import base64
import json
import shlex
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Sequence


@dataclass(frozen=True)
class SshTarget:
    address: str
    user: str
    identity: Path
    known_hosts: Path

    def base(self) -> list[str]:
        return [
            "sg", "libvirt", "-c",
            " ".join([
                "ssh", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
                "-o", "StrictHostKeyChecking=yes", "-o",
                f"UserKnownHostsFile={self.known_hosts}", "-i", str(self.identity),
                f"{self.user}@{self.address}",
            ]),
        ]

    def run(
        self,
        command: str,
        *,
        timeout: int,
        stdin: bytes | BinaryIO | None = None,
        on_timeout: Callable[[subprocess.TimeoutExpired], None] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        invocation = self.base()
        invocation[-1] += " " + subprocess.list2cmdline([command])
        if on_timeout is None:
            if stdin is None:
                return subprocess.run(invocation, input=b"", capture_output=True, timeout=timeout, check=False)
            if isinstance(stdin, bytes):
                return subprocess.run(invocation, input=stdin, capture_output=True, timeout=timeout, check=False)
            return subprocess.run(invocation, stdin=stdin, capture_output=True, timeout=timeout, check=False)

        process_stdin = stdin if stdin is not None and not isinstance(stdin, bytes) else subprocess.PIPE
        process_input = stdin if isinstance(stdin, bytes) else (b"" if stdin is None else None)
        with subprocess.Popen(
            invocation, stdin=process_stdin,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ) as process:
            try:
                stdout, stderr = process.communicate(
                    input=process_input,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as error:
                try:
                    on_timeout(error)
                finally:
                    process.kill()
                    stdout, stderr = process.communicate()
                raise subprocess.TimeoutExpired(
                    error.cmd, error.timeout, output=stdout, stderr=stderr,
                ) from None
        return subprocess.CompletedProcess(invocation, process.returncode, stdout, stderr)

    def upload_bytes(
        self, contents: bytes, remote_name: str, *, timeout: int,
    ) -> subprocess.CompletedProcess[bytes]:
        with tempfile.NamedTemporaryFile(prefix="wcb-control-", suffix=".ps1") as source:
            source.write(contents)
            source.flush()
            invocation = [
                "sg", "libvirt", "-c",
                shlex.join([
                    "scp", "-q", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
                    "-o", "StrictHostKeyChecking=yes", "-o",
                    f"UserKnownHostsFile={self.known_hosts}", "-i", str(self.identity),
                    source.name, f"{self.user}@{self.address}:{remote_name}",
                ]),
            ]
            return subprocess.run(
                invocation, input=b"", capture_output=True, timeout=timeout, check=False,
            )


class InteractiveAgentError(RuntimeError):
    pass


@dataclass(frozen=True)
class ConsoleSession:
    username: str
    session_id: int
    explorer_pid: int


@dataclass(frozen=True)
class LauncherIdentity:
    run_id: str
    task_name: str
    wrapper_pid: int
    session_id: int
    username: str
    executable: str
    command_line: str
    launcher_path: str
    request_path: str


@dataclass(frozen=True)
class InteractiveProcess:
    run_id: str
    task_name: str
    wrapper_pid: int
    pid: int
    session_id: int
    parent_pid: int
    executable: str
    command_line: str
    username: str = ""


def _ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _json_result(result: subprocess.CompletedProcess[bytes], action: str) -> dict:
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace").strip()
        raise InteractiveAgentError(f"{action} failed: {stderr or f'exit {result.returncode}'}")
    lines = [line for line in result.stdout.decode("utf-8", "replace").splitlines() if line.strip()]
    if not lines:
        raise InteractiveAgentError(f"{action} returned no JSON")
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as error:
        raise InteractiveAgentError(f"{action} returned invalid JSON: {lines[-1]}") from error


def _control_script(script: str) -> str:
    prefix = "$ErrorActionPreference = 'Stop'\nSet-StrictMode -Version Latest\n"
    return prefix + script


def _control_powershell(script: str) -> str:
    return encoded_powershell(_control_script(script))


def _execute_control_script(
    target: SshTarget, script: str, remote_name: str, *, timeout: int,
) -> subprocess.CompletedProcess[bytes]:
    upload = target.upload_bytes(_control_script(script).encode("utf-8-sig"), remote_name, timeout=timeout)
    if upload.returncode != 0:
        stderr = upload.stderr.decode("utf-8", "replace").strip()
        raise InteractiveAgentError(f"control script upload failed: {stderr or f'exit {upload.returncode}'}")
    loader = (
        f"$path=Join-Path $env:USERPROFILE {_ps_literal(remote_name)};"
        "$code=0;"
        "try { & $path; if (-not $?) { if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) { $code=[int]$LASTEXITCODE } else { $code=1 } } } "
        "finally { Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue };"
        "exit $code"
    )
    return target.run(_control_powershell(loader), timeout=timeout)


class InteractiveOpenCode:
    """Launch one OpenCode process in the existing Windows console session."""

    def __init__(self, target: SshTarget, user: str, launcher_source: str) -> None:
        self.target = target
        self.user = user
        self.launcher_source = launcher_source

    @staticmethod
    def guest_dir(run_id: str) -> str:
        return rf"C:\WCB\runs\{run_id}"

    @staticmethod
    def task_name(run_id: str) -> str:
        return f"WCB-{run_id}"

    def preflight(self) -> ConsoleSession:
        script = r"""
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class WcbConsoleSession {
  [DllImport("kernel32.dll")]
  public static extern UInt32 WTSGetActiveConsoleSessionId();
}
'@
$rawConsoleId = [WcbConsoleSession]::WTSGetActiveConsoleSessionId()
$sessionId = if ($rawConsoleId -eq [uint32]::MaxValue) { -1 } else { [int]$rawConsoleId }
$matching = @()
if ($sessionId -ge 0) {
  foreach ($process in @(Get-CimInstance Win32_Process -Filter "Name='explorer.exe'" | Where-Object SessionId -eq $sessionId)) {
    $owner = Invoke-CimMethod -InputObject $process -MethodName GetOwner
    $username = if ($owner.ReturnValue -eq 0) { "$($owner.Domain)\$($owner.User)" } else { '' }
    if ($username.Split('\')[-1] -ieq "__WCB_USER__") {
      $matching += [pscustomobject]@{ process=$process; username=$username }
    }
  }
}
$locked = $false
if ($sessionId -ge 0) {
  $locked = @(Get-Process LogonUI -ErrorAction SilentlyContinue | Where-Object SessionId -eq $sessionId).Count -gt 0
}
[ordered]@{
  username = if ($matching.Count -gt 0) { [string]$matching[0].username } else { '' }
  matching_shell_count = $matching.Count
  explorer_pid = if ($matching.Count -gt 0) { [int]$matching[0].process.ProcessId } else { 0 }
  session_id = $sessionId
  locked = $locked
} | ConvertTo-Json -Compress
""".replace("__WCB_USER__", self.user.replace('"', '`"'))
        payload = _json_result(self.target.run(_control_powershell(script), timeout=30), "console preflight")
        if payload["session_id"] < 0:
            raise InteractiveAgentError("interactive Agent requires an active Windows console session")
        if payload["matching_shell_count"] < 1:
            raise InteractiveAgentError("active console has no Explorer shell owned by the configured guest user")
        if payload["locked"]:
            raise InteractiveAgentError("interactive Agent requires an unlocked console session")
        username = str(payload["username"])
        if username.rsplit("\\", 1)[-1].casefold() != self.user.casefold():
            raise InteractiveAgentError(
                f"console user {username!r} does not match configured guest user {self.user!r}"
            )
        return ConsoleSession(username, int(payload["session_id"]), int(payload["explorer_pid"]))

    def stage(
        self,
        run_id: str,
        *,
        executable: str,
        arguments: Sequence[str],
        workspace: str,
        expected_session_id: int,
        environment: dict[str, str] | None = None,
        prepend_shadow: bool = True,
    ) -> None:
        guest_dir = self.guest_dir(run_id)
        request = {
            "run_id": run_id,
            "executable": executable,
            "arguments": list(arguments),
            "workspace": workspace,
            "expected_session_id": expected_session_id,
            "expected_username": self.user,
            "environment": environment or {},
            "prepend_shadow": prepend_shadow,
        }
        request_bytes = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request_b64 = base64.b64encode(request_bytes).decode("ascii")
        launcher_b64 = base64.b64encode(self.launcher_source.encode("utf-8")).decode("ascii")
        script = f"""
$root = {_ps_literal(guest_dir)}
New-Item -ItemType Directory -Path $root -Force | Out-Null
[IO.File]::WriteAllBytes((Join-Path $root 'request.json'),[Convert]::FromBase64String('{request_b64}'))
[IO.File]::WriteAllBytes((Join-Path $root 'launch.ps1'),[Convert]::FromBase64String('{launcher_b64}'))
"""
        result = _execute_control_script(
            self.target, script, f"wcb-{run_id}-stage.ps1", timeout=30,
        )
        if result.returncode != 0:
            raise InteractiveAgentError(
                "interactive Agent staging failed: " + result.stderr.decode("utf-8", "replace").strip()
            )

    def start(self, run_id: str, *, hidden: bool = False) -> None:
        guest_dir = self.guest_dir(run_id)
        task_name = self.task_name(run_id)
        launcher = guest_dir + r"\launch.ps1"
        request = guest_dir + r"\request.json"
        window_style = '-WindowStyle Hidden ' if hidden else ''
        action_arguments = f'-NoLogo -NoProfile {window_style}-ExecutionPolicy Bypass -File "{launcher}" -RequestPath "{request}"'
        hidden_setting = ' -Hidden' if hidden else ''
        script = f"""
$action = New-ScheduledTaskAction -Execute 'C:\\Program Files\\PowerShell\\7\\pwsh.exe' -Argument {_ps_literal(action_arguments)}
$principal = New-ScheduledTaskPrincipal -UserId {_ps_literal(self.user)} -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew{hidden_setting}
Register-ScheduledTask -TaskName {_ps_literal(task_name)} -Action $action -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName {_ps_literal(task_name)}
"""
        result = self.target.run(_control_powershell(script), timeout=30)
        if result.returncode != 0:
            raise InteractiveAgentError(
                "interactive Agent start failed: " + result.stderr.decode("utf-8", "replace").strip()
            )

    def inspect_launcher(
        self, run_id: str, console: ConsoleSession, *, timeout: float = 20.0,
    ) -> LauncherIdentity:
        guest_dir = self.guest_dir(run_id)
        state_path = guest_dir + r"\state.json"
        result_path = guest_dir + r"\result.json"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            script = rf"""
$statePath = {_ps_literal(state_path)}
$resultPath = {_ps_literal(result_path)}
if (Test-Path -LiteralPath $statePath) {{
  $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
  $wrapper = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$state.wrapper_pid)" -ErrorAction SilentlyContinue
  $ownerName = ''
  if ($null -ne $wrapper) {{
    $owner = Invoke-CimMethod -InputObject $wrapper -MethodName GetOwner
    if ($owner.ReturnValue -eq 0) {{ $ownerName = "$($owner.Domain)\$($owner.User)" }}
  }}
  [ordered]@{{
    found=$true
    state=$state
    wrapper_found=($null -ne $wrapper)
    wrapper_session_id=if ($null -ne $wrapper) {{ [int]$wrapper.SessionId }} else {{ -1 }}
    wrapper_username=$ownerName
    wrapper_executable=if ($null -ne $wrapper) {{ [string]$wrapper.ExecutablePath }} else {{ '' }}
    wrapper_command_line=if ($null -ne $wrapper) {{ [string]$wrapper.CommandLine }} else {{ '' }}
    finished=(Test-Path -LiteralPath $resultPath)
  }} | ConvertTo-Json -Compress -Depth 4
}} else {{
  [ordered]@{{ found=$false; finished=(Test-Path -LiteralPath $resultPath) }} | ConvertTo-Json -Compress
}}
"""
            payload = _json_result(self.target.run(_control_powershell(script), timeout=30), "launcher inspection")
            if payload.get("found"):
                state = payload["state"]
                if str(state.get("run_id")) != run_id:
                    raise InteractiveAgentError("launcher state run_id does not match this run")
                if int(state.get("session_id", -1)) != console.session_id:
                    raise InteractiveAgentError("launcher session does not match the active console session")
                username = str(state.get("username", ""))
                if username.rsplit("\\", 1)[-1].casefold() != self.user.casefold():
                    raise InteractiveAgentError("launcher user does not match the configured guest user")
                if payload.get("wrapper_found"):
                    live_values = {
                        "session_id": int(payload["wrapper_session_id"]),
                        "username": str(payload["wrapper_username"]),
                        "executable": str(payload["wrapper_executable"]),
                        "command_line": str(payload["wrapper_command_line"]),
                    }
                    if live_values["session_id"] != console.session_id:
                        raise InteractiveAgentError("live launcher is not in the active console session")
                    if live_values["username"].casefold() != username.casefold():
                        raise InteractiveAgentError("live launcher user does not match its state")
                    if live_values["executable"].casefold() != str(state["wrapper_executable"]).casefold():
                        raise InteractiveAgentError("live launcher executable does not match its state")
                    if live_values["command_line"] != str(state["wrapper_command_line"]):
                        raise InteractiveAgentError("live launcher command line does not match its state")
                elif not payload.get("finished"):
                    raise InteractiveAgentError("launcher state exists but its process is missing")
                return LauncherIdentity(
                    run_id=run_id, task_name=self.task_name(run_id),
                    wrapper_pid=int(state["wrapper_pid"]), session_id=int(state["session_id"]),
                    username=username, executable=str(state["wrapper_executable"]),
                    command_line=str(state["wrapper_command_line"]),
                    launcher_path=self.guest_dir(run_id) + r"\launch.ps1",
                    request_path=self.guest_dir(run_id) + r"\request.json",
                )
            if payload.get("finished"):
                raise InteractiveAgentError("interactive launcher exited before its identity was captured")
            time.sleep(0.5)
        raise InteractiveAgentError("timed out waiting for interactive launcher identity")

    def inspect_process(
        self, launcher: LauncherIdentity, *, timeout: float = 20.0,
    ) -> InteractiveProcess:
        state_path = self.guest_dir(launcher.run_id) + r"\state.json"
        request_path = launcher.request_path
        result_path = self.guest_dir(launcher.run_id) + r"\result.json"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            script = rf"""
$statePath = {_ps_literal(state_path)}
$requestPath = {_ps_literal(request_path)}
$resultPath = {_ps_literal(result_path)}
if (Test-Path -LiteralPath $statePath) {{
  $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
  $request = Get-Content -LiteralPath $requestPath -Raw | ConvertFrom-Json
  $children = @(Get-CimInstance Win32_Process | Where-Object {{
    $state.phase -eq 'agent_starting' -and
    $_.ParentProcessId -eq {launcher.wrapper_pid} -and
    $_.SessionId -eq {launcher.session_id} -and
    $_.ExecutablePath -eq [string]$request.executable
  }})
  $ownerName = ''
  if ($children.Count -eq 1) {{
    $owner = Invoke-CimMethod -InputObject $children[0] -MethodName GetOwner
    if ($owner.ReturnValue -eq 0) {{ $ownerName = "$($owner.Domain)\$($owner.User)" }}
  }}
  [ordered]@{{
    run_id = [string]$state.run_id
    phase = [string]$state.phase
    wrapper_pid = [int]$state.wrapper_pid
    child_count = $children.Count
    pid = if ($children.Count -eq 1) {{ [int]$children[0].ProcessId }} else {{ 0 }}
    parent_pid = if ($children.Count -eq 1) {{ [int]$children[0].ParentProcessId }} else {{ 0 }}
    session_id = if ($children.Count -eq 1) {{ [int]$children[0].SessionId }} else {{ -1 }}
    executable = if ($children.Count -eq 1) {{ [string]$children[0].ExecutablePath }} else {{ '' }}
    command_line = if ($children.Count -eq 1) {{ [string]$children[0].CommandLine }} else {{ '' }}
    username = $ownerName
    finished = Test-Path -LiteralPath $resultPath
  }} | ConvertTo-Json -Compress
}} else {{
  [ordered]@{{ wrapper_pid=0; child_count=0; finished=(Test-Path -LiteralPath $resultPath) }} | ConvertTo-Json -Compress
}}
"""
            payload = _json_result(self.target.run(_control_powershell(script), timeout=30), "process inspection")
            if payload.get("child_count") == 1:
                if payload.get("run_id") != launcher.run_id or int(payload["wrapper_pid"]) != launcher.wrapper_pid:
                    raise InteractiveAgentError("Agent state does not match the captured launcher")
                username = str(payload.get("username", ""))
                if username.rsplit("\\", 1)[-1].casefold() != self.user.casefold():
                    raise InteractiveAgentError("Agent user does not match the configured guest user")
                return InteractiveProcess(
                    run_id=launcher.run_id,
                    task_name=launcher.task_name,
                    wrapper_pid=int(payload["wrapper_pid"]),
                    pid=int(payload["pid"]),
                    session_id=int(payload["session_id"]),
                    parent_pid=int(payload["parent_pid"]),
                    executable=str(payload["executable"]),
                    command_line=str(payload["command_line"]),
                    username=username,
                )
            if payload.get("child_count", 0) > 1:
                raise InteractiveAgentError("interactive launcher created more than one matching OpenCode process")
            if payload.get("finished"):
                raise InteractiveAgentError("interactive OpenCode exited before its process identity was captured")
            time.sleep(0.5)
        raise InteractiveAgentError("timed out waiting for interactive OpenCode process identity")

    def read_result(self, launcher: LauncherIdentity) -> dict | None:
        result_path = self.guest_dir(launcher.run_id) + r"\result.json"
        script = rf"""
$path = {_ps_literal(result_path)}
if (Test-Path -LiteralPath $path) {{ Get-Content -LiteralPath $path -Raw }}
"""
        result = self.target.run(_control_powershell(script), timeout=30)
        if result.returncode != 0:
            raise InteractiveAgentError("failed to read interactive Agent result")
        value = result.stdout.decode("utf-8", "replace").strip()
        if not value:
            return None
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as error:
            raise InteractiveAgentError("interactive Agent result is invalid JSON") from error
        expected = {
            "run_id": launcher.run_id,
            "wrapper_pid": launcher.wrapper_pid,
            "session_id": launcher.session_id,
        }
        for field, expected_value in expected.items():
            if payload.get(field) != expected_value:
                raise InteractiveAgentError(f"interactive Agent result {field} does not match this run")
        username = str(payload.get("username", ""))
        if username.rsplit("\\", 1)[-1].casefold() != self.user.casefold():
            raise InteractiveAgentError("interactive Agent result user does not match this run")
        if payload.get("phase") != "finished":
            raise InteractiveAgentError("interactive Agent result is not a completed Agent result")
        if not isinstance(payload.get("exit_code"), int):
            raise InteractiveAgentError("interactive Agent result has no integer exit_code")
        return payload

    def mark_running(self, process: InteractiveProcess) -> None:
        state_path = self.guest_dir(process.run_id) + r"\state.json"
        script = rf"""
$path = {_ps_literal(state_path)}
$state = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
if ($state.run_id -ne {_ps_literal(process.run_id)} -or [int]$state.wrapper_pid -ne {process.wrapper_pid} -or [int]$state.session_id -ne {process.session_id}) {{
  throw 'refusing to update mismatched launcher state'
}}
$state.phase = 'agent_running'
$state | Add-Member -NotePropertyName agent_pid -NotePropertyValue {process.pid} -Force
$temporary = "$path.tmp"
$json = $state | ConvertTo-Json -Compress
[IO.File]::WriteAllText($temporary, $json, [Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $temporary -Destination $path -Force
"""
        result = self.target.run(_control_powershell(script), timeout=30)
        if result.returncode != 0:
            raise InteractiveAgentError(
                "failed to mark interactive Agent running: "
                + result.stderr.decode("utf-8", "replace").strip()
            )

    def collect_output(self, run_id: str) -> tuple[bytes, bytes]:
        root = self.guest_dir(run_id)
        script = rf"""
$root = {_ps_literal(root)}
$stdout = Join-Path $root 'opencode.stdout.jsonl'
$stderr = Join-Path $root 'opencode.stderr.log'
[ordered]@{{
  stdout = if (Test-Path -LiteralPath $stdout) {{ [Convert]::ToBase64String([IO.File]::ReadAllBytes($stdout)) }} else {{ '' }}
  stderr = if (Test-Path -LiteralPath $stderr) {{ [Convert]::ToBase64String([IO.File]::ReadAllBytes($stderr)) }} else {{ '' }}
}} | ConvertTo-Json -Compress
"""
        payload = _json_result(self.target.run(_control_powershell(script), timeout=30), "output collection")
        return base64.b64decode(payload["stdout"]), base64.b64decode(payload["stderr"])

    def collect_auth_output(self, run_id: str) -> tuple[bytes, bytes]:
        root = self.guest_dir(run_id)
        script = rf"""
$root = {_ps_literal(root)}
$stdout = Join-Path $root 'opencode.auth.stdout.log'
$stderr = Join-Path $root 'opencode.auth.stderr.log'
[ordered]@{{
  stdout = if (Test-Path -LiteralPath $stdout) {{ [Convert]::ToBase64String([IO.File]::ReadAllBytes($stdout)) }} else {{ '' }}
  stderr = if (Test-Path -LiteralPath $stderr) {{ [Convert]::ToBase64String([IO.File]::ReadAllBytes($stderr)) }} else {{ '' }}
}} | ConvertTo-Json -Compress
"""
        payload = _json_result(self.target.run(_control_powershell(script), timeout=30), "auth output collection")
        return base64.b64decode(payload["stdout"]), base64.b64decode(payload["stderr"])

    def process_alive(self, process: InteractiveProcess) -> bool:
        script = rf"""
$p = Get-CimInstance Win32_Process -Filter "ProcessId = {process.pid}" -ErrorAction SilentlyContinue
$ownerName = ''
if ($null -ne $p) {{
  $owner = Invoke-CimMethod -InputObject $p -MethodName GetOwner
  if ($owner.ReturnValue -eq 0) {{ $ownerName = "$($owner.Domain)\$($owner.User)" }}
}}
$ok = $null -ne $p -and [int]$p.ParentProcessId -eq {process.parent_pid} -and [int]$p.SessionId -eq {process.session_id} -and $p.ExecutablePath -eq {_ps_literal(process.executable)} -and $ownerName -eq {_ps_literal(process.username)}
[ordered]@{{ alive = $ok }} | ConvertTo-Json -Compress
"""
        payload = _json_result(self.target.run(_control_powershell(script), timeout=30), "process liveness check")
        return bool(payload["alive"])

    def terminate(self, process: InteractiveProcess) -> None:
        script = rf"""
$p = Get-CimInstance Win32_Process -Filter "ProcessId = {process.pid}" -ErrorAction SilentlyContinue
if ($null -ne $p) {{
  $owner = Invoke-CimMethod -InputObject $p -MethodName GetOwner
  $ownerName = if ($owner.ReturnValue -eq 0) {{ "$($owner.Domain)\$($owner.User)" }} else {{ '' }}
  if ([int]$p.ParentProcessId -ne {process.parent_pid} -or [int]$p.SessionId -ne {process.session_id} -or $p.ExecutablePath -ne {_ps_literal(process.executable)} -or $ownerName -ne {_ps_literal(process.username)}) {{
    throw 'refusing to terminate a process whose identity no longer matches this run'
  }}
  & taskkill.exe /PID {process.pid} /T /F | Out-Null
}}
"""
        result = self.target.run(_control_powershell(script), timeout=30)
        if result.returncode != 0:
            raise InteractiveAgentError(
                "interactive Agent termination failed: " + result.stderr.decode("utf-8", "replace").strip()
            )

    def cleanup(
        self, run_id: str, console: ConsoleSession,
        launcher: LauncherIdentity | None, process: InteractiveProcess | None,
        *, preserve_staging: bool = False, hidden: bool = False,
    ) -> dict:
        task_name = self.task_name(run_id)
        guest_dir = self.guest_dir(run_id)
        launcher_path = guest_dir + r"\launch.ps1"
        request_path = guest_dir + r"\request.json"
        window_style = '-WindowStyle Hidden ' if hidden else ''
        expected_arguments = f'-NoLogo -NoProfile {window_style}-ExecutionPolicy Bypass -File "{launcher_path}" -RequestPath "{request_path}"'
        expected_wrapper = launcher.wrapper_pid if launcher is not None else 0
        process_pid = process.pid if process is not None else 0
        process_parent = process.parent_pid if process is not None else 0
        process_executable = process.executable if process is not None else ""
        process_user = process.username if process is not None else ""
        preserve_staging_ps = "$true" if preserve_staging else "$false"
        script = rf"""
$task = Get-ScheduledTask -TaskName {_ps_literal(task_name)} -ErrorAction SilentlyContinue
$statePath = Join-Path {_ps_literal(guest_dir)} 'state.json'
$resultPath = Join-Path {_ps_literal(guest_dir)} 'result.json'
$diagnostic = [ordered]@{{
  run_id={_ps_literal(run_id)}
  task_found=($null -ne $task)
  state_found=(Test-Path -LiteralPath $statePath)
  result_found=(Test-Path -LiteralPath $resultPath)
  task_execute=if ($null -ne $task -and $task.Actions.Count -gt 0) {{ [string]$task.Actions[0].Execute }} else {{ '' }}
  task_arguments=if ($null -ne $task -and $task.Actions.Count -gt 0) {{ [string]$task.Actions[0].Arguments }} else {{ '' }}
}}
$reason = $null
$state = $null
$result = $null
$terminalResultVerified = $false
$agentFound = $false
$wrapperFound = $false
$agentTerminated = $false
$wrapperTerminated = $false

if (-not (Test-Path -LiteralPath $statePath)) {{
  $reason = 'launcher state is missing; refusing cleanup of possible partial staging'
}} else {{
  $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
  $diagnostic.state = $state
  if ($state.run_id -ne {_ps_literal(run_id)} -or [int]$state.session_id -ne {console.session_id} -or $state.username.Split('\')[-1] -ine {_ps_literal(self.user)}) {{
    $reason = 'launcher state identity does not match this run'
  }} elseif ({expected_wrapper} -gt 0 -and [int]$state.wrapper_pid -ne {expected_wrapper}) {{
    $reason = 'launcher wrapper PID does not match captured identity'
  }}
}}
if ($null -eq $reason -and (Test-Path -LiteralPath $resultPath)) {{
  $result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
  $diagnostic.result = $result
  $phaseIsTerminal = ($state.phase -eq 'auth_failed' -and $result.phase -eq 'auth_failed') -or ($state.phase -eq 'finished' -and $result.phase -eq 'finished')
  $resultIdentityMatches = $result.run_id -eq {_ps_literal(run_id)} -and [int]$result.wrapper_pid -eq [int]$state.wrapper_pid -and [int]$result.session_id -eq {console.session_id} -and $result.username.Split('\')[-1] -ieq {_ps_literal(self.user)}
  if (-not $phaseIsTerminal -or -not $resultIdentityMatches) {{
    $reason = 'terminal result identity or phase does not match this run'
  }} else {{
    $terminalResultVerified = $true
  }}
}}
if ($null -eq $reason -and $null -ne $task -and ($task.Actions.Count -ne 1 -or $task.Actions[0].Execute -ne 'C:\Program Files\PowerShell\7\pwsh.exe' -or $task.Actions[0].Arguments -ne {_ps_literal(expected_arguments)})) {{
  $reason = 'scheduled task action does not match this run launcher/request absolute paths'
}}
if ($null -eq $reason -and $null -eq $task -and -not $terminalResultVerified) {{
  $reason = 'scheduled task is missing without a verified terminal result'
}}
if ($null -eq $reason -and {process_pid} -gt 0) {{
  $agent = Get-CimInstance Win32_Process -Filter "ProcessId = {process_pid}" -ErrorAction SilentlyContinue
  $agentFound = $null -ne $agent
  if ($null -ne $agent) {{
    $owner = Invoke-CimMethod -InputObject $agent -MethodName GetOwner
    $ownerName = if ($owner.ReturnValue -eq 0) {{ "$($owner.Domain)\$($owner.User)" }} else {{ '' }}
    if ([int]$agent.ParentProcessId -ne {process_parent} -or [int]$agent.SessionId -ne {console.session_id} -or $agent.ExecutablePath -ne {_ps_literal(process_executable)} -or $ownerName -ne {_ps_literal(process_user)}) {{
      $reason = 'Agent identity no longer matches this run'
    }} else {{
      & taskkill.exe /PID {process_pid} /T /F | Out-Null
      if ($LASTEXITCODE -ne 0) {{ throw "taskkill Agent exited $LASTEXITCODE" }}
      $agentTerminated = $true
    }}
  }}
}}
if ($null -eq $reason) {{
  $wrapper = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$state.wrapper_pid)" -ErrorAction SilentlyContinue
  $wrapperFound = $null -ne $wrapper
  if ($null -ne $wrapper) {{
    $owner = Invoke-CimMethod -InputObject $wrapper -MethodName GetOwner
    $ownerName = if ($owner.ReturnValue -eq 0) {{ "$($owner.Domain)\$($owner.User)" }} else {{ '' }}
    if ([int]$wrapper.SessionId -ne {console.session_id} -or $wrapper.ExecutablePath -ne [string]$state.wrapper_executable -or $wrapper.CommandLine -ne [string]$state.wrapper_command_line -or $ownerName -ne [string]$state.username) {{
      $reason = 'launcher process identity no longer matches this run'
    }} else {{
      & taskkill.exe /PID ([int]$state.wrapper_pid) /T /F | Out-Null
      if ($LASTEXITCODE -ne 0) {{ throw "taskkill launcher exited $LASTEXITCODE" }}
      $wrapperTerminated = $true
    }}
  }}
}}
if ($null -eq $reason) {{
  if ({process_pid} -gt 0 -and $null -ne (Get-CimInstance Win32_Process -Filter "ProcessId = {process_pid}" -ErrorAction SilentlyContinue)) {{
    $reason = 'Agent process tree did not stop'
  }} elseif ($null -ne (Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$state.wrapper_pid)" -ErrorAction SilentlyContinue)) {{
    $reason = 'launcher process tree did not stop'
  }} elseif (-not $terminalResultVerified -and -not $agentTerminated -and -not $wrapperTerminated) {{
    $reason = 'nonterminal launcher disappeared without a captured or terminated process tree'
  }}
}}
if ($null -eq $reason) {{
  if ($null -ne $task) {{ Unregister-ScheduledTask -TaskName {_ps_literal(task_name)} -Confirm:$false }}
  if (-not {preserve_staging_ps}) {{ Remove-Item -LiteralPath {_ps_literal(guest_dir)} -Recurse -Force }}
}}
$taskAbsentAfter = $null -eq (Get-ScheduledTask -TaskName {_ps_literal(task_name)} -ErrorAction SilentlyContinue)
$stagingExistsAfter = Test-Path -LiteralPath {_ps_literal(guest_dir)}
$stagingConditionMet = if ({preserve_staging_ps}) {{ $stagingExistsAfter }} else {{ -not $stagingExistsAfter }}
if ($null -eq $reason -and (-not $taskAbsentAfter -or -not $stagingConditionMet)) {{
  $reason = 'cleanup postcondition failed'
}}
[ordered]@{{
  cleaned=($null -eq $reason)
  reason=$reason
  state_phase=if ($null -ne $state) {{ [string]$state.phase }} else {{ '' }}
  result_phase=if ($null -ne $result) {{ [string]$result.phase }} else {{ '' }}
  terminal_result_found=($null -ne $result)
  terminal_result_verified=$terminalResultVerified
  wrapper_found=$wrapperFound
  agent_found=$agentFound
  wrapper_terminated=$wrapperTerminated
  agent_terminated=$agentTerminated
  task_absent_after=$taskAbsentAfter
  staging_condition_met=$stagingConditionMet
  staging_preserved=$stagingExistsAfter
  diagnostic=$diagnostic
}} | ConvertTo-Json -Compress -Depth 6
"""
        payload = _json_result(
            _execute_control_script(
                self.target, script, f"wcb-{run_id}-cleanup.ps1", timeout=30,
            ),
            "interactive cleanup",
        )
        if payload.get("cleaned") and (
            payload.get("task_absent_after") is not True
            or payload.get("staging_condition_met") is not True
        ):
            payload["cleaned"] = False
            payload["reason"] = "cleanup returned success without satisfying postconditions"
        return payload


def encoded_powershell(script: str, *, executable: str = "powershell.exe") -> str:
    import base64

    payload = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return f"{executable} -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand {payload}"


def opencode_command(
    executable: str,
    workspace: str,
    model: str,
    variant: str,
    agent: str,
    prompt: str,
) -> str:
    args: Sequence[str] = (
        executable, "--pure", "run", "--auto", "--agent", agent,
        "--format", "json", "--dir", workspace, "--model", model,
        "--variant", variant, prompt,
    )
    return subprocess.list2cmdline(list(args))
