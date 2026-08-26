from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import yaml

from runner.model_smoke import run as run_model_smoke
from runner.opencode import (
    InteractiveAgentError,
    InteractiveOpenCode,
    SshTarget,
    _execute_control_script,
)
from runner.process_judge import ProcessJudgeError, judge_root
from runner.real_canary import run as run_real_canary
from runner.report import utc_now, write_json_atomic
from runner.scorer import EvidenceError, score_root
from runner.vm import VisualModeError, require_visual_domain, run_libvirt


class MatrixError(RuntimeError):
    pass


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError as error:
        raise MatrixError(f'missing matrix evidence: {path}') from error
    except (OSError, json.JSONDecodeError) as error:
        raise MatrixError(f'invalid matrix evidence {path}: {error}') from error
    if not isinstance(value, dict):
        raise MatrixError(f'invalid matrix evidence {path}: expected object')
    return value


def load_matrix(path: Path) -> dict:
    try:
        value = yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError, yaml.YAMLError) as error:
        raise MatrixError(f'unable to load matrix config {path}: {error}') from error
    if not isinstance(value, dict) or value.get('schema') != 'wcb.matrix/v1':
        raise MatrixError('matrix config must use schema wcb.matrix/v1')
    matrix_id = value.get('id')
    tasks = value.get('tasks')
    models = value.get('models')
    if (
        not isinstance(matrix_id, str)
        or Path(matrix_id).name != matrix_id
        or not matrix_id
    ):
        raise MatrixError('matrix id must be a non-empty path-safe string')
    if not isinstance(tasks, list) or not tasks:
        raise MatrixError('matrix tasks must be a non-empty list')
    if any(
        not isinstance(task, str) or Path(task).name != task or not task
        for task in tasks
    ) or len(set(tasks)) != len(tasks):
        raise MatrixError('matrix tasks must be unique path-safe strings')
    if not isinstance(models, list) or not models:
        raise MatrixError('matrix models must be a non-empty list')
    model_ids = set()
    model_slugs = set()
    normalized_models = []
    for model in models:
        if not isinstance(model, dict):
            raise MatrixError('each matrix model must be an object')
        model_id = model.get('id')
        slug = model.get('model')
        if (
            not isinstance(model_id, str)
            or Path(model_id).name != model_id
            or not model_id
            or model_id in model_ids
        ):
            raise MatrixError('matrix model ids must be unique path-safe strings')
        if not isinstance(slug, str) or not slug or slug in model_slugs:
            raise MatrixError('matrix model slugs must be unique non-empty strings')
        variant = model.get('variant')
        if variant is not None and (not isinstance(variant, str) or not variant):
            raise MatrixError('matrix model variant must be a non-empty string when set')
        model_ids.add(model_id)
        model_slugs.add(slug)
        normalized = {'id': model_id, 'model': slug}
        if variant is not None:
            normalized['variant'] = variant
        normalized_models.append(normalized)
    return {
        'schema': 'wcb.matrix/v1',
        'id': matrix_id,
        'tasks': list(tasks),
        'models': normalized_models,
    }


def _model_config(config: dict, model: dict) -> dict:
    selected = copy.deepcopy(config)
    selected['opencode']['model'] = model['model']
    if 'variant' in model:
        selected['opencode']['variant'] = model['variant']
        selected['opencode']['variant_explicit'] = True
    else:
        selected['opencode']['variant'] = 'provider-default'
        selected['opencode']['variant_explicit'] = False
    return selected


def _definition(matrix: dict, config: dict) -> dict:
    judge = config.get('judge', {})
    return {
        'matrix': matrix,
        'judge': {
            field: judge.get(field)
            for field in ('model', 'variant', 'agent')
        },
    }


def _cell_run_id(task: str, model_id: str) -> str:
    return f'opencode-{task.split("-", 1)[0]}-{model_id}'


