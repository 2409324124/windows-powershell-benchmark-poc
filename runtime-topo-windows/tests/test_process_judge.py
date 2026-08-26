from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from runner.process_judge import (
    CRITERION_IDS,
    ProcessJudgeError,
    _judge_config_content,
    _parse_opencode_output,
    _stage_bundle,
    judge_root,
)


def judge_result(score: int = 10) -> dict:
    criteria = [
        {
            'id': criterion_id,
            'score': score,
            'reason': f'{criterion_id} evidence is sufficient.',
            'evidence': ['agent.jsonl:event=opencode_event'],
        }
        for criterion_id in CRITERION_IDS
    ]
    return {
        'process_score': score * len(criteria),
        'reason': 'The recorded process is consistent with the frozen workspace.',
        'criteria': criteria,
    }


def jsonl(*events: dict) -> bytes:
    return ''.join(json.dumps(event) + '\n' for event in events).encode()


class OpenCodeJudgeOutputTests(unittest.TestCase):
    @staticmethod
    def config() -> dict:
        return {
            'guest': {
                'address': 'guest', 'user': 'Administrator',
                'ssh_key': '/tmp/key', 'known_hosts': '/tmp/known-hosts',
                'interactive_user': 'benchmark',
            },
            'judge': {
                'executable': r'C:\OpenCode\opencode.exe',
                'model': 'opencode-go/gpt-5.6-luna',
                'variant': 'low', 'agent': 'judge',
                'timeout_seconds': 180,
            },
        }

    def test_run_id_rejects_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            project = Path(__file__).resolve().parents[1]
            with self.assertRaisesRegex(ProcessJudgeError, 'invalid run id'):
                judge_root(
                    self.config(), project, output,
                    run_id='../opencode-escape',
                )

    def test_run_id_metadata_mismatch_is_infrastructure_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            run_dir = output / 'opencode-ps001-example'
            run_dir.mkdir()
            (run_dir / 'metadata.json').write_text(json.dumps({
                'run_id': 'opencode-ps001-other',
                'task': 'ps001-utf8-output',
                'evidence_schema': 'wcb.run-evidence/v3',
            }), encoding='utf-8')
            project = Path(__file__).resolve().parents[1]

            reports = judge_root(
                self.config(), project, output, run_id=run_dir.name,
            )

            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0]['status'], 'infrastructure_failure')
            self.assertIn('metadata run_id contradicts', reports[0]['error'])

    def test_staging_grants_modify_but_keeps_judge_evidence_read_only(self) -> None:
        target = Mock()
        target.upload_bytes.return_value = subprocess.CompletedProcess(
            [], 0, b'', b'',
        )
        target.run.return_value = subprocess.CompletedProcess([], 0, b'', b'')

        workspace = _stage_bundle(
            target, 'judge-example', b'zip', b'{}', 'wcb-agent-admin',
        )

        self.assertEqual(
            workspace, r'C:\WCB\judge-runs\judge-example\workspace',
        )
        script = target.upload_bytes.call_args.args[0].decode('utf-8-sig')
        self.assertIn("$modifyGrant = '*' + $judgeSid + ':(OI)(CI)M'", script)
        self.assertIn('icacls.exe $workspace /grant:r $modifyGrant /T /C', script)
        self.assertIn(
            "$readDirectoryGrant = '*' + $judgeSid + ':(OI)(CI)RX'", script,
        )
        self.assertIn('icacls.exe $evidenceRoot /inheritance:r /grant:r', script)
        self.assertIn("$readFileGrant = '*' + $judgeSid + ':R'", script)
        self.assertIn('icacls.exe $evidencePath /inheritance:r /grant:r', script)

    def test_accepts_exact_json_after_successful_windows_replay(self) -> None:
        expected = judge_result(9)
        result, replay = _parse_opencode_output(jsonl(
            {
                'type': 'tool_use',
                'part': {
                    'tool': 'bash',
                    'state': {
                        'status': 'completed',
                        'input': {
                            'command': 'powershell.exe -NoProfile -File .\\build.ps1',
                        },
                        'metadata': {'exit': 0},
                    },
                },
            },
            {'type': 'text', 'part': {'text': json.dumps(expected)}},
        ))
        self.assertEqual(result, expected)
        self.assertEqual(replay, [{
            'command': 'powershell.exe -NoProfile -File .\\build.ps1',
            'exit_code': 0,
        }])

    def test_rejects_failed_or_unrecorded_windows_replay(self) -> None:
        output = jsonl(
            {
                'type': 'tool_use',
                'part': {
                    'tool': 'bash',
                    'state': {
                        'status': 'completed',
                        'input': {'command': 'powershell.exe -File .\\build.ps1'},
                        'metadata': {'exit': 1},
                    },
                },
            },
            {'type': 'text', 'part': {'text': json.dumps(judge_result())}},
        )
        with self.assertRaisesRegex(ProcessJudgeError, 'successful Windows PowerShell'):
            _parse_opencode_output(output)

    def test_derives_total_from_criteria_when_reported_total_is_wrong(self) -> None:
        value = judge_result()
        value['process_score'] = 49
        output = jsonl(
            {
                'type': 'tool_use',
                'part': {
                    'tool': 'bash',
                    'state': {
                        'status': 'completed',
                        'input': {'command': 'powershell -Command Get-ChildItem'},
                        'metadata': {'exit': 0},
                    },
                },
            },
            {'type': 'text', 'part': {'text': json.dumps(value)}},
        )
        result, _ = _parse_opencode_output(output)
        self.assertEqual(result['process_score'], 50)

    def test_inline_agent_config_is_read_only_and_local(self) -> None:
        config = json.loads(_judge_config_content())
        permission = config['agent']['judge']['permission']
        self.assertEqual(config['share'], 'disabled')
        self.assertEqual(permission['read'], 'allow')
        self.assertEqual(permission['write'], 'deny')
        self.assertEqual(permission['edit'], 'deny')
        self.assertEqual(permission['external_directory'], 'deny')
        self.assertEqual(permission['bash']['*'], 'deny')
        self.assertEqual(permission['bash']['powershell.exe *'], 'allow')


if __name__ == '__main__':
    unittest.main()
