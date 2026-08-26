from __future__ import annotations

import json
from pathlib import Path

from runner.opencode import (
    InteractiveOpenCode,
    SshTarget,
    _execute_control_script,
)
from runner.report import utc_now, write_bytes_atomic, write_json_atomic


class OutputRecoveryError(RuntimeError):
    pass


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, json.JSONDecodeError) as error:
        raise OutputRecoveryError(f'invalid {path.name}: {error}') from error
    if not isinstance(value, dict):
        raise OutputRecoveryError(f'invalid {path.name}: expected object')
    return value


def _read_jsonl(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding='utf-8-sig').splitlines()
    except OSError as error:
        raise OutputRecoveryError(f'invalid {path.name}: {error}') from error
    records = []
    for number, line in enumerate(lines, start=1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise OutputRecoveryError(
                f'invalid {path.name} line {number}: {error}'
            ) from error
        if not isinstance(value, dict):
            raise OutputRecoveryError(
                f'invalid {path.name} line {number}: expected object'
            )
        records.append(value)
    if not records:
        raise OutputRecoveryError(f'{path.name} contains no records')
    return records


def _opencode_records(raw: bytes, timestamp: str) -> list[dict]:
    records = []
    for line in raw.decode('utf-8', 'replace').splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            payload = {'raw': line}
        records.append({
            'ts': timestamp,
            'stream': 'agent',
            'event': 'opencode_event',
            'payload': payload,
        })
    if not records:
        raise OutputRecoveryError('recovered OpenCode stdout contains no records')
    return records


def recover_run(
    config: dict,
    output_root: Path,
    run_id: str,
) -> dict:
    if (
        not isinstance(run_id, str)
        or Path(run_id).name != run_id
        or not run_id.startswith('opencode-')
    ):
        raise OutputRecoveryError(f'invalid run id: {run_id!r}')
    run_dir = output_root / run_id
    if not run_dir.is_dir():
        raise OutputRecoveryError(f'run id does not exist: {run_id}')
    recovery_path = run_dir / 'output-recovery.json'
    if recovery_path.exists():
        recovery = _read_json(recovery_path)
        if recovery.get('run_id') != run_id:
            raise OutputRecoveryError('existing output recovery has wrong run id')
        return recovery

    metadata = _read_json(run_dir / 'metadata.json')
    if (
        metadata.get('run_id') != run_id
        or metadata.get('evidence_schema') != 'wcb.run-evidence/v3'
        or metadata.get('timed_out') is not True
        or metadata.get('agent_exit') != 124
    ):
        raise OutputRecoveryError('run is not a timed-out v3 Agent run')
    orchestrator = _read_jsonl(run_dir / 'orchestrator.jsonl')
    if not any(
        record.get('event') == 'agent_output_collection_failed'
        for record in orchestrator
    ) or not any(
        record.get('event') == 'interactive_cleanup_finished'
        and record.get('guest_staging_preserved') is True
        for record in orchestrator
    ):
        raise OutputRecoveryError('run has no verified preserved-output condition')

    guest = config['guest']
    target = SshTarget(
        address=guest['address'],
        user=guest['user'],
        identity=Path(guest['ssh_key']),
        known_hosts=Path(guest['known_hosts']),
    )
    interactive = InteractiveOpenCode(
        target, guest.get('interactive_user', guest['user']), '',
    )
    stdout, stderr = interactive.collect_output(run_id)
    agent_records = _read_jsonl(run_dir / 'agent.jsonl')
    terminal_indexes = [
        index for index, record in enumerate(agent_records)
        if record.get('event') in {
            'process_finished', 'process_exit', 'process_timeout',
        }
    ]
    if len(terminal_indexes) != 1:
        raise OutputRecoveryError('agent.jsonl has no unique terminal event')
    terminal_index = terminal_indexes[0]
    terminal = agent_records[terminal_index]
    recovered_records = _opencode_records(stdout, str(terminal.get('ts', utc_now())))
    original_records = [
        record for record in agent_records
        if record.get('event') != 'opencode_event'
    ]
    terminal_index = next(
        index for index, record in enumerate(original_records)
        if record.get('event') in {
            'process_finished', 'process_exit', 'process_timeout',
        }
    )
    merged = (
        original_records[:terminal_index]
        + recovered_records
        + original_records[terminal_index:]
    )

    backups = {
        'agent.jsonl': 'agent.before-output-recovery.jsonl',
        'opencode.stdout.jsonl': 'opencode.stdout.before-output-recovery.jsonl',
        'opencode.stderr.log': 'opencode.stderr.before-output-recovery.log',
    }
    for source_name, backup_name in backups.items():
        backup = run_dir / backup_name
        if not backup.exists():
            write_bytes_atomic(backup, (run_dir / source_name).read_bytes())
    write_bytes_atomic(run_dir / 'opencode.stdout.jsonl', stdout)
    write_bytes_atomic(run_dir / 'opencode.stderr.log', stderr)
    write_bytes_atomic(
        run_dir / 'agent.jsonl',
        ''.join(
            json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n'
            for record in merged
        ).encode('utf-8'),
    )

    guest_dir = InteractiveOpenCode.guest_dir(run_id)
    task_name = InteractiveOpenCode.task_name(run_id)
    cleanup_script = rf"""
$root = '{guest_dir}'
$task = Get-ScheduledTask -TaskName '{task_name}' -ErrorAction SilentlyContinue
if ($null -ne $task) {{ throw 'refusing recovery cleanup while scheduled task exists' }}
$statePath = Join-Path $root 'state.json'
if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {{ throw 'recovery staging state is missing' }}
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if ($state.run_id -ne '{run_id}') {{ throw 'recovery staging run id is wrong' }}
foreach ($candidate in @([int]$state.wrapper_pid,[int]$state.agent_pid)) {{
    if ($candidate -gt 0 -and $null -ne (Get-CimInstance Win32_Process -Filter "ProcessId = $candidate" -ErrorAction SilentlyContinue)) {{
        throw "refusing recovery cleanup while process $candidate exists"
    }}
}}
Remove-Item -LiteralPath $root -Recurse -Force
if (Test-Path -LiteralPath $root) {{ throw 'recovery staging cleanup postcondition failed' }}
"""
    cleanup = _execute_control_script(
        target, cleanup_script, f'wcb-{run_id}-output-recovery-cleanup.ps1',
        timeout=60,
    )
    if cleanup.returncode != 0:
        detail = cleanup.stderr.decode('utf-8', 'replace').strip()
        raise OutputRecoveryError(
            f'output recovery cleanup failed: {detail or cleanup.returncode}'
        )
    recovery = {
        'schema': 'wcb.output-recovery/v1',
        'run_id': run_id,
        'source': guest_dir,
        'reason': 'stdout file was locked until timed-out Agent termination',
        'recovered_stdout_bytes': len(stdout),
        'recovered_stderr_bytes': len(stderr),
        'recovered_event_count': len(recovered_records),
        'backups': list(backups.values()),
        'captured_at': utc_now(),
    }
    write_json_atomic(recovery_path, recovery)
    return recovery
