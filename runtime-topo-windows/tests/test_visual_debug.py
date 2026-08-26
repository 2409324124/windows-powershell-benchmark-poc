from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch

from runner.opencode import SshTarget
from runner.real_canary import run
from runner.report import JsonlLog
from runner.vm import ScreenshotMonitor


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


class CanaryOutputTests(unittest.TestCase):
    def test_timeout_saves_partial_output_and_all_artifact_streams(self) -> None:
        config = {
            'guest': {
                'address': 'guest', 'user': 'Administrator',
                'ssh_key': '/tmp/key', 'known_hosts': '/tmp/known_hosts',
            },
            'opencode': {
                'executable': r'C:\OpenCode\opencode.exe', 'model': 'test/model',
                'variant': 'test', 'agent': 'bench',
            },
            'runtime': {'agent_timeout_seconds': 300},
        }
        auth = subprocess.CompletedProcess([], 0, b'1 credentials', b'')
        setup = subprocess.CompletedProcess([], 0, b'', b'')
        timeout = subprocess.TimeoutExpired([], 300, output=b'{"type":"partial"}\n', stderr=b'waiting')
        evaluation = subprocess.CompletedProcess([], 0, b'{"passed":true}\n', b'')
        target = unittest.mock.Mock()
        target.run.side_effect = [auth, setup, timeout, evaluation]

        class FakeScreenshots:
            def __init__(self, domain, run_dir, orchestrator, *, timeout_seconds):
                self.directory = run_dir / 'screenshots'

            def _write(self, name):
                self.directory.mkdir(parents=True, exist_ok=True)
                (self.directory / name).write_bytes(b'png')

            def start(self):
                self._write('000-agent-start.png')

            def finish_agent(self, *, timed_out):
                self._write('300-timeout.png')

            def evaluator_before(self):
                self._write('300-evaluator-before.png')

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with patch('runner.real_canary.SshTarget', return_value=target), \
                    patch('runner.real_canary.ScreenshotMonitor', FakeScreenshots):
                self.assertEqual(run(config, ROOT, output, visual=True), 0)
            run_dir = next(output.iterdir())
            self.assertEqual((run_dir / 'opencode.stdout.jsonl').read_bytes(), b'{"type":"partial"}\n')
            self.assertEqual((run_dir / 'opencode.stderr.log').read_bytes(), b'waiting')
            for name in ('orchestrator.jsonl', 'agent.jsonl', 'evaluator.jsonl'):
                self.assertTrue((run_dir / name).is_file())
            self.assertTrue((run_dir / 'screenshots/300-timeout.png').is_file())
            events = [json.loads(line)['event'] for line in (run_dir / 'orchestrator.jsonl').read_text().splitlines()]
            self.assertIn('agent_timeout', events)


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
