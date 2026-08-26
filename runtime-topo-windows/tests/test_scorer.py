from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runner.scorer import CodexProcessJudge, EvidenceError, score_root, score_run


TASK_ID = 'ps999-synthetic'
TASK_PROMPT = 'Repair the PowerShell script and verify the requested behavior.'


class FakeJudge:
    def __init__(
        self, process_score: int = 50, reason: str = 'Sound process.',
        *, model: str = 'gpt-5.6-luna', reasoning: str = 'low',
    ) -> None:
        self.result = {'process_score': process_score, 'reason': reason}
        self.calls: list[dict] = []
        self._identity = {'model': model, 'reasoning': reasoning}

    @property
    def identity(self) -> dict:
        return self._identity.copy()

    def judge(self, **evidence: object) -> dict:
        self.calls.append(evidence)
        return self.result.copy()


def score(run_dir: Path, task_manifest: dict, judge: FakeJudge | None = None) -> dict:
    return score_run(run_dir, task_manifest, TASK_PROMPT, judge or FakeJudge())


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + '\n', encoding='utf-8')


def write_jsonl(path: Path, values: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(value) + '\n' for value in values), encoding='utf-8')


def manifest(*fields: str) -> dict:
    return {
        'schema': 'wcb.task/v1',
        'id': TASK_ID,
        'workspace': r'C:\WCB\tasks\Synthetic',
        'target_files': ['build.ps1'],
        'result_checks': [
            {'id': field.replace('_', '-'), 'field': field, 'expected': True}
            for field in fields
        ],
    }


def make_complete_run(root: Path, *, run_id: str = 'opencode-ps999-good') -> Path:
    run_dir = root / run_id
    write_json(run_dir / 'metadata.json', {
        'schema': 'wcb.run-metadata/v1',
        'evidence_schema': 'wcb.run-evidence/v2',
        'run_id': run_id,
        'task': TASK_ID,
        'model': 'example/model',
        'variant': 'medium',
        'workspace': r'C:\WCB\tasks\Synthetic',
        'agent_exit': 0,
        'timed_out': False,
        'evaluator_exit': 0,
    })
    write_jsonl(run_dir / 'orchestrator.jsonl', [
        {'ts': '2026-08-26T00:00:00.000Z', 'event': 'run_started', 'run_id': run_id, 'task': TASK_ID},
        {'ts': '2026-08-26T00:00:01.000Z', 'event': 'agent_started', 'automatic': True, 'input_channel': 'none'},
        {'ts': '2026-08-26T00:00:03.000Z', 'event': 'agent_finished', 'exit_code': 0, 'timed_out': False},
        {'ts': '2026-08-26T00:00:04.000Z', 'event': 'run_finished', 'evidence_complete': True},
    ])
    write_jsonl(run_dir / 'agent.jsonl', [
        {'event': 'opencode_event', 'payload': {
            'type': 'tool_use', 'tool': 'write', 'status': 'completed',
            'input': {'path': r'C:\WCB\TASKS\SYNTHETIC\BUILD.PS1'},
        }},
        {'event': 'opencode_event', 'payload': {
            'type': 'tool_use', 'tool': 'powershell', 'status': 'error',
            'input': {'command': 'powershell.exe -File build.ps1'},
        }},
        {'event': 'opencode_event', 'payload': {
            'type': 'tool_use', 'tool': 'powershell', 'status': 'completed',
            'input': {'command': 'powershell.exe -File build.ps1; Invoke-Pester'},
        }},
        {'event': 'process_finished', 'exit_code': 0, 'timed_out': False, 'stderr': ''},
    ])
    evaluation = {'first': True, 'second': True, 'passed': True}
    write_json(run_dir / 'evaluator.json', evaluation)
    write_jsonl(run_dir / 'evaluator.jsonl', [
        {
            'ts': '2026-08-26T00:00:03.500Z',
            'event': 'evaluation', 'exit_code': 0,
            'result': evaluation, 'stderr': '',
        },
    ])
    return run_dir


