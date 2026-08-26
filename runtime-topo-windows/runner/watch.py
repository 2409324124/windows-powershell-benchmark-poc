from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from runner.run import ROOT, load_config


def last_record(path: Path) -> dict | None:
    if not path.exists():
        return None
    last = None
    with path.open('r', encoding='utf-8') as handle:
        for line in handle:
            if line.strip():
                last = json.loads(line)
    return last


def first_record(path: Path) -> dict | None:
    if not path.exists():
        return None
    with path.open('r', encoding='utf-8') as handle:
        for line in handle:
            if line.strip():
                return json.loads(line)
    return None


def render(run_dir: Path) -> str:
    streams = {
        name: last_record(run_dir / f'{name.lower()}.jsonl')
        for name in ('Orchestrator', 'Agent', 'Evaluator')
    }
    started = first_record(run_dir / 'orchestrator.jsonl')
    elapsed = 0
    if started is not None:
        start = datetime.fromisoformat(started['ts'].replace('Z', '+00:00'))
        elapsed = max(0, int((datetime.now(timezone.utc) - start).total_seconds()))
    screenshots = sorted((run_dir / 'screenshots').glob('*.png'))
    latest = screenshots[-1].relative_to(run_dir) if screenshots else 'none'
    lines = [f'Run: {run_dir.name}', f'Elapsed: {elapsed}s', '']
    for name, record in streams.items():
        lines.extend((f'{name}:', record['event'] if record else 'none', ''))
    lines.extend(('Latest screenshot:', str(latest)))
    return '\n'.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description='Watch the latest benchmark events and screenshot')
    parser.add_argument('run_id')
    parser.add_argument('--config', type=Path, default=ROOT / 'benchmark.yaml')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    output = args.output or Path(load_config(args.config)['storage']['runs'])
    run_dir = output / args.run_id
    if not run_dir.is_dir():
        parser.error(f'run directory does not exist: {run_dir}')
    try:
        while True:
            if not args.once:
                print('\033[2J\033[H', end='')
            print(render(run_dir), flush=True)
            if args.once:
                return 0
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
