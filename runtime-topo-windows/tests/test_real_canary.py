from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from runner.real_canary import _record_agent_process, _run_agent
from runner.report import JsonlLog


class RecordAgentProcessTests(unittest.TestCase):
    def read_events(self, path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]

    def test_preserves_and_parses_normal_process_output(self) -> None:
        stdout = b'{"type":"step","value":"snow"}\nplain text\n{"partial":'
        stderr = b'warning:\xff'
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            log = JsonlLog(run_dir / 'agent.jsonl', 'agent')

            _record_agent_process(
                run_dir,
                log,
                stdout=stdout,
                stderr=stderr,
                exit_code=0,
                timed_out=False,
                timeout_seconds=300,
            )

            self.assertEqual((run_dir / 'opencode.stdout.jsonl').read_bytes(), stdout)
            self.assertEqual((run_dir / 'opencode.stderr.log').read_bytes(), stderr)
            events = self.read_events(run_dir / 'agent.jsonl')
            self.assertEqual([event['event'] for event in events], [
                'opencode_event', 'opencode_event', 'opencode_event', 'process_finished',
            ])
            self.assertEqual(events[0]['payload'], {'type': 'step', 'value': 'snow'})
            self.assertEqual(events[1]['payload'], {'raw': 'plain text'})
            self.assertEqual(events[2]['payload'], {'raw': '{"partial":'})
            self.assertEqual(events[3]['exit_code'], 0)
            self.assertFalse(events[3]['timed_out'])
            self.assertEqual(events[3]['stderr'], 'warning:\ufffd')
            self.assertNotIn('timeout_seconds', events[3])

    def test_records_empty_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            log = JsonlLog(run_dir / 'agent.jsonl', 'agent')

            _record_agent_process(
                run_dir,
                log,
                stdout=None,
                stderr=None,
                exit_code=124,
                timed_out=True,
                timeout_seconds=300,
            )

            self.assertEqual((run_dir / 'opencode.stdout.jsonl').read_bytes(), b'')
            self.assertEqual((run_dir / 'opencode.stderr.log').read_bytes(), b'')
            events = self.read_events(run_dir / 'agent.jsonl')
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]['event'], 'process_finished')
            self.assertEqual(events[0]['exit_code'], 124)
            self.assertTrue(events[0]['timed_out'])
            self.assertEqual(events[0]['timeout_seconds'], 300)

    def test_accepts_string_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            log = JsonlLog(run_dir / 'agent.jsonl', 'agent')

            _record_agent_process(
                run_dir,
                log,
                stdout='{"ok":true}\n',
                stderr='diagnostic',
                exit_code=124,
                timed_out=True,
                timeout_seconds=10,
            )

            self.assertEqual((run_dir / 'opencode.stdout.jsonl').read_bytes(), b'{"ok":true}\n')
            self.assertEqual((run_dir / 'opencode.stderr.log').read_bytes(), b'diagnostic')
            events = self.read_events(run_dir / 'agent.jsonl')
            self.assertEqual(events[0]['payload'], {'ok': True})
            self.assertEqual(events[-1]['stderr'], 'diagnostic')

    def test_captures_timeout_expired_partial_output(self) -> None:
        class TimeoutTarget:
            def run(self, command: str, *, timeout: int) -> subprocess.CompletedProcess[bytes]:
                raise subprocess.TimeoutExpired(
                    command,
                    timeout,
                    output=b'{"partial":true}\n',
                    stderr=b'still running',
                )

        stdout, stderr, exit_code, timed_out = _run_agent(TimeoutTarget(), 'command', 300)

        self.assertEqual(stdout, b'{"partial":true}\n')
        self.assertEqual(stderr, b'still running')
        self.assertEqual(exit_code, 124)
        self.assertTrue(timed_out)

if __name__ == '__main__':
    unittest.main()