def _new_state(matrix: dict, config: dict) -> dict:
    cells = []
    for task in matrix['tasks']:
        for model in matrix['models']:
            selected = _model_config(config, model)['opencode']
            cells.append({
                'run_id': _cell_run_id(task, model['id']),
                'task': task,
                'model_id': model['id'],
                'model': selected['model'],
                'variant': selected['variant'],
                'variant_explicit': selected['variant_explicit'],
                'phase': 'planned',
            })
    smokes = [
        {
            'run_id': f'model-smoke-{model["id"]}',
            'model_id': model['id'],
            'model': model['model'],
            'phase': 'planned',
        }
        for model in matrix['models']
    ]
    return {
        'schema': 'wcb.matrix-state/v1',
        'matrix_id': matrix['id'],
        'definition': _definition(matrix, config),
        'status': 'initialized',
        'created_at': utc_now(),
        'updated_at': utc_now(),
        'smokes': smokes,
        'cells': cells,
        'last_error': None,
    }


def _matrix_report(state: dict, output_root: Path) -> dict:
    rows = []
    for cell in state['cells']:
        score_path = output_root / cell['run_id'] / 'score.json'
        score = _read_json(score_path) if score_path.is_file() else {}
        rows.append({
            **{
                field: cell.get(field)
                for field in (
                    'run_id', 'task', 'model_id', 'model', 'variant',
                    'variant_explicit', 'phase',
                )
            },
            'status': score.get('status'),
            'score': score.get('score'),
            'duration_seconds': score.get('duration_seconds'),
            'tokens': score.get('tokens'),
            'cost': score.get('cost'),
        })
    return {
        'schema': 'wcb.matrix-report/v1',
        'matrix_id': state['matrix_id'],
        'status': state['status'],
        'updated_at': state['updated_at'],
        'cells': rows,
    }


def _write_state(state: dict, output_root: Path) -> None:
    state['updated_at'] = utc_now()
    write_json_atomic(output_root / 'matrix-state.json', state)
    write_json_atomic(
        output_root / 'matrix-report.json',
        _matrix_report(state, output_root),
    )


def _target_and_interactive(
    config: dict, project_root: Path,
) -> tuple[SshTarget, InteractiveOpenCode]:
    guest = config['guest']
    target = SshTarget(
        address=guest['address'],
        user=guest['user'],
        identity=Path(guest['ssh_key']),
        known_hosts=Path(guest['known_hosts']),
    )
    launcher = (project_root / 'config/run-interactive-opencode.ps1').read_text(
        encoding='utf-8',
    )
    interactive = InteractiveOpenCode(
        target, guest.get('interactive_user', guest['user']), launcher,
    )
    return target, interactive


def _attached_overlay(domain: str) -> str:
    state = run_libvirt(['domstate', domain], timeout=10)
    if state.returncode != 0:
        detail = state.stderr.strip() or state.stdout.strip()
        raise MatrixError(f'unable to inspect VM state: {detail}')
    if state.stdout.strip().casefold() != 'running':
        raise MatrixError(f'VM {domain} is not running: {state.stdout.strip()}')
    disks = run_libvirt(['domblklist', '--details', domain], timeout=10)
    if disks.returncode != 0:
        detail = disks.stderr.strip() or disks.stdout.strip()
        raise MatrixError(f'unable to inspect VM disks: {detail}')
    qcow2 = []
    for line in disks.stdout.splitlines():
        fields = line.split(None, 3)
        if (
            len(fields) == 4
            and fields[0] == 'file'
            and fields[1] == 'disk'
            and fields[3].endswith('.qcow2')
        ):
            qcow2.append(fields[3])
    if len(qcow2) != 1:
        raise MatrixError(
            f'expected one attached qcow2 disk for {domain}, found {qcow2}'
        )
    return qcow2[0]


