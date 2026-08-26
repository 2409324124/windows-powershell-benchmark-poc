from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runner.real_canary import load_task


ROOT = Path(__file__).resolve().parents[1]
TASK_IDS = (
    'ps001-utf8-output',
    'ps002-path-quoting',
    'ps003-native-exit',
    'ps004-parallel-merge',
    'ps005-transactional-deploy',
)


class TaskCatalogTests(unittest.TestCase):
    def test_catalog_is_a_five_level_powershell_51_ladder(self) -> None:
        workspaces = set()
        for difficulty, task_id in enumerate(TASK_IDS, start=1):
            task, manifest = load_task(ROOT, task_id)
            self.assertEqual(manifest['difficulty'], difficulty)
            self.assertEqual(manifest['shell'], 'Windows PowerShell 5.1')
            self.assertNotIn(manifest['workspace'], workspaces)
            workspaces.add(manifest['workspace'])
            self.assertIn('Windows PowerShell 5.1', (task / 'prompt.md').read_text(encoding='utf-8'))
            evaluator = (task / 'evaluate.ps1').read_text(encoding='utf-8')
            self.assertIn('powershell.exe', evaluator)

    def test_task_id_cannot_escape_catalog(self) -> None:
        with self.assertRaisesRegex(ValueError, 'invalid task id'):
            load_task(ROOT, '../ps002-path-quoting')

    def test_manifest_id_must_match_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = root / 'tasks' / 'example'
            task.mkdir(parents=True)
            (task / 'task.json').write_text(json.dumps({
                'schema': 'wcb.task/v1',
                'id': 'different',
                'workspace': r'C:\WCB\tasks\Example',
            }), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'invalid task manifest'):
                load_task(root, 'example')


if __name__ == '__main__':
    unittest.main()
