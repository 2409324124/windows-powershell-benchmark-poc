from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

from runner.opencode import (
    InteractiveAgentError, InteractiveOpenCode, SshTarget,
    _execute_control_script, encoded_powershell,
)
from runner.report import JsonlLog, utc_now, write_bytes_atomic, write_json_atomic
from runner.vm import ScreenshotMonitor, VisualModeError, require_visual_domain


def _bench_config_content() -> str:
    return json.dumps({
        '$schema': 'https://opencode.ai/config.json',
        'share': 'disabled',
        'agent': {
            'bench': {
                'mode': 'primary',
                'description': 'Interactive Windows benchmark coding agent.',
                'prompt': (
                    'Work only on the supplied benchmark task and workspace. '
                    'Use the available Windows tools to implement and verify the fix.'
                ),
            },
        },
    }, ensure_ascii=False, separators=(',', ':'))


def _as_bytes(value: bytes | str | None) -> bytes:
    if value is None:
        return b''
    if isinstance(value, bytes):
        return value
    return value.encode('utf-8', 'replace')


def _record_agent_process(
    run_dir: Path,
    agent_log: JsonlLog,
    *,
    stdout: bytes | str | None,
    stderr: bytes | str | None,
    exit_code: int,
    timed_out: bool,
    timeout_seconds: int,
) -> None:
    raw_stdout = _as_bytes(stdout)
    raw_stderr = _as_bytes(stderr)
    write_bytes_atomic(run_dir / 'opencode.stdout.jsonl', raw_stdout)
    write_bytes_atomic(run_dir / 'opencode.stderr.log', raw_stderr)
    _record_stdout(agent_log, raw_stdout)
    fields = {
        'exit_code': exit_code,
        'timed_out': timed_out,
        'stderr': raw_stderr.decode('utf-8', 'replace'),
    }
    if timed_out:
        fields['timeout_seconds'] = timeout_seconds
    agent_log.emit('process_finished', **fields)


def _run_agent(
    target: SshTarget,
    command: str,
    timeout_seconds: int,
) -> tuple[bytes | str | None, bytes | str | None, int, bool]:
    """Compatibility helper for the legacy direct-SSH output capture tests."""
    try:
        result = target.run(command, timeout=timeout_seconds)
        return result.stdout, result.stderr, result.returncode, False
    except subprocess.TimeoutExpired as error:
        return error.stdout, error.stderr, 124, True


def _capture_workspace_snapshot(
    target: SshTarget,
    workspace: str,
    run_id: str,
) -> bytes:
    archive_name = f'wcb-{run_id}-workspace-after-agent.zip'
    script = rf"""
$workspace = '{workspace.replace("'", "''")}'
$archive = Join-Path $env:TEMP '{archive_name}'
if (-not (Test-Path -LiteralPath $workspace -PathType Container)) {{
    throw 'task workspace is missing before snapshot'
}}
Add-Type -AssemblyName System.IO.Compression.FileSystem
Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
try {{
    [IO.Compression.ZipFile]::CreateFromDirectory(
        $workspace,
        $archive,
        [IO.Compression.CompressionLevel]::Optimal,
        $false
    )
    [Convert]::ToBase64String([IO.File]::ReadAllBytes($archive))
}} finally {{
    Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
}}
"""
    result = _execute_control_script(
        target, script, f'wcb-{run_id}-workspace-snapshot.ps1', timeout=90,
    )
    if result.returncode != 0:
        detail = result.stderr.decode('utf-8', 'replace').strip()
        raise InteractiveAgentError(
            f'workspace snapshot failed: {detail or f"exit {result.returncode}"}'
        )
    encoded = result.stdout.decode('ascii', 'strict').strip()
    if not encoded:
        raise InteractiveAgentError('workspace snapshot returned no archive')
    try:
        return base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise InteractiveAgentError('workspace snapshot returned invalid base64') from error


