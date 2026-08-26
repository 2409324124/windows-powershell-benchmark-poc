from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

from runner.opencode import SshTarget, encoded_powershell
from runner.report import JsonlLog, utc_now, write_bytes_atomic, write_json_atomic


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

    for line in raw_stdout.decode('utf-8', 'replace').splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            payload = {'raw': line}
        agent_log.emit('opencode_event', payload=payload)

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
    try:
        result = target.run(command, timeout=timeout_seconds)
        return result.stdout, result.stderr, result.returncode, False
    except subprocess.TimeoutExpired as error:
        return error.stdout, error.stderr, 124, True


def _run_passed(
    *,
    agent_exit: int,
    timed_out: bool,
    evaluator_exit: int,
    evaluator_result: dict,
) -> tuple[bool, bool, bool]:
    lifecycle_pass = agent_exit == 0 and not timed_out
    evaluator_pass = evaluator_exit == 0 and bool(evaluator_result.get('passed'))
    return lifecycle_pass and evaluator_pass, lifecycle_pass, evaluator_pass


def run(config: dict, project_root: Path, output_root: Path) -> int:
    run_id = 'opencode-ps002-' + uuid.uuid4().hex[:8]
    run_dir = output_root / run_id
    orchestrator = JsonlLog(run_dir / 'orchestrator.jsonl', 'orchestrator')
    agent_log = JsonlLog(run_dir / 'agent.jsonl', 'agent')
    evaluator_log = JsonlLog(run_dir / 'evaluator.jsonl', 'evaluator')
    guest = config['guest']
    target = SshTarget(
        address=guest['address'], user=guest['user'],
        identity=Path(guest['ssh_key']), known_hosts=Path(guest['known_hosts']),
    )
    task = project_root / 'tasks/ps002-path-quoting'
    workspace = r'C:\WCB\tasks\PS002 Project (quoted)'
    orchestrator.emit('run_started', run_id=run_id, domain='wcb-canary-transport-001', task='ps002-path-quoting')

    auth = target.run(r'"C:\Program Files\OpenCode\1.18.21\opencode.exe" auth list', timeout=30)
    orchestrator.emit('auth_checked', exit_code=auth.returncode, stdout=auth.stdout.decode('utf-8', 'replace'), stderr=auth.stderr.decode('utf-8', 'replace'))
    if auth.returncode != 0 or b'0 credentials' in auth.stdout.lower():
        orchestrator.emit('run_finished', passed=False, reason='no OpenCode credential found')
        return 2

    setup = target.run(encoded_powershell((task / 'setup.ps1').read_text(encoding='utf-8')), timeout=90)
    orchestrator.emit('task_setup', exit_code=setup.returncode, stdout=setup.stdout.decode('utf-8', 'replace'), stderr=setup.stderr.decode('utf-8', 'replace'))
    if setup.returncode != 0:
        orchestrator.emit('run_finished', passed=False, reason='setup failed')
        return 3

    prompt = (task / 'prompt.md').read_text(encoding='utf-8').strip()
    executable = config['opencode']['executable']
    model = config['opencode']['model']
    variant = config['opencode']['variant']
    agent = config['opencode']['agent']
    ps = f"""
$ErrorActionPreference = 'Stop'
$env:Path = '{workspace}\\Shadow;' + $env:Path
$arguments = @('--pure','run','--auto','--agent','{agent}','--format','json','--dir','{workspace}','--model','{model}','--variant','{variant}',@'
{prompt}
'@)
& '{executable}' @arguments
exit $LASTEXITCODE
"""
    orchestrator.emit('agent_started', model=model, variant=variant, executable=executable)
    timeout_seconds = config['runtime']['agent_timeout_seconds']
    raw_stdout, raw_stderr, agent_exit, timed_out = _run_agent(
        target,
        encoded_powershell(ps),
        timeout_seconds,
    )

    _record_agent_process(
        run_dir,
        agent_log,
        stdout=raw_stdout,
        stderr=raw_stderr,
        exit_code=agent_exit,
        timed_out=timed_out,
        timeout_seconds=timeout_seconds,
    )
    orchestrator.emit('agent_finished', exit_code=agent_exit, timed_out=timed_out)

    evaluator_script = (task / 'evaluate.ps1').read_text(encoding='utf-8')
    evaluation = target.run(encoded_powershell(evaluator_script), timeout=60)
    eval_stdout = evaluation.stdout.decode('utf-8', 'replace').strip()
    try:
        eval_json = json.loads(eval_stdout.splitlines()[0])
    except (json.JSONDecodeError, IndexError):
        eval_json = {'passed': False, 'raw': eval_stdout}
    passed, lifecycle_pass, evaluator_pass = _run_passed(
        agent_exit=agent_exit,
        timed_out=timed_out,
        evaluator_exit=evaluation.returncode,
        evaluator_result=eval_json,
    )
    evaluator_log.emit('evaluation', exit_code=evaluation.returncode, result=eval_json, stderr=evaluation.stderr.decode('utf-8', 'replace'))
    metadata = {
        'schema': 'wcb.run-metadata/v1', 'run_id': run_id, 'task': 'ps002-path-quoting',
        'domain': 'wcb-canary-transport-001', 'base_sha256': 'e159e1d2388c19d74eb32cc479adb50e4b8749b7e3430cf601b175ca1319bab4',
        'model': model, 'variant': variant, 'agent_exit': agent_exit, 'timed_out': timed_out,
        'lifecycle_pass': lifecycle_pass, 'evaluator_pass': evaluator_pass, 'passed': passed,
        'finished_at': utc_now(),
    }
    write_json_atomic(run_dir / 'metadata.json', metadata)
    write_json_atomic(run_dir / 'evaluator.json', eval_json)
    write_json_atomic(run_dir / 'score.json', {'passed': passed, 'score': 1 if passed else 0})
    orchestrator.emit('run_finished', passed=passed, lifecycle_pass=lifecycle_pass, evaluator_pass=evaluator_pass)
    print(json.dumps({'run_id': run_id, 'run_dir': str(run_dir), 'passed': passed, 'agent_exit': agent_exit}))
    return 0 if passed else 1
