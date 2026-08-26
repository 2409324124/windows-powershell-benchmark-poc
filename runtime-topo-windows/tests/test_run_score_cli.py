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
                mock.patch(
                    'runner.run.load_config',
                    return_value={'judge': {'model': 'gpt-5.6-luna'}},
                ) as load_config,
                mock.patch(
                    'runner.run.CodexProcessJudge.from_config',
                    return_value=mock.sentinel.judge,
                ) as from_config,
                mock.patch('runner.run.score_root', return_value=[{
                    'run_id': 'opencode-ps001-example',
                    'status': 'passed',
                }]) as score_root,
                mock.patch('builtins.print') as output_print,
            ):
                exit_code = run.main()

            self.assertEqual(exit_code, 0)
            load_config.assert_called_once_with(run.ROOT / 'benchmark.yaml')
            from_config.assert_called_once_with({'model': 'gpt-5.6-luna'})
            score_root.assert_called_once_with(
                output, run.ROOT, mock.sentinel.judge,
                task_id='ps001-utf8-output',
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
                mock.patch(
                    'runner.run.load_config', return_value={'judge': {}},
                ),
                mock.patch(
                    'runner.run.CodexProcessJudge.from_config',
                    return_value=mock.sentinel.judge,
                ),
                mock.patch('runner.run.score_root', return_value=[{
                    'run_id': 'opencode-ps001-bad',
                    'status': 'infrastructure_failure',
                }]),
                mock.patch('builtins.print'),
            ):
                self.assertEqual(run.main(), 2)


if __name__ == '__main__':
    unittest.main()
