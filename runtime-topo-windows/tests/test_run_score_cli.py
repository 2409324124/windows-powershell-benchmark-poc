from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runner import run


class ScoreCliTests(unittest.TestCase):
    def test_score_dispatches_with_output_and_task_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with (
                mock.patch('sys.argv', [
                    'runner.run', 'score', '--output', str(output),
                    '--task', 'ps001-utf8-output',
                ]),
                mock.patch('runner.run.score_root', return_value=[{
                    'run_id': 'opencode-ps001-example',
                    'status': 'passed',
                }]) as score_root,
                mock.patch('builtins.print') as output_print,
            ):
                exit_code = run.main()

            self.assertEqual(exit_code, 0)
            score_root.assert_called_once_with(
                output, run.ROOT, task_id='ps001-utf8-output',
            )
            output_print.assert_called_once()

    def test_score_requires_explicit_output_root(self) -> None:
        with mock.patch('sys.argv', ['runner.run', 'score']):
            with self.assertRaises(SystemExit) as raised:
                run.main()
        self.assertEqual(raised.exception.code, 2)

    def test_infrastructure_failure_makes_score_command_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with (
                mock.patch('sys.argv', [
                    'runner.run', 'score', '--output', temporary,
                ]),
                mock.patch('runner.run.score_root', return_value=[{
                    'run_id': 'opencode-ps001-bad',
                    'status': 'infrastructure_failure',
                }]),
                mock.patch('builtins.print'),
            ):
                self.assertEqual(run.main(), 2)

    def test_process_judge_dispatches_to_windows_opencode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            config = {'judge': {'model': 'opencode-go/gpt-5.6-luna'}}
            with (
                mock.patch('sys.argv', [
                    'runner.run', 'process-judge', '--output', str(output),
                    '--task', 'ps005-transactional-deploy',
                ]),
                mock.patch('runner.run.load_config', return_value=config),
                mock.patch('runner.run.judge_root', return_value=[{
                    'run_id': 'opencode-ps005-example',
                    'status': 'completed',
                }]) as judge_root,
                mock.patch('builtins.print'),
            ):
                self.assertEqual(run.main(), 0)
            judge_root.assert_called_once_with(
                config, run.ROOT, output, task_id='ps005-transactional-deploy',
            )


if __name__ == '__main__':
    unittest.main()