def load_task(project_root: Path, task_id: str) -> tuple[Path, dict]:
    if not task_id or Path(task_id).name != task_id:
        raise ValueError(f'invalid task id: {task_id!r}')
    task = project_root / 'tasks' / task_id
    manifest_path = task / 'task.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('schema') != 'wcb.task/v1' or manifest.get('id') != task_id:
        raise ValueError(f'invalid task manifest: {manifest_path}')
    if not isinstance(manifest.get('workspace'), str) or not manifest['workspace'].startswith('C:\\WCB\\tasks\\'):
        raise ValueError(f'invalid task workspace: {manifest_path}')
    for filename in ('setup.ps1', 'prompt.md', 'evaluate.ps1'):
        if not (task / filename).is_file():
            raise ValueError(f'task {task_id} is missing {filename}')
    return task, manifest


def _record_stdout(agent_log: JsonlLog, raw_stdout: bytes) -> None:
    for line in raw_stdout.decode('utf-8', 'replace').splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            payload = {'raw': line}
        agent_log.emit('opencode_event', payload=payload)


def run(
    config: dict,
    project_root: Path,
    output_root: Path,
    *,
    visual: bool = False,
    run_id: str | None = None,
) -> int:
    task_id = str(config.get('task', 'ps002-path-quoting'))
    try:
        task, task_manifest = load_task(project_root, task_id)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f'Unable to load benchmark task {task_id}: {error}', file=sys.stderr)
        return 2

    domain = str(config.get('runtime', {}).get(
        'visual_domain', 'wcb-canary-transport-001',
    ))
    if visual:
        try:
            require_visual_domain(domain)
        except VisualModeError as error:
            print(error, file=sys.stderr)
            return 2

    guest = config['guest']
    target = SshTarget(
        address=guest['address'], user=guest['user'],
        identity=Path(guest['ssh_key']), known_hosts=Path(guest['known_hosts']),
    )
    launcher = (project_root / 'config/run-interactive-opencode.ps1').read_text(encoding='utf-8')
    interactive = InteractiveOpenCode(
        target, guest.get('interactive_user', guest['user']), launcher,
    )
    try:
        console = interactive.preflight()
    except InteractiveAgentError as error:
        print(error, file=sys.stderr)
        return 2

    task_code = task_id.split('-', 1)[0]
    if run_id is None:
        run_id = f'opencode-{task_code}-' + uuid.uuid4().hex[:8]
    elif (
        not isinstance(run_id, str)
        or Path(run_id).name != run_id
        or not run_id.startswith(f'opencode-{task_code}-')
    ):
        print(f'invalid explicit run id for {task_id}: {run_id!r}', file=sys.stderr)
        return 2
    run_dir = output_root / run_id
    if run_dir.exists():
        print(f'run directory already exists: {run_dir}', file=sys.stderr)
        return 2
    orchestrator = JsonlLog(run_dir / 'orchestrator.jsonl', 'orchestrator')
    agent_log = JsonlLog(run_dir / 'agent.jsonl', 'agent')
    evaluator_log = JsonlLog(run_dir / 'evaluator.jsonl', 'evaluator')
    workspace = task_manifest['workspace']
    orchestrator.emit(
        'run_started', run_id=run_id, domain=domain, task=task_id,
        visual=visual, console_session_id=console.session_id,
    )

    setup = _execute_control_script(
        target, (task / 'setup.ps1').read_text(encoding='utf-8'),
        f'wcb-{run_id}-task-setup.ps1', timeout=90,
    )
    orchestrator.emit('task_setup', exit_code=setup.returncode, stdout=setup.stdout.decode('utf-8', 'replace'), stderr=setup.stderr.decode('utf-8', 'replace'))
    if setup.returncode != 0:
        orchestrator.emit('run_finished', evidence_complete=False, reason='setup failed')
        return 3

    prompt = (task / 'prompt.md').read_text(encoding='utf-8').strip()
    executable = config['opencode']['executable']
    model = config['opencode']['model']
    variant = config['opencode']['variant']
    variant_explicit = config['opencode'].get('variant_explicit', True)
    if type(variant_explicit) is not bool:
        print('opencode.variant_explicit must be boolean', file=sys.stderr)
        return 2
    if not variant_explicit and variant != 'provider-default':
        print('implicit OpenCode variant must be provider-default', file=sys.stderr)
        return 2
    agent = config['opencode']['agent']
    arguments = [
        '--pure', 'run', '--auto', '--agent', agent, '--format', 'json',
        '--dir', workspace, '--model', model,
    ]
    if variant_explicit:
        arguments.extend(('--variant', variant))
    arguments.append(prompt)
    stdout_path = run_dir / 'opencode.stdout.jsonl'
    stderr_path = run_dir / 'opencode.stderr.log'
    auth_stdout_path = run_dir / 'opencode.auth.stdout.log'
    auth_stderr_path = run_dir / 'opencode.auth.stderr.log'
    for path in (stdout_path, stderr_path, auth_stdout_path, auth_stderr_path):
        write_bytes_atomic(path, b'')
    screenshots = None
    process = None
    launcher_identity = None
    staging_attempted = False
    staged = False
    screenshot_finished = False
    auth_collected = False
    agent_output_collected = False
    raw_stdout_bytes = b''
    raw_stderr_bytes = b''
    timed_out = False
    agent_exit = 2

    def collect_auth_best_effort() -> None:
        nonlocal auth_collected
        if auth_collected or not staging_attempted:
            return
        try:
            auth_stdout, auth_stderr = interactive.collect_auth_output(run_id)
            write_bytes_atomic(auth_stdout_path, auth_stdout)
            write_bytes_atomic(auth_stderr_path, auth_stderr)
            auth_collected = True
            orchestrator.emit('auth_output_collected')
        except Exception as error:
            orchestrator.emit('auth_output_collection_failed', reason=str(error))

    def collect_agent_best_effort() -> None:
        nonlocal raw_stdout_bytes, raw_stderr_bytes, agent_output_collected
        if agent_output_collected:
            return
        try:
            raw_stdout_bytes, raw_stderr_bytes = interactive.collect_output(run_id)
            write_bytes_atomic(stdout_path, raw_stdout_bytes)
            write_bytes_atomic(stderr_path, raw_stderr_bytes)
            agent_output_collected = True
        except Exception as error:
            orchestrator.emit('agent_output_collection_failed', reason=str(error))

    try:
        staging_attempted = True
        interactive.stage(
            run_id, executable=executable, arguments=tuple(arguments),
            workspace=workspace, expected_session_id=console.session_id,
            environment={'OPENCODE_CONFIG_CONTENT': _bench_config_content()},
        )
        staged = True
        interactive.start(run_id)
        launcher_identity = interactive.inspect_launcher(run_id, console)
        process = interactive.inspect_process(launcher_identity)
        if process.session_id != console.session_id:
            raise InteractiveAgentError(
                f'OpenCode session {process.session_id} does not match console session {console.session_id}'
            )
        if process.executable.casefold() != executable.casefold():
            raise InteractiveAgentError(f'unexpected interactive executable: {process.executable}')
        command_line_folded = process.command_line.casefold()
        for expected in (workspace, model, agent):
            if expected.casefold() not in command_line_folded:
                raise InteractiveAgentError(f'interactive command line is missing expected value: {expected}')
        if variant_explicit and variant.casefold() not in command_line_folded:
            raise InteractiveAgentError(
                f'interactive command line is missing expected variant: {variant}'
            )
        if not variant_explicit and '--variant' in command_line_folded:
            raise InteractiveAgentError(
                'interactive command line unexpectedly contains --variant'
            )
        interactive.mark_running(process)
        integrity = None
        expected_integrity = config.get('runtime', {}).get('expected_integrity_rid')
        if expected_integrity is not None:
            try:
                expected_integrity = int(expected_integrity)
            except (TypeError, ValueError) as error:
                raise InteractiveAgentError(
                    'runtime.expected_integrity_rid must be an integer'
                ) from error
            integrity = interactive.inspect_integrity(
                (launcher_identity.wrapper_pid, process.pid),
            )
            actual = {
                'wrapper': integrity[launcher_identity.wrapper_pid],
                'agent': integrity[process.pid],
            }
            if any(value != expected_integrity for value in actual.values()):
                raise InteractiveAgentError(
                    f'interactive integrity mismatch: expected {expected_integrity}, '
                    f'got wrapper={actual["wrapper"]}, agent={actual["agent"]}'
                )
        collect_auth_best_effort()
        orchestrator.emit('auth_checked', interactive=True, passed=True)

        process_evidence = {
            'schema': 'wcb.interactive-process/v1',
            'run_id': run_id,
            'task_name': process.task_name,
            'wrapper_pid': process.wrapper_pid,
            'pid': process.pid,
            'parent_pid': process.parent_pid,
            'session_id': process.session_id,
            'console_session_id': console.session_id,
            'explorer_pid': console.explorer_pid,
            'username': process.username,
            'executable': process.executable,
            'command_line': process.command_line,
            'wrapper_integrity_rid': (
                integrity[launcher_identity.wrapper_pid]
                if integrity is not None else None
            ),
            'integrity_rid': (
                integrity[process.pid] if integrity is not None else None
            ),
            'captured_at': utc_now(),
        }
        write_json_atomic(run_dir / 'interactive-process.json', process_evidence)
        agent_log.emit('interactive_process_started', **process_evidence)
        orchestrator.emit(
            'agent_started', model=model, variant=variant,
            variant_explicit=variant_explicit, executable=executable,
            pid=process.pid, session_id=process.session_id, task_name=process.task_name,
            automatic=True, input_channel='none',
        )

        if visual:
            screenshots = ScreenshotMonitor(
                domain, run_dir, orchestrator,
                timeout_seconds=config['runtime']['agent_timeout_seconds'],
                context={
                    'run_id': run_id, 'pid': process.pid,
                    'session_id': process.session_id, 'task_name': process.task_name,
                },
            )
            screenshots.start()

        deadline = time.monotonic() + config['runtime']['agent_timeout_seconds']
        interactive_result = None
        while time.monotonic() < deadline:
            interactive_result = interactive.read_result(launcher_identity)
            if interactive_result is not None:
                break
            time.sleep(1)

        if interactive_result is None:
            timed_out = True
            if screenshots is not None:
                screenshots.finish_agent(timed_out=True)
                screenshot_finished = True
            orchestrator.emit(
                'agent_timeout', timeout_seconds=config['runtime']['agent_timeout_seconds'],
                pid=process.pid, session_id=process.session_id,
            )
            try:
                interactive.terminate(process)
                orchestrator.emit('interactive_termination_attempted', pid=process.pid, succeeded=True)
            except InteractiveAgentError as error:
                orchestrator.emit('interactive_termination_failed', reason=str(error), pid=process.pid)
            collect_agent_best_effort()
            agent_exit = 124
        else:
            timed_out = False
            if screenshots is not None:
                screenshots.finish_agent(timed_out=False)
                screenshot_finished = True
            collect_agent_best_effort()
            agent_exit = int(interactive_result['exit_code'])
    except InteractiveAgentError as error:
        if screenshots is not None and not screenshot_finished:
            screenshots.stop()
        collect_auth_best_effort()
        collect_agent_best_effort()
        orchestrator.emit('interactive_agent_failed', reason=str(error))
        agent_exit = 2
    finally:
        if staging_attempted:
            collect_auth_best_effort()
            try:
                cleanup = interactive.cleanup(
                    run_id, console, launcher_identity, process,
                    preserve_staging=(
                        not staged or not auth_collected or not agent_output_collected
                    ),
                )
                if cleanup.get('cleaned'):
                    orchestrator.emit(
                        'interactive_cleanup_finished',
                        guest_staging_preserved=bool(cleanup.get('staging_preserved')),
                    )
                else:
                    diagnostic = {
                        'schema': 'wcb.interactive-diagnostics/v1',
                        'run_id': run_id,
                        'reason': cleanup.get('reason'),
                        'cleanup': cleanup.get('diagnostic'),
                        'auth_stdout': auth_stdout_path.name,
                        'auth_stderr': auth_stderr_path.name,
                        'guest_staging_preserved': bool(cleanup.get('staging_preserved', True)),
                    }
                    write_json_atomic(run_dir / 'interactive-diagnostics.json', diagnostic)
                    orchestrator.emit(
                        'interactive_cleanup_refused', reason=cleanup.get('reason'),
                        guest_staging_preserved=bool(cleanup.get('staging_preserved', True)),
                    )
            except Exception as error:
                orchestrator.emit('interactive_cleanup_failed', reason=str(error))

    collect_auth_best_effort()

    _record_agent_process(
        run_dir, agent_log,
        stdout=raw_stdout_bytes, stderr=raw_stderr_bytes,
        exit_code=agent_exit, timed_out=timed_out,
        timeout_seconds=config['runtime']['agent_timeout_seconds'],
    )
    orchestrator.emit('agent_finished', exit_code=agent_exit, timed_out=timed_out)

    snapshot_complete = False
    try:
        snapshot = _capture_workspace_snapshot(target, workspace, run_id)
        write_bytes_atomic(run_dir / 'workspace-after-agent.zip', snapshot)
        write_json_atomic(run_dir / 'workspace-snapshot.json', {
            'schema': 'wcb.workspace-snapshot/v1',
            'run_id': run_id,
            'phase': 'after_agent_before_evaluator',
            'workspace': workspace,
            'archive': 'workspace-after-agent.zip',
            'captured_at': utc_now(),
        })
        snapshot_complete = True
        orchestrator.emit(
            'workspace_snapshot_captured',
            archive='workspace-after-agent.zip',
            phase='after_agent_before_evaluator',
        )
    except (InteractiveAgentError, OSError, ValueError) as error:
        orchestrator.emit('workspace_snapshot_failed', reason=str(error))

    if screenshots is not None:
        screenshots.evaluator_before()
    evaluator_script = (task / 'evaluate.ps1').read_text(encoding='utf-8')
    evaluation = _execute_control_script(
        target, evaluator_script, f'wcb-{run_id}-task-evaluate.ps1', timeout=60,
    )
    eval_stdout = evaluation.stdout.decode('utf-8', 'replace').strip()
    try:
        eval_json = json.loads(eval_stdout.splitlines()[0])
    except (json.JSONDecodeError, IndexError):
        eval_json = {'passed': False, 'raw': eval_stdout}
    evaluator_log.emit('evaluation', exit_code=evaluation.returncode, result=eval_json, stderr=evaluation.stderr.decode('utf-8', 'replace'))
    metadata = {
        'schema': 'wcb.run-metadata/v1', 'run_id': run_id, 'task': task_id,
        'evidence_schema': 'wcb.run-evidence/v3',
        'domain': domain, 'base_sha256': 'e159e1d2388c19d74eb32cc479adb50e4b8749b7e3430cf601b175ca1319bab4',
        'model': model, 'variant': variant,
        'variant_explicit': variant_explicit, 'agent_exit': agent_exit,
        'workspace': workspace,
        'workspace_snapshot': 'workspace-after-agent.zip' if snapshot_complete else None,
        'timed_out': timed_out, 'evaluator_exit': evaluation.returncode,
        'finished_at': utc_now(),
    }
    write_json_atomic(run_dir / 'metadata.json', metadata)
    write_json_atomic(run_dir / 'evaluator.json', eval_json)
    orchestrator.emit('run_finished', evidence_complete=snapshot_complete)
    print(json.dumps({
        'run_id': run_id, 'run_dir': str(run_dir),
        'evidence_complete': snapshot_complete, 'agent_exit': agent_exit,
    }))
    return 0 if snapshot_complete else 3