def _residue(target: SshTarget) -> dict:
    script = r"""
$tasks = @(
  Get-ScheduledTask -ErrorAction SilentlyContinue |
    Where-Object TaskName -Like 'WCB-*' |
    ForEach-Object TaskName
)
$processes = @(
  Get-CimInstance Win32_Process | Where-Object {
    $command = [string]$_.CommandLine
    ($_.Name -ieq 'opencode.exe' -and
      $command -match '(?i)--agent\s+(bench|judge)' -and
      $command -match '(?i)C:\\WCB\\') -or
    ($_.Name -in @('pwsh.exe','powershell.exe') -and
      $command -match '(?i)C:\\WCB\\runs\\')
  } | ForEach-Object {
    [ordered]@{ pid=[int]$_.ProcessId; name=[string]$_.Name; command_line=[string]$_.CommandLine }
  }
)
$staging = @()
foreach ($root in @('C:\WCB\runs','C:\WCB\judge-runs','C:\WCB\model-smokes')) {
  if (Test-Path -LiteralPath $root -PathType Container) {
    $staging += @(Get-ChildItem -LiteralPath $root -Directory -Force | ForEach-Object FullName)
  }
}
[ordered]@{
  tasks=@($tasks)
  processes=@($processes)
  staging=@($staging)
} | ConvertTo-Json -Compress -Depth 5
"""
    result = _execute_control_script(
        target, script, 'wcb-matrix-residue.ps1', timeout=30,
    )
    if result.returncode != 0:
        detail = result.stderr.decode('utf-8', 'replace').strip()
        raise MatrixError(f'guest residue probe failed: {detail or result.returncode}')
    try:
        value = json.loads(result.stdout.decode('utf-8', 'replace').strip())
    except json.JSONDecodeError as error:
        raise MatrixError('guest residue probe returned invalid JSON') from error
    if not isinstance(value, dict):
        raise MatrixError('guest residue probe returned an invalid object')
    return value


def require_matrix_preflight(config: dict, project_root: Path) -> dict:
    runtime = config.get('runtime', {})
    domain = runtime.get('visual_domain')
    approved_overlay = runtime.get('approved_overlay')
    expected_integrity = runtime.get('expected_integrity_rid')
    if not isinstance(domain, str) or not domain:
        raise MatrixError('runtime.visual_domain is required')
    if not isinstance(approved_overlay, str) or not approved_overlay:
        raise MatrixError('runtime.approved_overlay is required')
    try:
        expected_integrity = int(expected_integrity)
    except (TypeError, ValueError) as error:
        raise MatrixError('runtime.expected_integrity_rid must be an integer') from error
    try:
        require_visual_domain(domain)
    except VisualModeError as error:
        raise MatrixError(str(error)) from error
    attached = _attached_overlay(domain)
    if attached != approved_overlay:
        raise MatrixError(
            f'VM overlay is not approved: expected {approved_overlay}, got {attached}'
        )
    target, interactive = _target_and_interactive(config, project_root)
    try:
        console = interactive.preflight()
        integrity = interactive.inspect_integrity((console.explorer_pid,))
    except InteractiveAgentError as error:
        raise MatrixError(str(error)) from error
    explorer_integrity = integrity[console.explorer_pid]
    if explorer_integrity != expected_integrity:
        raise MatrixError(
            f'Explorer integrity mismatch: expected {expected_integrity}, '
            f'got {explorer_integrity}'
        )
    residue = _residue(target)
    if any(residue.get(field) for field in ('tasks', 'processes', 'staging')):
        raise MatrixError(f'benchmark residue is present: {residue}')
    return {
        'domain': domain,
        'overlay': attached,
        'console_session_id': console.session_id,
        'console_user': console.username,
        'explorer_integrity_rid': explorer_integrity,
    }


def _validate_agent(
    run_dir: Path, cell: dict,
) -> None:
    metadata = _read_json(run_dir / 'metadata.json')
    expected = {
        'run_id': cell['run_id'],
        'task': cell['task'],
        'model': cell['model'],
        'variant': cell['variant'],
        'variant_explicit': cell['variant_explicit'],
        'evidence_schema': 'wcb.run-evidence/v3',
        'workspace_snapshot': 'workspace-after-agent.zip',
    }
    for field, value in expected.items():
        if metadata.get(field) != value:
            raise MatrixError(
                f'{cell["run_id"]} metadata {field} mismatch: '
                f'expected {value!r}, got {metadata.get(field)!r}'
            )
    if not (run_dir / 'workspace-after-agent.zip').is_file():
        raise MatrixError(f'{cell["run_id"]} workspace snapshot is missing')
    records = [
        json.loads(line)
        for line in (run_dir / 'orchestrator.jsonl').read_text(
            encoding='utf-8-sig',
        ).splitlines()
        if line.strip()
    ]
    finished = [record for record in records if record.get('event') == 'run_finished']
    if len(finished) != 1 or finished[0].get('evidence_complete') is not True:
        raise MatrixError(f'{cell["run_id"]} Agent evidence is incomplete')


