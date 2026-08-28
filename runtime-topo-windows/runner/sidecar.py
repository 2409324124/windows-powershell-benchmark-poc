from __future__ import annotations

import subprocess
from pathlib import Path

from runner.opencode import InteractiveAgentError, SshTarget, _execute_control_script


class SidecarError(RuntimeError):
    pass


def _docker(arguments: list[str], *, timeout: int = 1200) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ['docker', *arguments], text=True, capture_output=True,
        timeout=timeout, check=False,
    )


def _require(result: subprocess.CompletedProcess[str], action: str) -> str:
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise SidecarError(f'{action} failed: {detail or result.returncode}')
    return result.stdout.strip()


def ensure_sidecar(
    config: dict,
    project_root: Path,
    target: SshTarget,
) -> dict:
    sidecar = config.get('sidecar')
    if not isinstance(sidecar, dict):
        raise SidecarError('benchmark config has no sidecar section')
    name = str(sidecar['container_name'])
    image = str(sidecar['image'])
    key = Path(sidecar['ssh_key'])
    key.parent.mkdir(parents=True, exist_ok=True)
    if not key.is_file():
        generated = subprocess.run(
            ['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)],
            text=True, capture_output=True, timeout=30, check=False,
        )
        if generated.returncode != 0:
            raise SidecarError(generated.stderr.strip() or 'sidecar key generation failed')
    public_key = key.with_suffix(key.suffix + '.pub').read_text(encoding='ascii').strip()
    image_check = _docker(['image', 'inspect', image], timeout=30)
    if image_check.returncode != 0:
        context = project_root / 'container' / 'ps7-sidecar'
        prepared = subprocess.run(
            [str(context / 'prepare-package.sh')], text=True,
            capture_output=True, timeout=1200, check=False,
        )
        if prepared.returncode != 0:
            detail = prepared.stderr.strip() or prepared.stdout.strip()
            raise SidecarError(
                f'sidecar PowerShell package preparation failed: '
                f'{detail or prepared.returncode}'
            )
        _require(_docker(['build', '-t', image, str(context)]), 'sidecar image build')
    network = str(sidecar['network'])
    if _docker(['network', 'inspect', network], timeout=30).returncode != 0:
        _require(_docker(['network', 'create', '--internal', network]), 'sidecar network create')
    inspect = _docker(['inspect', '-f', '{{.State.Running}}', name], timeout=30)
    if inspect.returncode != 0:
        _require(_docker([
            'run', '-d', '--name', name, '--restart', 'unless-stopped',
            '--network', network,
            '--tmpfs', '/srv/wcb:rw,nosuid,nodev,size=256m',
            '--mount', 'type=volume,source=wcb-ps7-hostkeys,target=/etc/ssh/keys',
            '--publish', f'{sidecar["listen_address"]}:{sidecar["port"]}:22',
            '--env', f'WCB_AUTHORIZED_KEY={public_key}', image,
        ]), 'sidecar start')
    elif inspect.stdout.strip() != 'true':
        _require(_docker(['start', name], timeout=60), 'sidecar restart')
    host_key = _require(
        _docker(['exec', name, 'cat', '/etc/ssh/keys/ssh_host_ed25519_key.pub'], timeout=30),
        'sidecar host key read',
    )
    known_hosts = (
        f'[{sidecar["listen_address"]}]:{sidecar["port"]} '
        + host_key + '\n'
    ).encode('ascii')
    _install_windows_credentials(target, sidecar, key.read_bytes(), known_hosts)
    version = _require(
        _docker(['exec', name, 'pwsh', '-NoLogo', '-NoProfile', '-Command', '$PSVersionTable.PSVersion.ToString()'], timeout=30),
        'sidecar PowerShell probe',
    )
    if version != '7.6.4':
        raise SidecarError(f'sidecar PowerShell version is {version}, expected 7.6.4')
    return {
        'container': name,
        'image': image,
        'powershell': version,
        'windows_ssh_client_dir': str(sidecar['windows_ssh_client_dir']),
    }


def sidecar_run_residue(config: dict) -> list[str]:
    sidecar = config.get('sidecar')
    if not isinstance(sidecar, dict):
        raise SidecarError('benchmark config has no sidecar section')
    name = str(sidecar['container_name'])
    result = _docker([
        'exec', name, 'sh', '-c',
        "find /srv/wcb/runs -mindepth 1 -maxdepth 1 -print; "
        "find /tmp -mindepth 1 -user wcb-task -print",
    ], timeout=30)
    output = _require(result, 'sidecar residue probe')
    return [line for line in output.splitlines() if line]


def reset_sidecar(config: dict) -> None:
    sidecar = config.get('sidecar')
    if not isinstance(sidecar, dict):
        raise SidecarError('benchmark config has no sidecar section')
    name = str(sidecar['container_name'])
    inspected = _docker(['inspect', name], timeout=30)
    if inspected.returncode == 0:
        _require(_docker(['rm', '-f', name], timeout=60), 'sidecar reset')


def _install_windows_credentials(
    target: SshTarget,
    sidecar: dict,
    private_key: bytes,
    known_hosts: bytes,
) -> None:
    key_upload = 'wcb-ps7-sidecar-key'
    hosts_upload = 'wcb-ps7-sidecar-known-hosts'
    for contents, name in ((private_key, key_upload), (known_hosts, hosts_upload)):
        result = target.upload_bytes(contents, name, timeout=60)
        if result.returncode != 0:
            raise SidecarError(f'Windows sidecar credential upload failed: {name}')
    key_path = str(sidecar['windows_key_path']).replace("'", "''")
    hosts_path = str(sidecar['windows_known_hosts_path']).replace("'", "''")
    ssh_client_dir = str(sidecar['windows_ssh_client_dir']).replace("'", "''")
    interactive_user = str(sidecar['windows_user']).replace("'", "''")
    script = rf"""
$root = Split-Path -Parent '{key_path}'
foreach ($client in @('ssh.exe','scp.exe')) {{
    $clientPath = Join-Path '{ssh_client_dir}' $client
    if (-not (Test-Path -LiteralPath $clientPath -PathType Leaf)) {{
        throw "configured Windows SSH client is missing: $clientPath"
    }}
}}
New-Item -ItemType Directory -Path $root -Force | Out-Null
Move-Item -LiteralPath (Join-Path $env:USERPROFILE '{key_upload}') -Destination '{key_path}' -Force
Move-Item -LiteralPath (Join-Path $env:USERPROFILE '{hosts_upload}') -Destination '{hosts_path}' -Force
& icacls.exe $root /inheritance:r /grant:r '{interactive_user}:(OI)(CI)R' 'Administrators:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) {{ throw 'sidecar credential ACL failed' }}
foreach ($path in @('{key_path}','{hosts_path}')) {{
    & icacls.exe $path /inheritance:r /grant:r '{interactive_user}:R' 'Administrators:F' | Out-Null
    if ($LASTEXITCODE -ne 0) {{ throw "sidecar credential file ACL failed: $path" }}
}}
"""
    try:
        result = _execute_control_script(target, script, 'wcb-sidecar-credentials.ps1', timeout=60)
    except InteractiveAgentError as error:
        raise SidecarError(str(error)) from error
    if result.returncode != 0:
        raise SidecarError(result.stderr.decode('utf-8', 'replace').strip() or 'credential install failed')
