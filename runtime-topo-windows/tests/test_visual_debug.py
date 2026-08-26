from __future__ import annotations

import json
import io
import base64
import subprocess
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from runner.opencode import (
    ConsoleSession,
    InteractiveAgentError,
    InteractiveOpenCode,
    InteractiveProcess,
    LauncherIdentity,
    SshTarget,
    _control_powershell,
    encoded_powershell,
)
from runner.real_canary import run
from runner.report import JsonlLog, write_bytes_atomic
from runner.vm import ScreenshotMonitor, VisualModeError, require_visual_domain


ROOT = Path(__file__).resolve().parents[1]


class VisualDomainTests(unittest.TestCase):
    def test_visual_domain_is_local_and_has_no_sharing_devices(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'domain.xml'
            subprocess.run([
                sys.executable, str(ROOT / 'scripts/instantiate-domain.py'),
                '--template', str(ROOT / 'config/ws2025-domain-template.xml'),
                '--output', str(output), '--name', 'test',
                '--uuid', '11111111-1111-1111-1111-111111111111',
                '--overlay', '/tmp/test.qcow2', '--nvram', '/tmp/test.fd',
                '--mac', '52:54:00:00:00:01', '--visual',
            ], check=True)
            root = ET.parse(output).getroot()
            graphics = root.find('./devices/graphics')
            self.assertEqual(graphics.attrib, {
                'type': 'spice', 'autoport': 'yes', 'listen': '127.0.0.1',
            })
            self.assertEqual(graphics.find('clipboard').get('copypaste'), 'no')
            self.assertEqual(graphics.find('filetransfer').get('enable'), 'no')
            self.assertEqual(root.find('./devices/video/model').get('type'), 'qxl')
            self.assertIsNotNone(root.find("./devices/input[@type='keyboard']"))
            self.assertIsNotNone(root.find("./devices/input[@type='mouse']"))
            self.assertIsNone(root.find('./devices/filesystem'))
            self.assertIsNone(root.find('./devices/redirdev'))
            spice_channels = [
                channel for channel in root.findall('./devices/channel')
                if channel.find('target') is not None
                and channel.find('target').get('name', '').startswith('com.redhat.spice')
            ]
            self.assertEqual(spice_channels, [])

    def test_default_domain_remains_headless(self) -> None:
        template = ET.parse(ROOT / 'config/ws2025-domain-template.xml').getroot()
        self.assertIsNone(template.find('./devices/graphics'))
        self.assertIsNone(template.find('./devices/video'))


class ScreenshotMonitorTests(unittest.TestCase):
    def test_periodic_and_exit_screenshots_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            log = JsonlLog(run_dir / 'orchestrator.jsonl', 'orchestrator')

            def screenshot(arguments: list[str], *, timeout: int = 60):
                Path(arguments[-1]).write_bytes(b'png')
                return subprocess.CompletedProcess(arguments, 0, '', '')

            monitor = ScreenshotMonitor(
                'domain', run_dir, log, timeout_seconds=300,
                context={'run_id': 'run-123', 'pid': 701, 'session_id': 1},
                schedule=((0.01, '030.png'), (0.02, '060.png')),
            )
            with patch('runner.vm.run_libvirt', side_effect=screenshot):
                monitor.start()
                time.sleep(0.04)
                monitor.finish_agent(timed_out=False)
            names = {path.name for path in (run_dir / 'screenshots').glob('*.png')}
            self.assertIn('000-agent-start.png', names)
            self.assertIn('030.png', names)
            self.assertIn('060.png', names)
            self.assertTrue(any(name.endswith('-agent-exit.png') for name in names))
            records = [json.loads(line) for line in (run_dir / 'orchestrator.jsonl').read_text().splitlines()]
            self.assertTrue(records)
            self.assertTrue(all(record['run_id'] == 'run-123' for record in records))
            self.assertTrue(all(record['pid'] == 701 for record in records))
            self.assertTrue(all(record['session_id'] == 1 for record in records))

    def test_failure_is_logged_and_nonfatal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            log = JsonlLog(run_dir / 'orchestrator.jsonl', 'orchestrator')
            failure = subprocess.CompletedProcess([], 1, '', 'no framebuffer')
            monitor = ScreenshotMonitor('domain', run_dir, log, timeout_seconds=300)
            with patch('runner.vm.run_libvirt', return_value=failure):
                self.assertFalse(monitor.capture('000-agent-start.png'))
            record = json.loads((run_dir / 'orchestrator.jsonl').read_text())
            self.assertEqual(record['event'], 'screenshot_failed')
            self.assertEqual(record['reason'], 'no framebuffer')


class VisualPreflightTests(unittest.TestCase):
    def test_accepts_spice_graphics_and_video(self) -> None:
        xml = (
            "<domain><devices><graphics type='spice'>"
            "<clipboard copypaste='no'/><filetransfer enable='no'/>"
            "</graphics><video/></devices></domain>"
        )
        result = subprocess.CompletedProcess([], 0, xml, '')
        with patch('runner.vm.run_libvirt', return_value=result):
            require_visual_domain('visual-domain')

    def test_rejects_headless_domain_with_actionable_message(self) -> None:
        result = subprocess.CompletedProcess([], 0, '<domain><devices/></domain>', '')
        with patch('runner.vm.run_libvirt', return_value=result):
            with self.assertRaisesRegex(VisualModeError, 'Instantiate/start the domain with --visual first'):
                require_visual_domain('headless-domain')

    def test_rejects_domain_lookup_failure(self) -> None:
        result = subprocess.CompletedProcess([], 1, '', 'domain not found')
        with patch('runner.vm.run_libvirt', return_value=result):
            with self.assertRaisesRegex(VisualModeError, 'domain not found'):
                require_visual_domain('missing-domain')

    def test_rejects_spice_sharing_policy_violation(self) -> None:
        xml = (
            "<domain><devices><graphics type='spice'>"
            "<clipboard copypaste='yes'/><filetransfer enable='no'/>"
            "</graphics><video/></devices></domain>"
        )
        result = subprocess.CompletedProcess([], 0, xml, '')
        with patch('runner.vm.run_libvirt', return_value=result):
            with self.assertRaisesRegex(VisualModeError, 'restricted SPICE policy'):
                require_visual_domain('unsafe-domain')

    def test_canary_stops_before_creating_artifacts_when_preflight_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            message = VisualModeError(
                'Visual mode requested, but domain wcb-canary-transport-001\n'
                'has no graphical framebuffer.\n\n'
                'Instantiate/start the domain with --visual first.'
            )
            stderr = io.StringIO()
            with patch('runner.real_canary.require_visual_domain', side_effect=message), \
                    redirect_stderr(stderr):
                self.assertEqual(run({}, ROOT, output, visual=True), 2)
            self.assertEqual(list(output.iterdir()), [])
            self.assertIn('has no graphical framebuffer', stderr.getvalue())


def decode_encoded_powershell(command: str) -> str:
    payload = command.rsplit(' ', 1)[-1]
    return base64.b64decode(payload).decode('utf-16-le')


def decode_uploaded_control(target) -> str:
    return target.upload_bytes.call_args.args[0].decode('utf-8-sig')


class InteractiveOpenCodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.target = Mock()
        self.target.upload_bytes.return_value = subprocess.CompletedProcess([], 0, b'', b'')
        self.launcher = InteractiveOpenCode(self.target, 'Administrator', '# launcher')

    def test_preflight_returns_unlocked_matching_console_session(self) -> None:
        payload = {
            'username': r'WIN\Administrator', 'matching_shell_count': 1,
            'explorer_pid': 412, 'session_id': 1, 'locked': False,
        }
        self.target.run.return_value = subprocess.CompletedProcess(
            [], 0, json.dumps(payload).encode(), b'',
        )
        self.assertEqual(
            self.launcher.preflight(),
            ConsoleSession(r'WIN\Administrator', 1, 412),
        )

    def test_preflight_rejects_locked_console(self) -> None:
        payload = {
            'username': r'WIN\Administrator', 'matching_shell_count': 1,
            'explorer_pid': 412, 'session_id': 1, 'locked': True,
        }
        self.target.run.return_value = subprocess.CompletedProcess(
            [], 0, json.dumps(payload).encode(), b'',
        )
        with self.assertRaisesRegex(InteractiveAgentError, 'unlocked console session'):
            self.launcher.preflight()

    def test_preflight_uses_active_console_and_ignores_other_sessions(self) -> None:
        payload = {
            'username': r'WIN\Administrator', 'matching_shell_count': 2,
            'explorer_pid': 412, 'session_id': 3, 'locked': False,
        }
        self.target.run.return_value = subprocess.CompletedProcess(
            [], 0, json.dumps(payload).encode(), b'',
        )
        session = self.launcher.preflight()
        self.assertEqual(session.session_id, 3)
        script = decode_encoded_powershell(self.target.run.call_args.args[0])
        self.assertTrue(script.startswith(
            "$ErrorActionPreference = 'Stop'\nSet-StrictMode -Version Latest\n",
        ))
        self.assertIn('WTSGetActiveConsoleSessionId', script)
        self.assertIn('Where-Object SessionId -eq $sessionId', script)

    def test_preflight_rejects_no_matching_shell_in_active_console(self) -> None:
        payload = {
            'username': '', 'matching_shell_count': 0,
            'explorer_pid': 0, 'session_id': 1, 'locked': False,
        }
        self.target.run.return_value = subprocess.CompletedProcess(
            [], 0, json.dumps(payload).encode(), b'',
        )
        with self.assertRaisesRegex(InteractiveAgentError, 'no Explorer shell'):
            self.launcher.preflight()

    def test_preflight_rejects_when_no_active_console_exists(self) -> None:
        payload = {
            'username': '', 'matching_shell_count': 0,
            'explorer_pid': 0, 'session_id': -1, 'locked': False,
        }
        self.target.run.return_value = subprocess.CompletedProcess(
            [], 0, json.dumps(payload).encode(), b'',
        )
        with self.assertRaisesRegex(InteractiveAgentError, 'active Windows console'):
            self.launcher.preflight()

    def test_start_uses_interactive_token_scheduled_task(self) -> None:
        self.target.run.return_value = subprocess.CompletedProcess([], 0, b'', b'')
        self.launcher.start('run-123')
        script = decode_encoded_powershell(self.target.run.call_args.args[0])
        self.assertTrue(script.startswith("$ErrorActionPreference = 'Stop'\nSet-StrictMode -Version Latest\n"))
        self.assertIn("-TaskName 'WCB-run-123'", script)
        self.assertIn('-LogonType Interactive', script)
        self.assertIn('-RunLevel Limited', script)
        self.assertNotIn('Highest', script)
        self.assertIn(r"-Execute 'C:\Program Files\PowerShell\7\pwsh.exe'", script)
        self.assertIn(r'C:\WCB\runs\run-123\launch.ps1', script)

    def test_large_stage_script_uses_short_command_and_complete_upload(self) -> None:
        target = Mock()
        target.upload_bytes.return_value = subprocess.CompletedProcess([], 0, b'', b'')
        target.run.return_value = subprocess.CompletedProcess([], 0, b'', b'')
        launcher_source = "Write-Output 'launcher'\n" * 1000
        launcher = InteractiveOpenCode(target, 'Administrator', launcher_source)

        launcher.stage(
            'run-large', executable=r'C:\OpenCode\opencode.exe',
            arguments=('--model', 'test/model'), workspace=r'C:\WCB\workspace',
            expected_session_id=1,
        )

        call = target.run.call_args
        command = call.args[0]
        script = decode_uploaded_control(target)
        self.assertLess(len(command), 2048)
        self.assertGreater(len(script), 8191)
        self.assertIn("Set-StrictMode -Version Latest", script)
        self.assertIn("Join-Path $root 'launch.ps1'", script)
        self.assertNotIn(launcher_source, command)
        self.assertNotIn('stdin', call.kwargs)

    def test_inspect_process_captures_exact_child_identity(self) -> None:
        payload = {
            'run_id': 'run-123', 'phase': 'agent_starting',
            'wrapper_pid': 700, 'child_count': 1,
            'pid': 701, 'parent_pid': 700, 'session_id': 1,
            'executable': r'C:\OpenCode\opencode.exe',
            'command_line': r'opencode.exe --dir C:\WCB\task --model test/model',
            'username': r'WIN\Administrator',
            'finished': False,
        }
        self.target.run.return_value = subprocess.CompletedProcess(
            [], 0, json.dumps(payload).encode(), b'',
        )
        launcher = LauncherIdentity(
            'run-123', 'WCB-run-123', 700, 1, r'WIN\Administrator',
            r'C:\Program Files\PowerShell\7\pwsh.exe', 'pwsh launch.ps1',
            r'C:\WCB\runs\run-123\launch.ps1', r'C:\WCB\runs\run-123\request.json',
        )
        process = self.launcher.inspect_process(launcher, timeout=1)
        self.assertEqual(process.pid, 701)
        self.assertEqual(process.parent_pid, process.wrapper_pid)
        self.assertEqual(process.session_id, 1)
        self.assertEqual(process.run_id, 'run-123')
        self.assertEqual(process.task_name, 'WCB-run-123')

    def test_terminate_revalidates_identity_before_tree_kill(self) -> None:
        self.target.run.return_value = subprocess.CompletedProcess([], 0, b'', b'')
        process = InteractiveProcess(
            'run-123', 'WCB-run-123', 700, 701, 1, 700,
            r'C:\OpenCode\opencode.exe', 'opencode.exe --model test/model',
            r'WIN\Administrator',
        )
        self.launcher.terminate(process)
        script = decode_encoded_powershell(self.target.run.call_args.args[0])
        self.assertIn('ParentProcessId -ne 700', script)
        self.assertIn('SessionId -ne 1', script)
        self.assertIn(r"ExecutablePath -ne 'C:\OpenCode\opencode.exe'", script)
        self.assertIn('& taskkill.exe /PID 701 /T /F', script)

    def test_result_identity_mismatch_is_rejected(self) -> None:
        launcher = LauncherIdentity(
            'run-123', 'WCB-run-123', 700, 1, r'WIN\Administrator',
            'pwsh.exe', 'pwsh launch.ps1',
            r'C:\WCB\runs\run-123\launch.ps1', r'C:\WCB\runs\run-123\request.json',
        )
        base = {
            'run_id': 'run-123', 'wrapper_pid': 700, 'session_id': 1,
            'username': r'WIN\Administrator', 'phase': 'finished', 'exit_code': 0,
        }
        cases = {
            'run_id': 'stale-run', 'wrapper_pid': 999, 'session_id': 2,
            'username': r'WIN\OtherUser',
        }
        for field, bad_value in cases.items():
            with self.subTest(field=field):
                payload = {**base, field: bad_value}
                self.target.run.return_value = subprocess.CompletedProcess(
                    [], 0, json.dumps(payload).encode(), b'',
                )
                with self.assertRaisesRegex(InteractiveAgentError, 'does not match'):
                    self.launcher.read_result(launcher)

    def test_cleanup_validates_task_action_absolute_paths(self) -> None:
        self.target.run.return_value = subprocess.CompletedProcess(
            [], 0, b'{"cleaned":false,"reason":"path mismatch","diagnostic":{}}', b'',
        )
        result = self.launcher.cleanup(
            'run-123', ConsoleSession(r'WIN\Administrator', 1, 412), None, None,
        )
        self.assertFalse(result['cleaned'])
        script = decode_uploaded_control(self.target)
        self.assertIn(r'C:\WCB\runs\run-123\launch.ps1', script)
        self.assertIn(r'C:\WCB\runs\run-123\request.json', script)
        self.assertIn('scheduled task action does not match', script)
        self.assertIn("$state.phase -eq 'auth_failed'", script)
        self.assertIn("$state.phase -eq 'finished'", script)
        self.assertIn('nonterminal launcher disappeared', script)
        self.assertIn('$LASTEXITCODE -ne 0', script)
        self.assertIn('$taskAbsentAfter', script)
        self.assertIn('$stagingConditionMet', script)

    def test_cleanup_consumes_phase_aware_result_payloads(self) -> None:
        console = ConsoleSession(r'WIN\Administrator', 1, 412)
        cases = (
            ({
                'cleaned': False,
                'reason': 'nonterminal launcher disappeared without a captured or terminated process tree',
                'state_phase': 'agent_starting', 'result_phase': '',
                'terminal_result_found': False, 'terminal_result_verified': False,
                'wrapper_found': False, 'agent_found': False,
                'wrapper_terminated': False, 'agent_terminated': False,
                'task_absent_after': False, 'staging_condition_met': True,
                'staging_preserved': True, 'diagnostic': {},
            }, False),
            ({
                'cleaned': True, 'reason': None,
                'state_phase': 'auth_failed', 'result_phase': 'auth_failed',
                'terminal_result_found': True, 'terminal_result_verified': True,
                'wrapper_found': False, 'agent_found': False,
                'wrapper_terminated': False, 'agent_terminated': False,
                'task_absent_after': True, 'staging_condition_met': True,
                'staging_preserved': False, 'diagnostic': {},
            }, True),
            ({
                'cleaned': True, 'reason': None,
                'state_phase': 'finished', 'result_phase': 'finished',
                'terminal_result_found': True, 'terminal_result_verified': True,
                'wrapper_found': False, 'agent_found': False,
                'wrapper_terminated': False, 'agent_terminated': False,
                'task_absent_after': True, 'staging_condition_met': True,
                'staging_preserved': False, 'diagnostic': {},
            }, True),
            ({
                'cleaned': False, 'reason': 'terminal result identity or phase does not match this run',
                'state_phase': 'finished', 'result_phase': 'finished',
                'terminal_result_found': True, 'terminal_result_verified': False,
                'wrapper_found': False, 'agent_found': False,
                'wrapper_terminated': False, 'agent_terminated': False,
                'task_absent_after': False, 'staging_condition_met': True,
                'staging_preserved': True, 'diagnostic': {},
            }, False),
        )
        for remote_payload, expected_cleaned in cases:
            with self.subTest(reason=remote_payload['reason']):
                self.target.run.return_value = subprocess.CompletedProcess(
                    [], 0, json.dumps(remote_payload).encode(), b'',
                )
                result = self.launcher.cleanup('run-123', console, None, None)
                self.assertIs(result['cleaned'], expected_cleaned)

    def test_cleanup_rejects_remote_success_without_postconditions(self) -> None:
        cases = (
            (False, True, False, 'task still exists'),
            (True, False, False, 'staging was not removed'),
            (True, False, True, 'preserved staging disappeared'),
        )
        for task_absent, staging_met, preserve_staging, label in cases:
            with self.subTest(label=label):
                remote_payload = {
                    'cleaned': True, 'reason': None,
                    'task_absent_after': task_absent,
                    'staging_condition_met': staging_met,
                    'staging_preserved': preserve_staging, 'diagnostic': {},
                }
                self.target.run.return_value = subprocess.CompletedProcess(
                    [], 0, json.dumps(remote_payload).encode(), b'',
                )
                result = self.launcher.cleanup(
                    'run-123', ConsoleSession(r'WIN\Administrator', 1, 412),
                    None, None, preserve_staging=preserve_staging,
                )
                self.assertFalse(result['cleaned'])
                self.assertIn('without satisfying postconditions', result['reason'])

    def test_control_powershell_is_fail_fast_without_changing_generic_encoder(self) -> None:
        control = decode_encoded_powershell(_control_powershell("Write-Output 'ok'"))
        generic = decode_encoded_powershell(encoded_powershell("Write-Output 'ok'"))
        self.assertTrue(control.startswith(
            "$ErrorActionPreference = 'Stop'\nSet-StrictMode -Version Latest\n",
        ))
        self.assertNotIn('$ErrorActionPreference', generic)
        self.assertNotIn('Set-StrictMode', generic)
        source = (ROOT / 'runner/opencode.py').read_text(encoding='utf-8')
        interactive_source = source.split('class InteractiveOpenCode:', 1)[1].split(
            '\ndef encoded_powershell(', 1,
        )[0]
        self.assertNotIn('target.run(encoded_powershell(script)', interactive_source)

    def test_launcher_rejects_non_console_session(self) -> None:
        state = {
            'run_id': 'run-123', 'wrapper_pid': 700, 'session_id': 4,
            'username': r'WIN\Administrator', 'wrapper_executable': 'pwsh.exe',
            'wrapper_command_line': 'pwsh launch.ps1',
        }
        payload = {
            'found': True, 'finished': False, 'state': state,
            'wrapper_found': True, 'wrapper_session_id': 4,
            'wrapper_username': r'WIN\Administrator',
            'wrapper_executable': 'pwsh.exe',
            'wrapper_command_line': 'pwsh launch.ps1',
        }
        self.target.run.return_value = subprocess.CompletedProcess(
            [], 0, json.dumps(payload).encode(), b'',
        )
        with self.assertRaisesRegex(InteractiveAgentError, 'active console session'):
            self.launcher.inspect_launcher(
                'run-123', ConsoleSession(r'WIN\Administrator', 1, 412), timeout=1,
            )


class InteractiveLauncherScriptTests(unittest.TestCase):
    def test_auth_completes_before_agent_and_unknown_output_fails_closed(self) -> None:
        script = (ROOT / 'config/run-interactive-opencode.ps1').read_text(encoding='utf-8')
        auth = script.index('& $Request.executable auth list')
        agent = script.index('& $Request.executable @($Request.arguments)')
        self.assertLess(auth, agent)
        user_check = script.index('launcher user $Username does not match expected user')
        self.assertLess(user_check, auth)
        self.assertIn("Write-State -Phase 'auth_check'", script)
        self.assertIn("Write-State -Phase 'auth_failed'", script)
        self.assertIn('authentication output was not recognized', script)
        self.assertIn('$AuthExitCode -ne 0 -or -not $AuthKnownGood', script)
        self.assertIn("Write-State -Phase 'agent_starting'", script)
        self.assertIn('opencode.auth.stdout.log', script)
        self.assertIn('opencode.auth.stderr.log', script)


class FakeInteractiveOpenCode:
    def __init__(
        self, *, result: dict | None, stdout: bytes, stderr: bytes, trace=None,
        inspect_error: InteractiveAgentError | None = None,
        collect_error: InteractiveAgentError | None = None,
        terminate_error: InteractiveAgentError | None = None,
        stage_error: InteractiveAgentError | None = None,
    ) -> None:
        self.result = result
        self.stdout = stdout
        self.stderr = stderr
        self.console = ConsoleSession(r'WIN\Administrator', 1, 412)
        self.process = InteractiveProcess(
            'placeholder', 'placeholder', 700, 701, 1, 700,
            r'C:\OpenCode\opencode.exe',
            r'opencode.exe --dir "C:\WCB\tasks\PS002 Project (quoted)" '
            r'--model test/model --variant test --agent bench',
            r'WIN\Administrator',
        )
        self.stage_args = None
        self.started_run_id = None
        self.terminated = False
        self.cleaned = False
        self.trace = trace
        self.inspect_error = inspect_error
        self.collect_error = collect_error
        self.terminate_error = terminate_error
        self.stage_error = stage_error
        self.cleanup_args = None
        self.wrapper_terminated = False
        self.cleanup_result = {'cleaned': True, 'reason': None, 'diagnostic': {}}
        self.cleanup_preserve_staging = None

    def preflight(self):
        return self.console

    def stage(self, run_id, **kwargs):
        self.stage_args = (run_id, kwargs)
        if self.stage_error is not None:
            raise self.stage_error

    def start(self, run_id):
        self.started_run_id = run_id

    def inspect_launcher(self, run_id, console):
        return LauncherIdentity(
            run_id, f'WCB-{run_id}', 700, 1, r'WIN\Administrator',
            r'C:\Program Files\PowerShell\7\pwsh.exe', 'pwsh launch.ps1',
            rf'C:\WCB\runs\{run_id}\launch.ps1', rf'C:\WCB\runs\{run_id}\request.json',
        )

    def inspect_process(self, launcher):
        if self.inspect_error is not None:
            raise self.inspect_error
        run_id = launcher.run_id
        return InteractiveProcess(
            run_id, f'WCB-{run_id}', self.process.wrapper_pid, self.process.pid,
            self.process.session_id, self.process.parent_pid,
            self.process.executable, self.process.command_line, self.process.username,
        )

    def mark_running(self, process):
        pass

    def read_result(self, launcher):
        return self.result

    def collect_output(self, run_id):
        if self.trace is not None:
            self.trace.append('collect_output')
        if self.collect_error is not None:
            raise self.collect_error
        return self.stdout, self.stderr

    def collect_auth_output(self, run_id):
        return b'1 credentials\n', b''

    def process_alive(self, process):
        return True

    def terminate(self, process):
        if self.trace is not None:
            self.trace.append('terminate')
        if self.terminate_error is not None:
            raise self.terminate_error
        self.terminated = True

    def cleanup(self, run_id, console, launcher, process, *, preserve_staging=False):
        self.cleanup_args = (run_id, console, launcher, process)
        if launcher is not None and process is None:
            self.wrapper_terminated = True
        self.cleaned = True
        self.cleanup_preserve_staging = preserve_staging
        result = dict(self.cleanup_result)
        result['staging_preserved'] = (
            preserve_staging if result.get('cleaned') else result.get('staging_preserved', True)
        )
        return result


class FakeScreenshots:
    def __init__(self, domain, run_dir, orchestrator, *, timeout_seconds, context=None):
        self.directory = run_dir / 'screenshots'
        self.context = context or {}
        self.timeout_seconds = timeout_seconds

    def _write(self, name):
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / name).write_bytes(b'png')

    def start(self):
        self._write('000-agent-start.png')

    def finish_agent(self, *, timed_out):
        self._write('000-timeout.png' if timed_out else '001-agent-exit.png')

    def stop(self):
        pass

    def evaluator_before(self):
        self._write('001-evaluator-before.png')


