#!/usr/bin/env python3
from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


TOKENS = ('__DOMAIN_NAME__', '__DOMAIN_UUID__', '__OVERLAY_PATH__', '__NVRAM_PATH__', '__MAC_ADDRESS__')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--template', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--uuid', required=True)
    parser.add_argument('--overlay', required=True)
    parser.add_argument('--nvram', required=True)
    parser.add_argument('--mac', required=True)
    parser.add_argument(
        '--visual', action='store_true',
        help='enable local-only SPICE and QXL for human observation',
    )
    args = parser.parse_args()
    replacements = {
        '__DOMAIN_NAME__': args.name,
        '__DOMAIN_UUID__': args.uuid,
        '__OVERLAY_PATH__': args.overlay,
        '__NVRAM_PATH__': args.nvram,
        '__MAC_ADDRESS__': args.mac,
    }
    value = args.template.read_text(encoding='utf-8')
    for token, replacement in replacements.items():
        if token not in value:
            raise RuntimeError(f'missing token {token}')
        value = value.replace(token, replacement)
    remaining = [token for token in TOKENS if token in value]
    if remaining:
        raise RuntimeError(f'unresolved tokens: {remaining}')
    if args.visual:
        root = ET.fromstring(value)
        devices = root.find('devices')
        if devices is None:
            raise RuntimeError('template has no devices')
        graphics = ET.SubElement(devices, 'graphics', {
            'type': 'spice', 'autoport': 'yes', 'listen': '127.0.0.1',
        })
        ET.SubElement(graphics, 'listen', {'type': 'address', 'address': '127.0.0.1'})
        ET.SubElement(graphics, 'clipboard', {'copypaste': 'no'})
        ET.SubElement(graphics, 'filetransfer', {'enable': 'no'})
        video = ET.SubElement(devices, 'video')
        ET.SubElement(video, 'model', {
            'type': 'qxl', 'ram': '65536', 'vram': '65536',
            'vgamem': '16384', 'heads': '1', 'primary': 'yes',
        })
        ET.indent(root, space='  ')
        value = ET.tostring(root, encoding='unicode') + '\n'
    args.output.write_text(value, encoding='utf-8', newline='\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
