from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

from runner.opencode import (
    InteractiveAgentError,
    InteractiveOpenCode,
    SshTarget,
    _execute_control_script,
)
from runner.report import utc_now, write_bytes_atomic, write_json_atomic


PROMPT = 'Reply with exactly: OK'
DEFAULT_TIMEOUT_SECONDS = 60


class ModelSmokeError(RuntimeError):
    pass


def _workspace_script(root: str, user: str) -> str:
    return rf"""
$root = '{root}'
$user = '{user.replace("'", "''")}'
Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $root -Force | Out-Null
$sid = ([Security.Principal.NTAccount]$user).Translate(
    [Security.Principal.SecurityIdentifier]
).Value
$grant = '*' + $sid + ':(OI)(CI)M'
& icacls.exe $root /grant:r $grant /T /C | Out-Null
if ($LASTEXITCODE -ne 0) {{ throw "icacls smoke workspace grant failed: $LASTEXITCODE" }}
"""


def _remove_workspace(target: SshTarget, root: str, run_id: str) -> None:
    result = _execute_control_script(
        target,
        rf"Remove-Item -LiteralPath '{root}' -Recurse -Force -ErrorAction SilentlyContinue",
        f'wcb-{run_id}-smoke-workspace-remove.ps1',
        timeout=30,
    )
    if result.returncode != 0:
        detail = result.stderr.decode('utf-8', 'replace').strip()
        raise ModelSmokeError(
            f'smoke workspace cleanup failed: {detail or f"exit {result.returncode}"}'
        )


