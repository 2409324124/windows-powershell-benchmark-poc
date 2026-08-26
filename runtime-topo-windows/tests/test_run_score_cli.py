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
                output, run.ROOT, task_id='ps001-utf8-output', run_id=None,
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
                config, run.ROOT, output,
                task_id='ps005-transactional-deploy', run_id=None,
            )

    def test_run_id_is_forwarded_to_judge_and_score(self) -> None:
        run_id = 'opencode-ps001-example'
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with (
                mock.patch('sys.argv', [
                    'runner.run', 'score', '--output', str(output),
                    '--run-id', run_id,
                ]),
                mock.patch('runner.run.score_root', return_value=[{
                    'run_id': run_id, 'status': 'model_failure',
                }]) as score_root,
                mock.patch('builtins.print'),
            ):
                self.assertEqual(run.main(), 0)
            score_root.assert_called_once_with(
                output, run.ROOT, task_id=None, run_id=run_id,
            )

            config = {'judge': {'model': 'opencode-go/gpt-5.6-luna'}}
            with (
                mock.patch('sys.argv', [
                    'runner.run', 'process-judge', '--output', str(output),
                    '--run-id', run_id,
                ]),
                mock.patch('runner.run.load_config', return_value=config),
                mock.patch('runner.run.judge_root', return_value=[{
                    'run_id': run_id, 'status': 'completed',
                }]) as judge_root,
                mock.patch('builtins.print'),
            ):
                self.assertEqual(run.main(), 0)
            judge_root.assert_called_once_with(
                config, run.ROOT, output, task_id=None, run_id=run_id,
            )

    def test_model_and_implicit_variant_override_canary_config(self) -> None:
        config = {
            'opencode': {
                'model': 'old/model', 'variant': 'low',
                'executable': 'opencode', 'agent': 'bench',
            },
            'storage': {'runs': '/tmp/runs'},
        }
        with (
            mock.patch('sys.argv', [
                'runner.run', 'opencode-canary',
                '--model', 'opencode-go/mimo-v2.5', '--no-variant',
            ]),
            mock.patch('runner.run.load_config', return_value=config),
            mock.patch('runner.run.run_real_canary', return_value=0) as canary,
        ):
            self.assertEqual(run.main(), 0)
        applied = canary.call_args.args[0]['opencode']
        self.assertEqual(applied['model'], 'opencode-go/mimo-v2.5')
        self.assertEqual(applied['variant'], 'provider-default')
        self.assertFalse(applied['variant_explicit'])

    def test_variant_and_no_variant_are_mutually_exclusive(self) -> None:
        with mock.patch('sys.argv', [
            'runner.run', 'opencode-canary',
            '--variant', 'low', '--no-variant',
        ]):
            with self.assertRaises(SystemExit) as raised:
                run.main()
        self.assertEqual(raised.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
