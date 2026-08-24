#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path


PROJECT = Path('/home/miku/runtime-topo-windows')
WCB = Path('/mnt/PM983/windows-benchmark')
BASE = WCB / 'base/ws2025-opencode-1.18.21-v001.qcow2'
NVRAM = WCB / 'base/ws2025-opencode-1.18.21-v001_VARS.fd'
TPM = WCB / 'base/ws2025-opencode-1.18.21-v001_tpm'
TEMPLATE = PROJECT / 'config/ws2025-domain-template.xml'
GUEST_FACTS = PROJECT / 'config/guest-lock-facts.json'
OUTPUT = PROJECT / 'environment-lock.json'


def command(*args: str) -> str:
    result = subprocess.run(args, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def sidecar_hash(path: Path) -> str:
    return path.read_text(encoding='utf-8').split()[0].lower()


def package_hash(name: str) -> dict:
    path = WCB / 'iso/tools' / name
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest(path)}


def main() -> int:
    base_expected = sidecar_hash(Path(str(BASE) + '.sha256'))
    if base_expected != 'e159e1d2388c19d74eb32cc479adb50e4b8749b7e3430cf601b175ca1319bab4':
        raise RuntimeError(f'unexpected base sidecar hash: {base_expected}')
    guest = json.loads(GUEST_FACTS.read_text(encoding='utf-8'))
    if guest['opencode']['auth_present']:
        raise RuntimeError('refusing to lock a base with OpenCode auth present')

    lock = {
        'schema': 'wcb.environment-lock/v1',
        'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'host': {
            'hostname': platform.node(),
            'kernel': platform.release(),
            'architecture': platform.machine(),
            'os_release': command('sh', '-c', ". /etc/os-release; printf '%s %s' \"$NAME\" \"$VERSION_ID\""),
            'qemu': command('qemu-system-x86_64', '--version').splitlines()[0],
            'libvirt': command('virsh', '--connect', 'qemu:///system', 'version'),
            'machine_type': 'pc-q35-noble',
            'cpu_mode': 'host-passthrough',
            'vcpu': 8,
            'memory_kib': 16777216,
        },
        'firmware': {
            'loader': '/usr/share/OVMF/OVMF_CODE_4M.ms.fd',
            'loader_sha256': digest(Path('/usr/share/OVMF/OVMF_CODE_4M.ms.fd')),
            'secure_boot': True,
            'enrolled_keys': True,
            'nvram': str(NVRAM),
            'nvram_sha256': sidecar_hash(Path(str(NVRAM) + '.sha256')),
            'tpm_version': '2.0',
            'tpm_state': str(TPM),
            'tpm_manifest_sha256': digest(Path(str(TPM) + '.sha256')),
        },
        'base': {
            'path': str(BASE),
            'format': 'qcow2',
            'virtual_bytes': 128849018880,
            'sha256': base_expected,
            'readonly_mode': oct(BASE.stat().st_mode & 0o777),
            'backing_file': None,
        },
        'domain_template': {
            'path': str(TEMPLATE),
            'sha256': digest(TEMPLATE),
            'network': 'wcb-nat',
            'graphics': False,
            'installation_media': False,
            'clipboard': False,
            'host_shared_directories': False,
        },
        'network': {
            'name': 'wcb-nat',
            'bridge': 'virbr-wcb',
            'gateway': '192.168.122.1',
            'cidr': '192.168.122.0/24',
            'mode': 'nat',
            'inbound_port_forwards': [],
            'guest_ssh_allowed_source': '192.168.122.1',
        },
        'tools_media': {
            'opencode': package_hash('opencode-windows-x64.zip'),
            'powershell': package_hash('PowerShell-7.6.4-win-x64.msi'),
            'git': package_hash('Git-2.55.0.5-64-bit.exe'),
        },
        'guest': guest,
        'session_defaults': {
            'user': 'Administrator',
            'opencode_model': 'opencode-go/gpt-5.6-luna',
            'opencode_variant': 'medium',
            'opencode_agent': 'bench',
            'agent_timeout_seconds': 300,
            'auth_in_base': False,
            'evaluator_location': 'host',
            'evaluator_injected_after_agent_exit': True,
        },
        'reference': {
            'repository': 'https://github.com/2409324124/windows-powershell-benchmark-poc',
            'commit': '897990524040878e5cdc1ad70c2a79cfc4772fdd',
        },
        'known_risks': [
            'Windows Server Evaluation grace state is intentionally not activated by request.',
            'Guest Administrator privilege is contained by the disposable VM boundary, not a substitute for a hypervisor security boundary.',
        ],
    }
    encoded = json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
    temporary = OUTPUT.with_suffix('.json.tmp')
    temporary.write_text(encoded, encoding='utf-8', newline='\n')
    os.replace(temporary, OUTPUT)
    lock_hash = digest(OUTPUT)
    OUTPUT.with_suffix('.json.sha256').write_text(f'{lock_hash}  {OUTPUT.name}\n', encoding='ascii')
    print(f'{lock_hash}  {OUTPUT}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