def _parse_response(raw: bytes) -> tuple[str, list[str]]:
    reply = ''
    errors: list[str] = []
    for number, line in enumerate(raw.decode('utf-8', 'replace').splitlines(), start=1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            errors.append(f'invalid OpenCode JSONL line {number}: {error}')
            continue
        if not isinstance(event, dict):
            errors.append(f'invalid OpenCode JSONL line {number}: expected object')
            continue
        if event.get('type') == 'error':
            value = event.get('error')
            if isinstance(value, dict):
                data = value.get('data')
                message = data.get('message') if isinstance(data, dict) else None
                message = message or value.get('message')
            else:
                message = str(value) if value is not None else None
            errors.append(str(message or 'OpenCode reported an unknown error'))
        part = event.get('part')
        if event.get('type') == 'text' and isinstance(part, dict):
            text = part.get('text')
            if isinstance(text, str):
                reply = text.strip()
    return reply, errors


def run(config: dict, project_root: Path, output_root: Path) -> int:
    opencode = config.get('opencode')
    guest = config.get('guest')
    if not isinstance(opencode, dict) or not isinstance(guest, dict):
        print('benchmark config is missing opencode or guest settings', file=sys.stderr)
        return 2
    try:
        executable = opencode['executable']
        model = opencode['model']
        variant = opencode['variant']
        agent = opencode['agent']
        variant_explicit = opencode.get('variant_explicit', True)
        timeout_seconds = int(
            config.get('runtime', {}).get(
                'model_smoke_timeout_seconds', DEFAULT_TIMEOUT_SECONDS,
            )
        )
    except (KeyError, TypeError, ValueError) as error:
        print(f'invalid model smoke configuration: {error}', file=sys.stderr)
        return 2
    if not all(isinstance(value, str) and value for value in (
        executable, model, variant, agent,
    )):
        print('model smoke executable/model/variant/agent must be non-empty', file=sys.stderr)
        return 2
    if type(variant_explicit) is not bool:
        print('model smoke variant_explicit must be boolean', file=sys.stderr)
        return 2
    if not variant_explicit and variant != 'provider-default':
        print('implicit model smoke variant must be provider-default', file=sys.stderr)
        return 2
    if timeout_seconds <= 0:
        print('model smoke timeout must be positive', file=sys.stderr)
        return 2

    run_id = 'model-smoke-' + uuid.uuid4().hex[:8]
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    started_at = utc_now()
    started = time.monotonic()
    workspace_root = rf'C:\WCB\model-smokes\{run_id}'
    workspace = workspace_root + r'\workspace'
    target = SshTarget(
        address=guest['address'], user=guest['user'],
        identity=Path(guest['ssh_key']), known_hosts=Path(guest['known_hosts']),
    )
    launcher_source = (
        project_root / 'config/run-interactive-opencode.ps1'
    ).read_text(encoding='utf-8')
    interactive = InteractiveOpenCode(
        target, guest.get('interactive_user', guest['user']), launcher_source,
    )

    stdout = b''
    stderr = b''
    reply = ''
    errors: list[str] = []
    console = None
    launcher = None
    process = None
    result = None
    workspace_attempted = False
    launcher_attempted = False
    timed_out = False
    process_evidence = None
    try:
        console = interactive.preflight()
        workspace_attempted = True
        prepared = _execute_control_script(
            target,
            _workspace_script(workspace, interactive.user),
            f'wcb-{run_id}-smoke-workspace.ps1',
            timeout=30,
        )
        if prepared.returncode != 0:
            detail = prepared.stderr.decode('utf-8', 'replace').strip()
            raise ModelSmokeError(
                f'smoke workspace setup failed: {detail or f"exit {prepared.returncode}"}'
            )
        arguments = [
            '--pure', 'run', '--auto', '--agent', agent, '--format', 'json',
            '--dir', workspace, '--model', model,
        ]
        if variant_explicit:
            arguments.extend(('--variant', variant))
        arguments.append(PROMPT)
        launcher_attempted = True
        interactive.stage(
            run_id,
            executable=executable,
            arguments=tuple(arguments),
            workspace=workspace,
            expected_session_id=console.session_id,
            prepend_shadow=False,
        )
        interactive.start(run_id, hidden=True)
        launcher = interactive.inspect_launcher(run_id, console)
        process = interactive.inspect_process(launcher)
        command_line = process.command_line.casefold()
        for expected in (workspace, model, agent):
            if expected.casefold() not in command_line:
                raise ModelSmokeError(
                    f'smoke command line is missing expected value: {expected}'
                )
        if variant_explicit and variant.casefold() not in command_line:
            raise ModelSmokeError(
                f'smoke command line is missing expected variant: {variant}'
            )
        if not variant_explicit and '--variant' in command_line:
            raise ModelSmokeError('smoke command line unexpectedly contains --variant')
        interactive.mark_running(process)
        process_evidence = {
            'username': process.username,
            'pid': process.pid,
            'parent_pid': process.parent_pid,
            'wrapper_pid': process.wrapper_pid,
            'session_id': process.session_id,
            'console_session_id': console.session_id,
            'executable': process.executable,
            'command_line': process.command_line,
        }
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            result = interactive.read_result(launcher)
            if result is not None:
                break
            time.sleep(0.5)
        if result is None:
            timed_out = True
            interactive.terminate(process)
            errors.append(f'model smoke timed out after {timeout_seconds} seconds')
        stdout, stderr = interactive.collect_output(run_id)
        reply, output_errors = _parse_response(stdout)
        errors.extend(output_errors)
    except (InteractiveAgentError, ModelSmokeError, KeyError, OSError) as error:
        errors.append(str(error))
        if launcher_attempted:
            try:
                stdout, stderr = interactive.collect_output(run_id)
                reply, output_errors = _parse_response(stdout)
                errors.extend(output_errors)
            except BaseException:
                pass
    finally:
        if launcher_attempted and console is not None:
            try:
                cleanup = interactive.cleanup(
                    run_id, console, launcher, process, hidden=True,
                )
                if not cleanup.get('cleaned'):
                    errors.append(
                        'smoke launcher cleanup failed: ' + str(cleanup.get('reason'))
                    )
            except BaseException as error:
                errors.append(f'smoke launcher cleanup failed: {error}')
        if workspace_attempted:
            try:
                _remove_workspace(target, workspace_root, run_id)
            except ModelSmokeError as error:
                errors.append(str(error))

    write_bytes_atomic(run_dir / 'opencode.stdout.jsonl', stdout)
    write_bytes_atomic(run_dir / 'opencode.stderr.log', stderr)
    exit_code = None if result is None else result.get('exit_code')
    passed = (
        exit_code == 0 and not timed_out and reply == 'OK' and not errors
        and process_evidence is not None
    )
    report = {
        'schema': 'wcb.model-smoke/v1',
        'run_id': run_id,
        'model': model,
        'variant': variant,
        'variant_explicit': variant_explicit,
        'prompt': PROMPT,
        'reply': reply,
        'exit_code': exit_code,
        'timed_out': timed_out,
        'passed': passed,
        'status': 'passed' if passed else 'failed',
        'errors': errors,
        'process': process_evidence,
        'started_at': started_at,
        'finished_at': utc_now(),
        'duration_seconds': round(time.monotonic() - started, 3),
    }
    write_json_atomic(run_dir / 'smoke.json', report)
    print(json.dumps(report, ensure_ascii=False, separators=(',', ':')))
    return 0 if passed else 1
