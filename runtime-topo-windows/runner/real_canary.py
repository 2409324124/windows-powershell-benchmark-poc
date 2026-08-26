from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

from runner.opencode import SshTarget, encoded_powershell
from runner.report import JsonlLog, utc_now, write_json_atomic
from runner.vm import ScreenshotMonitor


def _partial_bytes(value: bytes | str | None) -> bytes:
    if value is None:
        return b''
    if isinstance(value, bytes):
        return value
    return value.encode('utf-8', 'replace')


def run(config: dict, project_root: Path, output_root: Path, *, visual: bool = False) -> int:
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
    domain = 'wcb-canary-transport-001'
    orchestrator.emit('run_started', run_id=run_id, domain=domain, task='ps002-path-quoting', visual=visual)

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
    stdout_path = run_dir / 'opencode.stdout.jsonl'
    stderr_path = run_dir / 'opencode.stderr.log'
    stdout_path.write_bytes(b'')
    stderr_path.write_bytes(b'')
    screenshots = None
    if visual:
        screenshots = ScreenshotMonitor(
            domain, run_dir, orchestrator,
            timeout_seconds=config['runtime']['agent_timeout_seconds'],
        )
        screenshots.start()
    timeout_observed = False

    def observe_timeout(error: subprocess.TimeoutExpired) -> None:
        nonlocal timeout_observed
        if timeout_observed:
            return
        timeout_observed = True
        if screenshots is not None:
            screenshots.finish_agent(timed_out=True)
        stdout_path.write_bytes(_partial_bytes(error.stdout))
        stderr_path.write_bytes(_partial_bytes(error.stderr))
        orchestrator.emit('agent_timeout', timeout_seconds=config['runtime']['agent_timeout_seconds'])

    try:
        result = target.run(
            encoded_powershell(ps),
            timeout=config['runtime']['agent_timeout_seconds'],
            on_timeout=observe_timeout,
        )
        timed_out = False
        raw_stdout_bytes = result.stdout
        raw_stderr_bytes = result.stderr
        if screenshots is not None:
            screenshots.finish_agent(timed_out=False)
    except subprocess.TimeoutExpired as error:
        timed_out = True
        result = None
        # SshTarget calls this before killing the timed-out SSH process. Keep the
        # fallback for test doubles and alternate targets.
        observe_timeout(error)
        raw_stdout_bytes = _partial_bytes(error.stdout)
        raw_stderr_bytes = _partial_bytes(error.stderr)

    stdout_path.write_bytes(raw_stdout_bytes)
    stderr_path.write_bytes(raw_stderr_bytes)
    if result is not None:
        raw_stdout = raw_stdout_bytes.decode('utf-8', 'replace')
        raw_stderr = raw_stderr_bytes.decode('utf-8', 'replace')
        for line in raw_stdout.splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                payload = {'raw': line}
            agent_log.emit('opencode_event', payload=payload)
        agent_log.emit('process_exit', exit_code=result.returncode, stderr=raw_stderr)
        agent_exit = result.returncode
    else:
        raw_stdout = raw_stdout_bytes.decode('utf-8', 'replace')
        for line in raw_stdout.splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                payload = {'raw': line}
            agent_log.emit('opencode_event', payload=payload)
        agent_log.emit('process_timeout', timeout_seconds=config['runtime']['agent_timeout_seconds'])
        agent_exit = 124
    orchestrator.emit('agent_finished', exit_code=agent_exit, timed_out=timed_out)

    if screenshots is not None:
        screenshots.evaluator_before()
    evaluator_script = (task / 'evaluate.ps1').read_text(encoding='utf-8')
    evaluation = target.run(encoded_powershell(evaluator_script), timeout=60)
    eval_stdout = evaluation.stdout.decode('utf-8', 'replace').strip()
    try:
        eval_json = json.loads(eval_stdout.splitlines()[0])
    except (json.JSONDecodeError, IndexError):
        eval_json = {'passed': False, 'raw': eval_stdout}
    passed = evaluation.returncode == 0 and bool(eval_json.get('passed'))
    evaluator_log.emit('evaluation', exit_code=evaluation.returncode, result=eval_json, stderr=evaluation.stderr.decode('utf-8', 'replace'))
    metadata = {
        'schema': 'wcb.run-metadata/v1', 'run_id': run_id, 'task': 'ps002-path-quoting',
        'domain': domain, 'base_sha256': 'e159e1d2388c19d74eb32cc479adb50e4b8749b7e3430cf601b175ca1319bab4',
        'model': model, 'variant': variant, 'agent_exit': agent_exit, 'passed': passed,
        'finished_at': utc_now(),
    }
    write_json_atomic(run_dir / 'metadata.json', metadata)
    write_json_atomic(run_dir / 'evaluator.json', eval_json)
    write_json_atomic(run_dir / 'score.json', {'passed': passed, 'score': 1 if passed else 0})
    orchestrator.emit('run_finished', passed=passed)
    print(json.dumps({'run_id': run_id, 'run_dir': str(run_dir), 'passed': passed, 'agent_exit': agent_exit}))
    return 0 if passed else 1
