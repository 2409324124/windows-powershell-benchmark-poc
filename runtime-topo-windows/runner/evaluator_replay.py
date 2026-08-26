from __future__ import annotations

import json
from pathlib import Path

from runner.opencode import SshTarget, _execute_control_script
from runner.real_canary import load_task
from runner.report import utc_now, write_json_atomic


class EvaluatorReplayError(RuntimeError):
    pass


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, json.JSONDecodeError) as error:
        raise EvaluatorReplayError(f'invalid {path.name}: {error}') from error
    if not isinstance(value, dict):
        raise EvaluatorReplayError(f'invalid {path.name}: expected object')
    return value


def _parse_result(stdout: bytes) -> dict:
    for line in stdout.decode('utf-8', 'replace').splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and type(value.get('passed')) is bool:
            return value
    raise EvaluatorReplayError('evaluator replay returned no structured result')


def replay_run(
    config: dict,
    project_root: Path,
    output_root: Path,
    run_id: str,
) -> dict:
    if (
        not isinstance(run_id, str)
        or Path(run_id).name != run_id
        or not run_id.startswith('opencode-')
    ):
        raise EvaluatorReplayError(f'invalid run id: {run_id!r}')
    run_dir = output_root / run_id
    if not run_dir.is_dir():
        raise EvaluatorReplayError(f'run id does not exist: {run_id}')
    replay_path = run_dir / 'evaluator-replay.json'
    if replay_path.exists():
        replay = _read_json(replay_path)
        if replay.get('run_id') != run_id:
            raise EvaluatorReplayError('existing evaluator replay has wrong run id')
        return replay

    metadata = _read_json(run_dir / 'metadata.json')
    task_id = metadata.get('task')
    if metadata.get('run_id') != run_id or not isinstance(task_id, str):
        raise EvaluatorReplayError('metadata identity is invalid')
    task_root, manifest = load_task(project_root, task_id)
    snapshot = _read_json(run_dir / 'workspace-snapshot.json')
    if (
        snapshot.get('run_id') != run_id
        or snapshot.get('phase') != 'after_agent_before_evaluator'
        or snapshot.get('archive') != 'workspace-after-agent.zip'
        or snapshot.get('workspace') != manifest['workspace']
    ):
        raise EvaluatorReplayError('workspace snapshot identity is invalid')
    archive = (run_dir / 'workspace-after-agent.zip').read_bytes()
    if not archive:
        raise EvaluatorReplayError('workspace snapshot archive is empty')

    guest = config['guest']
    target = SshTarget(
        address=guest['address'],
        user=guest['user'],
        identity=Path(guest['ssh_key']),
        known_hosts=Path(guest['known_hosts']),
    )
    remote_archive = f'wcb-{run_id}-evaluator-replay.zip'
    uploaded = target.upload_bytes(archive, remote_archive, timeout=120)
    if uploaded.returncode != 0:
        detail = uploaded.stderr.decode('utf-8', 'replace').strip()
        raise EvaluatorReplayError(
            f'evaluator snapshot upload failed: {detail or uploaded.returncode}'
        )
    replay_root = rf'C:\WCB\evaluator-replays\{run_id}'
    workspace = replay_root + r'\workspace'
    stage_script = rf"""
$root = '{replay_root}'
$workspace = '{workspace}'
$archive = Join-Path $env:USERPROFILE '{remote_archive}'
Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $workspace -Force | Out-Null
try {{
    Expand-Archive -LiteralPath $archive -DestinationPath $workspace -Force
}} finally {{
    Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
}}
"""
    staged = _execute_control_script(
        target, stage_script, f'wcb-{run_id}-evaluator-replay-stage.ps1',
        timeout=120,
    )
    if staged.returncode != 0:
        detail = staged.stderr.decode('utf-8', 'replace').strip()
        raise EvaluatorReplayError(
            f'evaluator snapshot staging failed: {detail or staged.returncode}'
        )

    evaluation = None
    cleanup_error = None
    try:
        evaluator_script = (
            f"$env:WCB_EVALUATOR_ROOT='{workspace}'\n"
            + (task_root / 'evaluate.ps1').read_text(encoding='utf-8')
        )
        evaluation = _execute_control_script(
            target, evaluator_script,
            f'wcb-{run_id}-evaluator-replay-run.ps1', timeout=90,
        )
    finally:
        cleanup = _execute_control_script(
            target,
            rf"Remove-Item -LiteralPath '{replay_root}' -Recurse -Force -ErrorAction SilentlyContinue",
            f'wcb-{run_id}-evaluator-replay-cleanup.ps1', timeout=60,
        )
        if cleanup.returncode != 0:
            cleanup_error = cleanup.stderr.decode('utf-8', 'replace').strip()
    if cleanup_error is not None:
        raise EvaluatorReplayError(
            f'evaluator replay cleanup failed: {cleanup_error or cleanup.returncode}'
        )
    if evaluation is None:
        raise EvaluatorReplayError('evaluator replay did not start')
    result = _parse_result(evaluation.stdout)
    if (evaluation.returncode == 0) != result['passed']:
        raise EvaluatorReplayError('evaluator replay exit contradicts passed flag')
    replay = {
        'schema': 'wcb.evaluator-replay/v1',
        'run_id': run_id,
        'task': task_id,
        'workspace_snapshot': 'workspace-after-agent.zip',
        'evaluator': f'tasks/{task_id}/evaluate.ps1',
        'exit_code': evaluation.returncode,
        'result': result,
        'stderr': evaluation.stderr.decode('utf-8', 'replace'),
        'captured_at': utc_now(),
    }
    write_json_atomic(replay_path, replay)
    return replay