def _validate_score(run_dir: Path, cell: dict) -> dict:
    score = _read_json(run_dir / 'score.json')
    if (
        score.get('run_id') != cell['run_id']
        or score.get('task') != cell['task']
        or score.get('model') != cell['model']
        or score.get('variant') != cell['variant']
        or score.get('status') == 'infrastructure_failure'
        or score.get('score') is None
    ):
        raise MatrixError(f'{cell["run_id"]} score is missing or contradictory')
    return score


def _recover_cell(cell: dict, output_root: Path) -> None:
    run_dir = output_root / cell['run_id']
    phase = cell['phase']
    if phase == 'planned':
        if run_dir.exists():
            raise MatrixError(
                f'{cell["run_id"]} exists while its state is still planned'
            )
        return
    if phase == 'agent_running':
        _validate_agent(run_dir, cell)
        cell['phase'] = 'agent_complete'
        phase = cell['phase']
    if phase == 'judging':
        if (run_dir / 'process-judge-error.json').exists():
            raise MatrixError(f'{cell["run_id"]} has a recorded Judge failure')
        cell['phase'] = (
            'judged' if (run_dir / 'process-judge.json').is_file()
            else 'agent_complete'
        )
        phase = cell['phase']
    if phase == 'scoring':
        if (run_dir / 'score.json').is_file():
            _validate_score(run_dir, cell)
            cell['phase'] = 'complete'
        else:
            cell['phase'] = 'judged'
        phase = cell['phase']
    if phase in {'agent_complete', 'judged'}:
        _validate_agent(run_dir, cell)
    elif phase == 'complete':
        _validate_agent(run_dir, cell)
        _validate_score(run_dir, cell)
    elif phase not in {'planned', 'agent_running', 'judging', 'scoring'}:
        raise MatrixError(f'{cell["run_id"]} has unknown phase {phase!r}')


def _run_smokes(
    state: dict,
    matrix: dict,
    config: dict,
    project_root: Path,
    output_root: Path,
) -> None:
    smoke_root = output_root / 'smokes'
    smoke_root.mkdir(exist_ok=True)
    models = {model['id']: model for model in matrix['models']}
    for smoke in state['smokes']:
        report_path = smoke_root / smoke['run_id'] / 'smoke.json'
        if smoke['phase'] == 'passed':
            report = _read_json(report_path)
            if report.get('passed') is not True:
                raise MatrixError(f'{smoke["run_id"]} no longer has a passing report')
            continue
        if smoke['phase'] == 'running':
            if not report_path.is_file():
                raise MatrixError(f'{smoke["run_id"]} was interrupted without a result')
            report = _read_json(report_path)
            if report.get('passed') is not True:
                raise MatrixError(f'{smoke["run_id"]} failed')
            smoke['phase'] = 'passed'
            _write_state(state, output_root)
            continue
        if smoke['phase'] != 'planned':
            raise MatrixError(f'{smoke["run_id"]} has unknown phase {smoke["phase"]!r}')
        if report_path.parent.exists():
            raise MatrixError(f'{smoke["run_id"]} directory already exists')
        selected = _model_config(config, models[smoke['model_id']])
        smoke['phase'] = 'running'
        _write_state(state, output_root)
        result = run_model_smoke(
            selected, project_root, smoke_root, run_id=smoke['run_id'],
        )
        report = _read_json(report_path)
        if result != 0 or report.get('passed') is not True:
            raise MatrixError(f'{smoke["run_id"]} failed: {report.get("errors")}')
        smoke['phase'] = 'passed'
        _write_state(state, output_root)