class CodexProcessJudgeTests(unittest.TestCase):
    def test_invokes_locked_down_codex_exec_with_structured_untrusted_evidence(self) -> None:
        adapter = CodexProcessJudge(
            executable='/home/miku/.local/bin/codex',
            model='gpt-5.6-luna', reasoning='low', timeout_seconds=90,
        )
        self.assertEqual(adapter.identity, {
            'model': 'gpt-5.6-luna', 'reasoning': 'low',
        })

        def complete(command: list[str], **kwargs: object) -> mock.Mock:
            output_path = Path(command[command.index('--output-last-message') + 1])
            write_json(output_path, {
                'process_score': 42,
                'reason': 'The evidence shows a mostly effective process.',
            })
            self.assertEqual(list(Path(str(kwargs['cwd'])).iterdir()), [])
            return mock.Mock(returncode=0, stdout='', stderr='')

        with mock.patch('runner.scorer.subprocess.run', side_effect=complete) as run:
            result = adapter.judge(
                task_prompt=TASK_PROMPT,
                manifest=manifest('first', 'second'),
                orchestrator=[{'event': 'run_started'}],
                agent_records=[{'event': 'opencode_event', 'payload': {'type': 'tool_use'}}],
                evaluation={'first': True, 'second': True, 'passed': True},
                evaluator_records=[{'event': 'evaluation', 'exit_code': 0}],
                result_breakdown={'score': 50, 'checks': []},
            )

        self.assertEqual(result['process_score'], 42)
        command = run.call_args.args[0]
        self.assertEqual(command[0:2], ['/home/miku/.local/bin/codex', 'exec'])
        for option in (
            '--ephemeral', '--ignore-user-config', '--ignore-rules',
            '--skip-git-repo-check', '--output-schema', '--output-last-message',
        ):
            self.assertIn(option, command)
        self.assertEqual(command[command.index('--model') + 1], 'gpt-5.6-luna')
        self.assertEqual(command[command.index('--sandbox') + 1], 'read-only')
        self.assertIn('model_reasoning_effort="low"', command)
        self.assertEqual(command[-1], '-')
        prompt = run.call_args.kwargs['input']
        self.assertIn('UNTRUSTED EVIDENCE', prompt)
        self.assertIn(TASK_PROMPT, prompt)
        self.assertIn('agent.jsonl', prompt)
        self.assertIn('evaluator.json', prompt)
        self.assertIn('evaluator.jsonl', prompt)
        self.assertIn('machine_result_breakdown', prompt)
        self.assertEqual(run.call_args.kwargs['timeout'], 90)

    def test_cli_failure_and_timeout_are_evidence_errors(self) -> None:
        adapter = CodexProcessJudge(
            executable='codex', model='gpt-5.6-luna',
            reasoning='low', timeout_seconds=10,
        )
        evidence = {
            'task_prompt': TASK_PROMPT,
            'manifest': manifest('first'),
            'orchestrator': [{'event': 'run_started'}],
            'agent_records': [{'event': 'process_finished'}],
            'evaluation': {'first': True, 'passed': True},
            'evaluator_records': [{'event': 'evaluation', 'exit_code': 0}],
            'result_breakdown': {'score': 50, 'checks': []},
        }
        with mock.patch(
            'runner.scorer.subprocess.run',
            return_value=mock.Mock(returncode=9, stdout='', stderr='judge failed'),
        ):
            with self.assertRaisesRegex(EvidenceError, 'CLI failed'):
                adapter.judge(**evidence)
        with mock.patch(
            'runner.scorer.subprocess.run',
            side_effect=subprocess.TimeoutExpired(['codex'], 10),
        ):
            with self.assertRaisesRegex(EvidenceError, 'timed out'):
                adapter.judge(**evidence)


