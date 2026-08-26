from __future__ import annotations

import json
import unittest

from runner.process_judge import (
    CRITERION_IDS,
    ProcessJudgeError,
    _judge_config_content,
    _parse_opencode_output,
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

    def test_rejects_criterion_sum_contradiction(self) -> None:
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
        with self.assertRaisesRegex(ProcessJudgeError, 'criterion sum 50'):
            _parse_opencode_output(output)

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