def _run_cell(
    state: dict,
    cell: dict,
    model: dict,
    config: dict,
    project_root: Path,
    output_root: Path,
) -> None:
    selected = _model_config(config, model)
    selected['task'] = cell['task']
    run_dir = output_root / cell['run_id']
    if cell['phase'] == 'planned':
        gate = require_matrix_preflight(selected, project_root)
        print(json.dumps({'run_id': cell['run_id'], 'preflight': gate}, ensure_ascii=False))
        cell['phase'] = 'agent_running'
        _write_state(state, output_root)
        result = run_real_canary(
            selected, project_root, output_root,
            visual=True, run_id=cell['run_id'],
        )
        if result != 0:
            raise MatrixError(f'{cell["run_id"]} Agent runner exited {result}')
        _validate_agent(run_dir, cell)
        cell['phase'] = 'agent_complete'
        _write_state(state, output_root)
    if cell['phase'] == 'agent_complete':
        require_matrix_preflight(selected, project_root)
        cell['phase'] = 'judging'
        _write_state(state, output_root)
        reports = judge_root(
            selected, project_root, output_root, run_id=cell['run_id'],
        )
        if (
            len(reports) != 1
            or reports[0].get('status') == 'infrastructure_failure'
        ):
            raise MatrixError(f'{cell["run_id"]} Judge failed: {reports}')
        cell['phase'] = 'judged'
        _write_state(state, output_root)
    if cell['phase'] == 'judged':
        cell['phase'] = 'scoring'
        _write_state(state, output_root)
        reports = score_root(
            output_root, project_root, run_id=cell['run_id'],
        )
        if len(reports) != 1:
            raise MatrixError(f'{cell["run_id"]} scorer returned {len(reports)} reports')
        score = reports[0]
        if score.get('status') == 'infrastructure_failure' or score.get('score') is None:
            raise MatrixError(f'{cell["run_id"]} scoring failed: {score}')
        _validate_score(run_dir, cell)
        cell['phase'] = 'complete'
        _write_state(state, output_root)
        require_matrix_preflight(selected, project_root)


def run(
    config: dict,
    project_root: Path,
    matrix_path: Path,
    output_root: Path,
    *,
    visual: bool,
    resume: bool,
    dry_run: bool,
) -> int:
    try:
        matrix = load_matrix(matrix_path)
        definition = _definition(matrix, config)
        if dry_run:
            cells = _new_state(matrix, config)['cells']
            print(json.dumps({
                'matrix_id': matrix['id'],
                'cell_count': len(cells),
                'cells': cells,
            }, ensure_ascii=False, indent=2))
            return 0
        if not visual:
            raise MatrixError('matrix execution requires --visual')
        state_path = output_root / 'matrix-state.json'
        if resume:
            state = _read_json(state_path)
            if (
                state.get('schema') != 'wcb.matrix-state/v1'
                or state.get('definition') != definition
            ):
                raise MatrixError('matrix state does not match the requested definition')
            for cell in state.get('cells', []):
                _recover_cell(cell, output_root)
        else:
            if output_root.exists():
                raise MatrixError(f'fresh matrix output already exists: {output_root}')
            output_root.mkdir(parents=True)
            state = _new_state(matrix, config)
            _write_state(state, output_root)

        state['status'] = 'smoke'
        state['last_error'] = None
        _write_state(state, output_root)
        _run_smokes(state, matrix, config, project_root, output_root)

        state['status'] = 'running'
        _write_state(state, output_root)
        models = {model['id']: model for model in matrix['models']}
        for cell in state['cells']:
            _recover_cell(cell, output_root)
            if cell['phase'] == 'complete':
                continue
            _run_cell(
                state, cell, models[cell['model_id']], config,
                project_root, output_root,
            )

        reports = score_root(output_root, project_root)
        if len(reports) != len(state['cells']) or any(
            report.get('status') == 'infrastructure_failure'
            or report.get('score') is None
            for report in reports
        ):
            raise MatrixError('final score report is incomplete or contains infrastructure failure')
        state['status'] = 'completed'
        state['last_error'] = None
        _write_state(state, output_root)
        return 0
    except (
        EvidenceError,
        InteractiveAgentError,
        KeyError,
        MatrixError,
        OSError,
        ProcessJudgeError,
        TypeError,
        ValueError,
    ) as error:
        if output_root.is_dir() and (output_root / 'matrix-state.json').is_file():
            try:
                state = _read_json(output_root / 'matrix-state.json')
                state['status'] = 'stopped'
                state['last_error'] = str(error)
                _write_state(state, output_root)
            except BaseException:
                pass
        print(f'Matrix stopped: {error}', file=sys.stderr)
        return 2