def fake_ssh_target(*results):
    target = Mock()
    target.upload_bytes.return_value = subprocess.CompletedProcess([], 0, b'', b'')
    target.run.side_effect = list(results)
    return target


class CanaryOutputTests(unittest.TestCase):
    def config(self, timeout: int) -> dict:
        return {
            'guest': {
                'address': 'guest', 'user': 'Administrator',
                'ssh_key': '/tmp/key', 'known_hosts': '/tmp/known_hosts',
            },
            'opencode': {
                'executable': r'C:\OpenCode\opencode.exe', 'model': 'test/model',
                'variant': 'test', 'agent': 'bench',
            },
            'runtime': {'agent_timeout_seconds': timeout},
        }

    def test_control_user_and_interactive_desktop_user_are_separate(self) -> None:
        config = self.config(0)
        config['guest']['interactive_user'] = 'benchmark'
        target = fake_ssh_target(
            subprocess.CompletedProcess([], 0, b'', b''),
            subprocess.CompletedProcess([], 0, b'{"passed":true}\n', b''),
        )
        interactive = FakeInteractiveOpenCode(
            result={'exit_code': 0}, stdout=b'', stderr=b'',
        )

        with tempfile.TemporaryDirectory() as temporary:
            with patch('runner.real_canary.SshTarget', return_value=target) as ssh_type, \
                    patch('runner.real_canary.InteractiveOpenCode', return_value=interactive) as interactive_type, \
                    patch('runner.real_canary.require_visual_domain'):
                self.assertEqual(run(config, ROOT, Path(temporary), visual=True), 0)

        self.assertEqual(ssh_type.call_args.kwargs['user'], 'Administrator')
        self.assertIs(interactive_type.call_args.args[0], target)
        self.assertEqual(interactive_type.call_args.args[1], 'benchmark')

    def test_timeout_saves_partial_output_and_all_artifact_streams(self) -> None:
        setup = subprocess.CompletedProcess([], 0, b'', b'')
        evaluation = subprocess.CompletedProcess([], 0, b'{"passed":true}\n', b'')
        target = fake_ssh_target(setup, evaluation)
        interactive = FakeInteractiveOpenCode(
            result=None, stdout=b'{"type":"partial"}\n', stderr=b'waiting',
        )

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with patch('runner.real_canary.SshTarget', return_value=target), \
                    patch('runner.real_canary.InteractiveOpenCode', return_value=interactive), \
                    patch('runner.real_canary.ScreenshotMonitor', FakeScreenshots), \
                    patch('runner.real_canary.require_visual_domain'):
                self.assertEqual(run(self.config(0), ROOT, output, visual=True), 0)
            run_dir = next(output.iterdir())
            self.assertEqual((run_dir / 'opencode.stdout.jsonl').read_bytes(), b'{"type":"partial"}\n')
            self.assertEqual((run_dir / 'opencode.stderr.log').read_bytes(), b'waiting')
            for name in ('orchestrator.jsonl', 'agent.jsonl', 'evaluator.jsonl'):
                self.assertTrue((run_dir / name).is_file())
            self.assertTrue((run_dir / 'screenshots/000-timeout.png').is_file())
            events = [json.loads(line)['event'] for line in (run_dir / 'orchestrator.jsonl').read_text().splitlines()]
            self.assertIn('agent_timeout', events)
            evidence = json.loads((run_dir / 'interactive-process.json').read_text())
            self.assertEqual(evidence['run_id'], run_dir.name)
            self.assertEqual(evidence['pid'], 701)
            self.assertEqual(evidence['session_id'], evidence['console_session_id'])
            self.assertEqual(interactive.stage_args[0], run_dir.name)
            self.assertEqual(interactive.started_run_id, run_dir.name)
            self.assertTrue(interactive.terminated)
            self.assertTrue(interactive.cleaned)

    def test_timeout_captures_before_output_event_and_termination(self) -> None:
        trace = []
        target = fake_ssh_target(
            subprocess.CompletedProcess([], 0, b'', b''),
            subprocess.CompletedProcess([], 0, b'{"passed":true}\n', b''),
        )
        interactive = FakeInteractiveOpenCode(
            result=None, stdout=b'partial', stderr=b'waiting', trace=trace,
        )

        class TracedScreenshots(FakeScreenshots):
            def finish_agent(self, *, timed_out):
                trace.append('timeout_screenshot')
                super().finish_agent(timed_out=timed_out)

        original_emit = JsonlLog.emit

        def traced_emit(log, event, **fields):
            if event == 'agent_timeout':
                trace.append('timeout_event')
            return original_emit(log, event, **fields)

        with tempfile.TemporaryDirectory() as temporary:
            with patch('runner.real_canary.SshTarget', return_value=target), \
                    patch('runner.real_canary.InteractiveOpenCode', return_value=interactive), \
                    patch('runner.real_canary.ScreenshotMonitor', TracedScreenshots), \
                    patch('runner.real_canary.require_visual_domain'), \
                    patch.object(JsonlLog, 'emit', traced_emit):
                self.assertEqual(run(self.config(0), ROOT, Path(temporary), visual=True), 0)
        self.assertEqual(
            trace,
            ['timeout_screenshot', 'collect_output', 'timeout_event', 'terminate'],
        )

    def test_normal_exit_collects_output_without_termination(self) -> None:
        target = fake_ssh_target(
            subprocess.CompletedProcess([], 0, b'', b''),
            subprocess.CompletedProcess([], 0, b'{"passed":true}\n', b''),
        )
        interactive = FakeInteractiveOpenCode(
            result={'exit_code': 0}, stdout=b'{"type":"done"}\n', stderr=b'',
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with patch('runner.real_canary.SshTarget', return_value=target), \
                    patch('runner.real_canary.InteractiveOpenCode', return_value=interactive), \
                    patch('runner.real_canary.ScreenshotMonitor', FakeScreenshots), \
                    patch('runner.real_canary.require_visual_domain'):
                self.assertEqual(run(self.config(300), ROOT, output, visual=True), 0)
            run_dir = next(output.iterdir())
            self.assertTrue((run_dir / 'screenshots/001-agent-exit.png').is_file())
            self.assertEqual((run_dir / 'opencode.stdout.jsonl').read_bytes(), b'{"type":"done"}\n')
            self.assertFalse((run_dir / 'score.json').exists())
            metadata = json.loads((run_dir / 'metadata.json').read_text())
            self.assertEqual(metadata['evidence_schema'], 'wcb.run-evidence/v2')
            self.assertEqual(metadata['workspace'], r'C:\WCB\tasks\PS002 Project (quoted)')
            self.assertNotIn('passed', metadata)
            self.assertFalse(interactive.terminated)
            self.assertTrue(interactive.cleaned)

    def test_inspect_failure_still_cleans_verified_launcher_and_runs_evaluator(self) -> None:
        target = fake_ssh_target(
            subprocess.CompletedProcess([], 0, b'', b''),
            subprocess.CompletedProcess([], 0, b'{"passed":true}\n', b''),
        )
        interactive = FakeInteractiveOpenCode(
            result=None, stdout=b'', stderr=b'',
            inspect_error=InteractiveAgentError('Agent identity capture failed'),
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with patch('runner.real_canary.SshTarget', return_value=target), \
                    patch('runner.real_canary.InteractiveOpenCode', return_value=interactive):
                self.assertEqual(run(self.config(300), ROOT, output), 0)
            run_dir = next(output.iterdir())
            events = [
                json.loads(line)['event']
                for line in (run_dir / 'orchestrator.jsonl').read_text().splitlines()
            ]
            self.assertIn('interactive_agent_failed', events)
            self.assertIn('interactive_cleanup_finished', events)
            self.assertTrue((run_dir / 'evaluator.jsonl').is_file())
            self.assertIsNotNone(interactive.cleanup_args[2])
            self.assertIsNone(interactive.cleanup_args[3])
            self.assertTrue(interactive.wrapper_terminated)

    def test_timeout_collection_and_status_failure_do_not_skip_event_or_evaluator(self) -> None:
        trace = []
        target = fake_ssh_target(
            subprocess.CompletedProcess([], 0, b'', b''),
            subprocess.CompletedProcess([], 0, b'{"passed":true}\n', b''),
        )
        interactive = FakeInteractiveOpenCode(
            result=None, stdout=b'', stderr=b'', trace=trace,
            collect_error=InteractiveAgentError('output unavailable'),
            terminate_error=InteractiveAgentError('process query unavailable'),
        )

        class TracedScreenshots(FakeScreenshots):
            def finish_agent(self, *, timed_out):
                trace.append('timeout_screenshot')
                super().finish_agent(timed_out=timed_out)

        original_emit = JsonlLog.emit

        def traced_emit(log, event, **fields):
            if event == 'agent_timeout':
                trace.append('timeout_event')
            return original_emit(log, event, **fields)

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with patch('runner.real_canary.SshTarget', return_value=target), \
                    patch('runner.real_canary.InteractiveOpenCode', return_value=interactive), \
                    patch('runner.real_canary.ScreenshotMonitor', TracedScreenshots), \
                    patch('runner.real_canary.require_visual_domain'), \
                    patch.object(JsonlLog, 'emit', traced_emit):
                self.assertEqual(run(self.config(0), ROOT, output, visual=True), 0)
            run_dir = next(output.iterdir())
            events = [
                json.loads(line)['event']
                for line in (run_dir / 'orchestrator.jsonl').read_text().splitlines()
            ]
            self.assertIn('agent_output_collection_failed', events)
            self.assertIn('agent_timeout', events)
            self.assertIn('interactive_termination_failed', events)
            self.assertTrue((run_dir / 'evaluator.jsonl').is_file())
        self.assertEqual(
            trace,
            ['timeout_screenshot', 'collect_output', 'timeout_event', 'terminate'],
        )

    def test_ssh_never_directly_launches_opencode(self) -> None:
        target = fake_ssh_target(
            subprocess.CompletedProcess([], 0, b'', b''),
            subprocess.CompletedProcess([], 0, b'{"passed":true}\n', b''),
        )
        interactive = FakeInteractiveOpenCode(
            result={'exit_code': 0}, stdout=b'', stderr=b'',
        )
        with tempfile.TemporaryDirectory() as temporary:
            with patch('runner.real_canary.SshTarget', return_value=target), \
                    patch('runner.real_canary.InteractiveOpenCode', return_value=interactive):
                self.assertEqual(run(self.config(300), ROOT, Path(temporary)), 0)
        self.assertEqual(target.run.call_count, 2)
        for call in target.run.call_args_list:
            self.assertNotIn('opencode.exe', call.args[0].casefold())
            self.assertNotIn(' auth list', call.args[0].casefold())

    def test_cleanup_refusal_preserves_diagnostics(self) -> None:
        target = fake_ssh_target(
            subprocess.CompletedProcess([], 0, b'', b''),
            subprocess.CompletedProcess([], 0, b'{"passed":true}\n', b''),
        )
        interactive = FakeInteractiveOpenCode(
            result={'exit_code': 0}, stdout=b'', stderr=b'',
        )
        interactive.cleanup_result = {
            'cleaned': False,
            'reason': 'scheduled task action does not match this run launcher/request absolute paths',
            'diagnostic': {'task_found': True},
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with patch('runner.real_canary.SshTarget', return_value=target), \
                    patch('runner.real_canary.InteractiveOpenCode', return_value=interactive):
                self.assertEqual(run(self.config(300), ROOT, output), 0)
            run_dir = next(output.iterdir())
            diagnostic = json.loads((run_dir / 'interactive-diagnostics.json').read_text())
            self.assertTrue(diagnostic['guest_staging_preserved'])
            self.assertEqual(diagnostic['cleanup']['task_found'], True)
            events = [
                json.loads(line)['event']
                for line in (run_dir / 'orchestrator.jsonl').read_text().splitlines()
            ]
            self.assertIn('interactive_cleanup_refused', events)

    def test_partial_stage_failure_runs_diagnostics_and_preserves_staging(self) -> None:
        target = fake_ssh_target(
            subprocess.CompletedProcess([], 0, b'', b''),
            subprocess.CompletedProcess([], 0, b'{"passed":true}\n', b''),
        )
        interactive = FakeInteractiveOpenCode(
            result=None, stdout=b'', stderr=b'',
            stage_error=InteractiveAgentError('staging write failed'),
        )
        interactive.cleanup_result = {
            'cleaned': False,
            'reason': 'scheduled task is missing without a verified terminal result',
            'staging_preserved': True,
            'diagnostic': {'task_found': False, 'state_found': False},
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with patch('runner.real_canary.SshTarget', return_value=target), \
                    patch('runner.real_canary.InteractiveOpenCode', return_value=interactive):
                self.assertEqual(run(self.config(300), ROOT, output), 0)
            run_dir = next(output.iterdir())
            diagnostic = json.loads((run_dir / 'interactive-diagnostics.json').read_text())
            self.assertTrue(diagnostic['guest_staging_preserved'])
            self.assertFalse(diagnostic['cleanup']['task_found'])
            events = [
                json.loads(line)['event']
                for line in (run_dir / 'orchestrator.jsonl').read_text().splitlines()
            ]
            self.assertIn('interactive_agent_failed', events)
            self.assertIn('interactive_cleanup_refused', events)
            self.assertTrue(interactive.cleaned)
            self.assertTrue(interactive.cleanup_preserve_staging)
            self.assertIsNone(interactive.cleanup_args[2])
            self.assertIsNone(interactive.cleanup_args[3])


class AtomicBytesTests(unittest.TestCase):
    def test_replace_failure_preserves_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / 'output.log'
            destination.write_bytes(b'old')
            with patch('runner.report.os.replace', side_effect=OSError('replace failed')):
                with self.assertRaisesRegex(OSError, 'replace failed'):
                    write_bytes_atomic(destination, b'new')
            self.assertEqual(destination.read_bytes(), b'old')
            self.assertEqual(list(Path(temporary).iterdir()), [destination])


class SshTimeoutOrderingTests(unittest.TestCase):
    def test_timeout_callback_runs_before_process_kill(self) -> None:
        target = SshTarget('guest', 'user', Path('/tmp/key'), Path('/tmp/hosts'))
        process = MagicMock()
        process.communicate.side_effect = [
            subprocess.TimeoutExpired('ssh', 300, output=b'partial', stderr=b'waiting'),
            (b'full', b'waiting'),
        ]
        process.returncode = -9
        manager = MagicMock()
        manager.__enter__.return_value = process
        manager.__exit__.return_value = False

        def observe(error: subprocess.TimeoutExpired) -> None:
            self.assertFalse(process.kill.called)
            self.assertEqual(error.stdout, b'partial')

        with patch.object(SshTarget, 'base', return_value=['ssh']), \
                patch('runner.opencode.subprocess.Popen', return_value=manager):
            with self.assertRaises(subprocess.TimeoutExpired) as raised:
                target.run('command', timeout=300, on_timeout=observe)
        process.kill.assert_called_once_with()
        self.assertEqual(raised.exception.stdout, b'full')


if __name__ == '__main__':
    unittest.main()