class ScoreRunTests(unittest.TestCase):
    def test_combines_judge_process_score_and_equal_result_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = make_complete_run(Path(temporary))
            judge = FakeJudge(50, 'The Agent used a careful and effective process.')

            result = score(run_dir, manifest('first', 'second'), judge)

            self.assertEqual(result['schema'], 'wcb.score/v2')
            self.assertEqual(result['score'], 100)
            self.assertTrue(result['passed'])
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(result['classification'], 'passed')
            self.assertEqual(result['model'], 'example/model')
            self.assertEqual(result['variant'], 'medium')
            self.assertEqual(result['duration_seconds'], 4)
            self.assertIsNone(result['tokens'])
            self.assertIsNone(result['cost'])
            self.assertNotIn('duration', result)
            self.assertNotIn('token', result)
            self.assertEqual(result['process'], judge.result)
            self.assertEqual(result['result']['score'], 50)
            self.assertEqual(
                [item['points'] for item in result['result']['checks']],
                [25, 25],
            )
            self.assertEqual(len(judge.calls), 1)
            self.assertEqual(judge.calls[0]['task_prompt'], TASK_PROMPT)
            self.assertEqual(judge.calls[0]['manifest']['id'], TASK_ID)
            self.assertEqual(len(judge.calls[0]['orchestrator']), 4)
            self.assertEqual(len(judge.calls[0]['agent_records']), 4)
            self.assertEqual(judge.calls[0]['evaluation']['passed'], True)
            self.assertEqual(len(judge.calls[0]['evaluator_records']), 1)
            self.assertEqual(judge.calls[0]['result_breakdown']['score'], 50)

    def test_partial_judge_score_produces_model_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = make_complete_run(Path(temporary))

            result = score(
                run_dir, manifest('first', 'second'),
                FakeJudge(31, 'The process was useful but incomplete.'),
            )

            self.assertEqual(result['process']['process_score'], 31)
            self.assertEqual(result['score'], 81)
            self.assertEqual(result['status'], 'model_failure')
            self.assertFalse(result['passed'])

    def test_invalid_judge_output_is_infrastructure_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = make_complete_run(Path(temporary))
            judge = FakeJudge()
            judge.result = {'process_score': 51, 'reason': 'Out of range.'}

            result = score(run_dir, manifest('first', 'second'), judge)

            self.assertEqual(result['status'], 'infrastructure_failure')
            self.assertIsNone(result['score'])
            self.assertTrue(any('process judge' in error for error in result['errors']))

    def test_cached_judge_result_is_reused_without_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = make_complete_run(Path(temporary))
            first_judge = FakeJudge(37, 'Cached assessment.')
            first = score(run_dir, manifest('first', 'second'), first_judge)
            second_judge = FakeJudge(1, 'Must not be used.')

            second = score(run_dir, manifest('first', 'second'), second_judge)

            self.assertEqual(first['score'], 87)
            self.assertEqual(second['score'], 87)
            self.assertEqual(second['process'], {
                'process_score': 37, 'reason': 'Cached assessment.',
            })
            self.assertEqual(len(first_judge.calls), 1)
            self.assertEqual(second_judge.calls, [])
            self.assertEqual(
                json.loads((run_dir / 'process-judge.json').read_text()),
                {
                    'schema': 'wcb.process-judge-cache/v1',
                    'run_id': run_dir.name,
                    'judge': {
                        'model': 'gpt-5.6-luna', 'reasoning': 'low',
                    },
                    'result': second['process'],
                },
            )

    def test_cache_identity_mismatch_is_infrastructure_failure_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = make_complete_run(root, run_id='opencode-ps999-source')
            score(source, manifest('first', 'second'), FakeJudge(39, 'Original.'))
            cached = (source / 'process-judge.json').read_bytes()

            wrong_judge = FakeJudge(model='gpt-5.6-terra')
            judge_result = score(source, manifest('first', 'second'), wrong_judge)

            self.assertEqual(judge_result['status'], 'infrastructure_failure')
            self.assertTrue(any('judge identity' in error for error in judge_result['errors']))
            self.assertEqual(wrong_judge.calls, [])
            self.assertEqual((source / 'process-judge.json').read_bytes(), cached)

            target = make_complete_run(root, run_id='opencode-ps999-target')
            (target / 'process-judge.json').write_bytes(cached)
            target_judge = FakeJudge()

            run_result = score(target, manifest('first', 'second'), target_judge)

            self.assertEqual(run_result['status'], 'infrastructure_failure')
            self.assertTrue(any('run_id' in error for error in run_result['errors']))
            self.assertEqual(target_judge.calls, [])
            self.assertEqual((target / 'process-judge.json').read_bytes(), cached)

    def test_legacy_bare_judge_cache_is_rejected_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = make_complete_run(Path(temporary))
            cache_path = run_dir / 'process-judge.json'
            write_json(cache_path, {
                'process_score': 50, 'reason': 'Legacy bare cache.',
            })
            cached = cache_path.read_bytes()
            judge = FakeJudge()

            result = score(run_dir, manifest('first', 'second'), judge)

            self.assertEqual(result['status'], 'infrastructure_failure')
            self.assertTrue(any('cache envelope' in error for error in result['errors']))
            self.assertEqual(judge.calls, [])
            self.assertEqual(cache_path.read_bytes(), cached)

    def test_present_failed_check_scores_zero_without_infrastructure_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = make_complete_run(Path(temporary))
            write_json(run_dir / 'evaluator.json', {'first': True, 'second': False, 'passed': False})
            write_jsonl(run_dir / 'evaluator.jsonl', [{
                'ts': '2026-08-26T00:00:03.500Z',
                'event': 'evaluation', 'exit_code': 1,
                'result': {'first': True, 'second': False, 'passed': False}, 'stderr': '',
            }])
            metadata = json.loads((run_dir / 'metadata.json').read_text(encoding='utf-8'))
            metadata['evaluator_exit'] = 1
            write_json(run_dir / 'metadata.json', metadata)

            result = score(run_dir, manifest('first', 'second'))

            self.assertEqual(result['status'], 'model_failure')
            self.assertEqual(result['classification'], 'model_failure')
            self.assertEqual(result['score'], 75)
            self.assertFalse(result['passed'])

    def test_evaluator_passed_must_exist_and_be_boolean(self) -> None:
        for invalid in (None, 'true'):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as temporary:
                run_dir = make_complete_run(Path(temporary))
                evaluation = {'first': True, 'second': True}
                if invalid is not None:
                    evaluation['passed'] = invalid
                write_json(run_dir / 'evaluator.json', evaluation)
                write_jsonl(run_dir / 'evaluator.jsonl', [{
                    'ts': '2026-08-26T00:00:03.500Z',
                    'event': 'evaluation', 'exit_code': 0,
                    'result': evaluation, 'stderr': '',
                }])

                result = score(run_dir, manifest('first', 'second'))

                self.assertEqual(result['status'], 'infrastructure_failure')
                self.assertIsNone(result['score'])
                self.assertTrue(any(
                    'evaluator passed' in error for error in result['errors']
                ))

    def test_evaluator_passed_must_match_exit_and_all_result_checks(self) -> None:
        cases = (
            (True, 1, 'evaluator exit'),
            (False, 1, 'declared result checks'),
        )
        for passed, evaluator_exit, expected_error in cases:
            with self.subTest(
                passed=passed, evaluator_exit=evaluator_exit,
            ), tempfile.TemporaryDirectory() as temporary:
                run_dir = make_complete_run(Path(temporary))
                evaluation = {'first': True, 'second': True, 'passed': passed}
                write_json(run_dir / 'evaluator.json', evaluation)
                write_jsonl(run_dir / 'evaluator.jsonl', [{
                    'ts': '2026-08-26T00:00:03.500Z',
                    'event': 'evaluation', 'exit_code': evaluator_exit,
                    'result': evaluation, 'stderr': '',
                }])
                metadata = json.loads((run_dir / 'metadata.json').read_text())
                metadata['evaluator_exit'] = evaluator_exit
                write_json(run_dir / 'metadata.json', metadata)

                result = score(run_dir, manifest('first', 'second'))

                self.assertEqual(result['status'], 'infrastructure_failure')
                self.assertTrue(any(
                    expected_error in error for error in result['errors']
                ))

    def test_uses_last_step_finish_part_tokens_and_cost(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = make_complete_run(Path(temporary))
            records = [json.loads(line) for line in (
                run_dir / 'agent.jsonl'
            ).read_text(encoding='utf-8').splitlines()]
            records[-1:-1] = [
                {'event': 'opencode_event', 'payload': {
                    'type': 'step_finish',
                    'part': {'tokens': {'input': 10, 'output': 2}, 'cost': 0.01},
                }},
                {'event': 'opencode_event', 'payload': {
                    'type': 'step_finish',
                    'part': {
                        'tokens': {'input': 30, 'output': 7, 'reasoning': 3},
                        'cost': 0.125,
                    },
                }},
            ]
            write_jsonl(run_dir / 'agent.jsonl', records)

            result = score(run_dir, manifest('first', 'second'))

            self.assertEqual(result['tokens'], {
                'input': 30, 'output': 7, 'reasoning': 3,
            })
            self.assertEqual(result['cost'], 0.125)

    def test_missing_evidence_produces_null_infrastructure_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = make_complete_run(Path(temporary))
            (run_dir / 'agent.jsonl').unlink()

            result = score(run_dir, manifest('first', 'second'))

            self.assertIsNone(result['score'])
            self.assertIsNone(result['passed'])
            self.assertEqual(result['status'], 'infrastructure_failure')
            self.assertEqual(result['classification'], 'infrastructure_failure')
            for field in (
                'model', 'variant', 'duration_seconds', 'tokens', 'cost',
            ):
                self.assertIn(field, result)
            self.assertTrue(any('agent.jsonl' in error for error in result['errors']))

    def test_contradictory_terminal_evidence_is_infrastructure_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = make_complete_run(Path(temporary))
            metadata = json.loads((run_dir / 'metadata.json').read_text(encoding='utf-8'))
            metadata['agent_exit'] = 7
            write_json(run_dir / 'metadata.json', metadata)

            result = score(run_dir, manifest('first', 'second'))

            self.assertIsNone(result['score'])
            self.assertEqual(result['status'], 'infrastructure_failure')
            self.assertTrue(any('agent exit' in error for error in result['errors']))

    def test_orchestrator_and_evaluator_timestamp_order_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = make_complete_run(Path(temporary))
            evaluation = json.loads((run_dir / 'evaluator.json').read_text())
            write_jsonl(run_dir / 'evaluator.jsonl', [{
                'ts': '2026-08-26T00:00:02.000Z',
                'event': 'evaluation', 'exit_code': 0,
                'result': evaluation, 'stderr': '',
            }])

            result = score(run_dir, manifest('first', 'second'))

            self.assertEqual(result['status'], 'infrastructure_failure')
            self.assertTrue(any('event order' in error for error in result['errors']))

    def test_visual_run_requires_matching_interactive_identity_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = make_complete_run(Path(temporary))
            metadata = json.loads((run_dir / 'metadata.json').read_text())
            write_json(run_dir / 'metadata.json', metadata)
            orchestrator = [json.loads(line) for line in (
                run_dir / 'orchestrator.jsonl'
            ).read_text().splitlines()]
            orchestrator[0].update({'visual': True, 'console_session_id': 1})
            orchestrator[1].update({
                'pid': 701, 'session_id': 1,
                'model': metadata['model'], 'variant': metadata['variant'],
            })
            write_jsonl(run_dir / 'orchestrator.jsonl', orchestrator)
            identity = {
                'schema': 'wcb.interactive-process/v1',
                'run_id': run_dir.name,
                'wrapper_pid': 700,
                'pid': 701,
                'parent_pid': 700,
                'session_id': 1,
                'console_session_id': 1,
                'username': r'HOST\Administrator',
                'executable': r'C:\Program Files\OpenCode\opencode.exe',
                'command_line': (
                    f'opencode.exe --dir "{metadata["workspace"]}" '
                    f'--model {metadata["model"]} --variant {metadata["variant"]}'
                ),
            }
            write_json(run_dir / 'interactive-process.json', identity)
            agent_records = [json.loads(line) for line in (
                run_dir / 'agent.jsonl'
            ).read_text().splitlines()]
            agent_records.insert(0, {
                'event': 'interactive_process_started', **identity,
            })
            write_jsonl(run_dir / 'agent.jsonl', agent_records)

            result = score(run_dir, manifest('first', 'second'))

            self.assertEqual(result['status'], 'passed')

    def test_visual_v1_metadata_without_workspace_can_still_be_scored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = make_complete_run(Path(temporary))
            metadata = json.loads((run_dir / 'metadata.json').read_text())
            metadata.pop('evidence_schema')
            metadata.pop('workspace')
            write_json(run_dir / 'metadata.json', metadata)
            task_manifest = manifest('first', 'second')
            orchestrator = [json.loads(line) for line in (
                run_dir / 'orchestrator.jsonl'
            ).read_text().splitlines()]
            orchestrator[0].update({'visual': True, 'console_session_id': 1})
            orchestrator[1].update({
                'pid': 701, 'session_id': 1,
                'model': metadata['model'], 'variant': metadata['variant'],
            })
            write_jsonl(run_dir / 'orchestrator.jsonl', orchestrator)
            identity = {
                'schema': 'wcb.interactive-process/v1',
                'run_id': run_dir.name,
                'wrapper_pid': 700,
                'pid': 701,
                'parent_pid': 700,
                'session_id': 1,
                'console_session_id': 1,
                'username': r'HOST\Administrator',
                'executable': r'C:\Program Files\OpenCode\opencode.exe',
                'command_line': (
                    f'opencode.exe --dir "{task_manifest["workspace"]}" '
                    f'--model {metadata["model"]} --variant {metadata["variant"]}'
                ),
            }
            write_json(run_dir / 'interactive-process.json', identity)
            agent_records = [json.loads(line) for line in (
                run_dir / 'agent.jsonl'
            ).read_text().splitlines()]
            agent_records.insert(0, {
                'event': 'interactive_process_started', **identity,
            })
            write_jsonl(run_dir / 'agent.jsonl', agent_records)

            result = score(run_dir, task_manifest)

            self.assertEqual(result['status'], 'passed')
            self.assertEqual(result['score'], 100)

    def test_visual_identity_mismatch_is_infrastructure_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = make_complete_run(Path(temporary))
            orchestrator = [json.loads(line) for line in (
                run_dir / 'orchestrator.jsonl'
            ).read_text().splitlines()]
            orchestrator[0].update({'visual': True, 'console_session_id': 1})
            write_jsonl(run_dir / 'orchestrator.jsonl', orchestrator)

            result = score(run_dir, manifest('first', 'second'))

            self.assertEqual(result['status'], 'infrastructure_failure')
            self.assertTrue(any('interactive-process.json' in error for error in result['errors']))

            metadata = json.loads((run_dir / 'metadata.json').read_text())
            orchestrator[1].update({
                'pid': 701, 'session_id': 1,
                'model': metadata['model'], 'variant': metadata['variant'],
            })
            write_jsonl(run_dir / 'orchestrator.jsonl', orchestrator)
            contradictory = {
                'schema': 'wcb.interactive-process/v1',
                'run_id': 'opencode-ps999-wrong',
                'wrapper_pid': 700, 'pid': 701, 'parent_pid': 700,
                'session_id': 1, 'console_session_id': 1,
                'username': r'HOST\Administrator',
                'executable': r'C:\Program Files\OpenCode\opencode.exe',
                'command_line': (
                    f'opencode.exe --dir "{metadata["workspace"]}" '
                    f'--model {metadata["model"]} --variant {metadata["variant"]}'
                ),
            }
            write_json(run_dir / 'interactive-process.json', contradictory)
            agent_records = [json.loads(line) for line in (
                run_dir / 'agent.jsonl'
            ).read_text().splitlines()]
            agent_records.insert(0, {
                'event': 'interactive_process_started', **contradictory,
            })
            write_jsonl(run_dir / 'agent.jsonl', agent_records)

            contradictory_result = score(run_dir, manifest('first', 'second'))

            self.assertEqual(
                contradictory_result['status'], 'infrastructure_failure',
            )
            self.assertTrue(any(
                'run_id contradicts' in error
                for error in contradictory_result['errors']
            ))

    def test_old_v1_timeout_and_legacy_passed_score_are_rescored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = make_complete_run(Path(temporary))
            metadata = json.loads((run_dir / 'metadata.json').read_text(encoding='utf-8'))
            metadata.pop('evidence_schema')
            metadata.pop('timed_out')
            metadata.pop('evaluator_exit')
            metadata['agent_exit'] = 124
            metadata['passed'] = True
            write_json(run_dir / 'metadata.json', metadata)
            write_json(run_dir / 'score.json', {'passed': True, 'score': 1})
            write_jsonl(run_dir / 'agent.jsonl', [
                {'event': 'process_timeout', 'timeout_seconds': 300},
            ])
            write_jsonl(run_dir / 'orchestrator.jsonl', [
                {'ts': '2026-08-26T00:00:00.000Z', 'event': 'run_started', 'run_id': run_dir.name, 'task': TASK_ID},
                {'ts': '2026-08-26T00:00:01.000Z', 'event': 'agent_started'},
                {'ts': '2026-08-26T00:05:01.000Z', 'event': 'agent_finished', 'exit_code': 124, 'timed_out': True},
                {'ts': '2026-08-26T00:05:02.000Z', 'event': 'run_finished', 'passed': True},
            ])
            evaluation = {
                'first': True, 'second': True,
                'powershell_51_exit': 0, 'passed': True,
            }
            write_json(run_dir / 'evaluator.json', evaluation)
            write_jsonl(run_dir / 'evaluator.jsonl', [{
                'ts': '2026-08-26T00:05:01.500Z',
                'event': 'evaluation', 'exit_code': 0,
                'result': evaluation, 'stderr': '',
            }])

            legacy_manifest = manifest('first', 'second', 'powershell_51_exit')
            legacy_manifest['result_checks'][-1]['expected'] = 0
            result = score(
                run_dir, legacy_manifest,
                FakeJudge(20, 'The run timed out before completing the process.'),
            )

            self.assertEqual(result['status'], 'model_failure')
            self.assertEqual(result['score'], 70)
            self.assertFalse(result['passed'])

    def test_old_v1_missing_declared_result_field_is_infrastructure_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = make_complete_run(Path(temporary))
            metadata = json.loads((run_dir / 'metadata.json').read_text(encoding='utf-8'))
            metadata.pop('evidence_schema')
            write_json(run_dir / 'metadata.json', metadata)
            legacy_manifest = manifest('first', 'second', 'powershell_51_exit')
            legacy_manifest['result_checks'][-1]['expected'] = 0

            result = score(run_dir, legacy_manifest)

            self.assertEqual(result['status'], 'infrastructure_failure')
            self.assertIsNone(result['score'])
            self.assertIsNone(result['passed'])
            self.assertTrue(any(
                "missing declared result field 'powershell_51_exit'" in error
                for error in result['errors']
            ))


class ScoreRootTests(unittest.TestCase):
    def test_scores_independently_and_root_report_has_no_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / 'project'
            task_dir = project / 'tasks' / TASK_ID
            task_dir.mkdir(parents=True)
            write_json(task_dir / 'task.json', manifest('first', 'second'))
            (task_dir / 'prompt.md').write_text(TASK_PROMPT, encoding='utf-8')
            first = make_complete_run(root / 'runs', run_id='opencode-ps999-first')
            second = make_complete_run(root / 'runs', run_id='opencode-ps999-second')
            other = make_complete_run(root / 'runs', run_id='opencode-ps998-other')
            metadata = json.loads((other / 'metadata.json').read_text(encoding='utf-8'))
            metadata['task'] = 'ps998-other'
            write_json(other / 'metadata.json', metadata)

            judge = FakeJudge()
            reports = score_root(
                root / 'runs', project, judge, task_id=TASK_ID,
            )

            self.assertEqual([report['run_id'] for report in reports], [
                'opencode-ps999-first', 'opencode-ps999-second',
            ])
            self.assertTrue((first / 'score.json').is_file())
            self.assertTrue((second / 'score.json').is_file())
            self.assertFalse((other / 'score.json').is_file())
            report = json.loads((root / 'runs' / 'score-report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['schema'], 'wcb.score-report/v2')
            self.assertEqual([item['run_id'] for item in report['runs']], [
                'opencode-ps999-first', 'opencode-ps999-second',
            ])
            for forbidden in ('score', 'total', 'average', 'mean', 'best', 'passed'):
                self.assertNotIn(forbidden, report)
            for item in report['runs']:
                for field in (
                    'model', 'variant', 'duration_seconds', 'tokens', 'cost',
                    'status', 'classification', 'score', 'passed',
                ):
                    self.assertIn(field, item)
                self.assertNotIn('duration', item)
                self.assertNotIn('token', item)

    def test_invalid_metadata_becomes_infrastructure_failure_in_root_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / 'runs' / 'opencode-ps999-broken'
            run_dir.mkdir(parents=True)
            (run_dir / 'metadata.json').write_text('{broken', encoding='utf-8')

            reports = score_root(root / 'runs', root / 'project', FakeJudge())

            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0]['status'], 'infrastructure_failure')
            self.assertIsNone(reports[0]['score'])
            report = json.loads((root / 'runs' / 'score-report.json').read_text())
            self.assertEqual(report['runs'], reports)


if __name__ == '__main__':
    unittest.main()
