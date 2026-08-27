from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from runner.real_canary import _evaluator_input, _runtime_environment, load_task


ROOT = Path(__file__).resolve().parents[1]
TASK_IDS = (
    'ps001-utf8-output',
    'ps002-path-quoting',
    'ps003-native-exit',
    'ps004-parallel-merge',
    'ps005-transactional-deploy',
    'ps006-dual-engine-pipeline',
    'ps007-parallel-runspace-fanout',
    'ps008-ssh-remoting-sync',
    'ps009-native-byte-pipeline',
    'ps010-cross-platform-manifest',
)
TARGET_FILES = {
    'ps001-utf8-output': ['build.ps1'],
    'ps002-path-quoting': ['build.ps1'],
    'ps003-native-exit': ['pipeline.ps1'],
    'ps004-parallel-merge': ['build.ps1'],
    'ps005-transactional-deploy': ['deploy.ps1'],
    'ps006-dual-engine-pipeline': ['summarize.ps1'],
    'ps007-parallel-runspace-fanout': ['fanout.ps1'],
    'ps008-ssh-remoting-sync': ['sync.ps1'],
    'ps009-native-byte-pipeline': ['byte-pipeline.ps1'],
    'ps010-cross-platform-manifest': ['build-manifest.ps1'],
}


class TaskCatalogTests(unittest.TestCase):
    def test_catalog_contains_legacy_and_high_difficulty_ladders(self) -> None:
        workspaces = set()
        for difficulty, task_id in enumerate(TASK_IDS, start=1):
            task, manifest = load_task(ROOT, task_id)
            self.assertEqual(manifest['difficulty'], difficulty)
            self.assertNotIn(manifest['workspace'], workspaces)
            self.assertEqual(manifest.get('target_files'), TARGET_FILES[task_id])
            workspaces.add(manifest['workspace'])
            evaluator = (task / 'evaluate.ps1').read_text(encoding='utf-8')
            if difficulty <= 5:
                self.assertEqual(manifest['schema'], 'wcb.task/v1')
                self.assertEqual(manifest['shell'], 'Windows PowerShell 5.1')
                self.assertIn('Windows PowerShell 5.1', (task / 'prompt.md').read_text(encoding='utf-8'))
                self.assertIn('powershell.exe', evaluator)
            else:
                self.assertEqual(manifest['schema'], 'wcb.task/v2')
                self.assertTrue(manifest['runtime_matrix'])
                self.assertGreaterEqual(len(manifest['evaluator_scenarios']), 2)
                generated = _evaluator_input(manifest, f'opencode-ps{difficulty:03d}-test')
                self.assertEqual(generated['task'], task_id)
                self.assertEqual(generated['scenarios'], manifest['evaluator_scenarios'])
            checks = manifest.get('result_checks')
            self.assertIsInstance(checks, list)
            self.assertTrue(checks)
            self.assertEqual(len({check['id'] for check in checks}), len(checks))
            for check in checks:
                self.assertEqual(check.get('operator', 'equals'), 'equals')
                self.assertIn('expected', check)
                self.assertIn(check['field'], evaluator)
            result_block = re.search(
                r'^(?P<indent>[ \t]*)\$result\s*=\s*\[ordered\]@\{'
                r'(.*?)^(?P=indent)\}',
                evaluator,
                flags=re.MULTILINE | re.DOTALL,
            )
            self.assertIsNotNone(result_block)
            evaluator_fields = set(re.findall(
                r'^\s+([A-Za-z0-9_]+)\s*=', result_block.group(2), flags=re.MULTILINE,
            )) - {'passed'}
            self.assertEqual({check['field'] for check in checks}, evaluator_fields)

    def test_runtime_environment_selects_only_declared_runtimes(self) -> None:
        _, manifest = load_task(ROOT, 'ps006-dual-engine-pipeline')
        config = {
            'runtimes': {
                'win-ps51': {'environment_variable': 'A', 'executable': 'one'},
                'win-pwsh76': {'environment_variable': 'B', 'executable': 'two'},
                'unused': {'environment_variable': 'C', 'executable': 'three'},
            },
        }
        self.assertEqual(_runtime_environment(config, manifest), {'A': 'one', 'B': 'two'})

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
