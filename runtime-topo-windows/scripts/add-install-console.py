#!/usr/bin/env python3
from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('domain_xml', type=Path)
    args = parser.parse_args()
    tree = ET.parse(args.domain_xml)
    devices = tree.getroot().find('devices')
    if devices is None:
        raise RuntimeError('devices missing')
    for tag in ('graphics', 'video'):
        for element in devices.findall(tag):
            devices.remove(element)
    graphics = ET.SubElement(devices, 'graphics', {'type': 'spice', 'autoport': 'yes', 'listen': '127.0.0.1'})
    ET.SubElement(graphics, 'listen', {'type': 'address', 'address': '127.0.0.1'})
    ET.SubElement(graphics, 'clipboard', {'copypaste': 'yes'})
    ET.SubElement(graphics, 'filetransfer', {'enable': 'yes'})
    video = ET.SubElement(devices, 'video')
    ET.SubElement(video, 'model', {'type': 'qxl', 'ram': '65536', 'vram': '65536', 'vgamem': '16384', 'heads': '1', 'primary': 'yes'})
    ET.indent(tree, space='  ')
    tree.write(args.domain_xml, encoding='unicode', xml_declaration=False)
    with args.domain_xml.open('a', encoding='utf-8') as handle:
        handle.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
