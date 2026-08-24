#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this script as root after reviewing it." >&2
  exit 2
fi

DOMAIN="ws2025-base-build-v001"
ROOT="/mnt/PM983/windows-benchmark"
SOURCE="$ROOT/overlays/ws2025-base-build-v001.qcow2"
SOURCE_NVRAM="$ROOT/nvram/ws2025-base-build-v001_VARS.fd"
DOMAIN_UUID="9194c01f-e29f-400a-8cf3-5c125e5efc48"
SOURCE_TPM="/var/lib/libvirt/swtpm/$DOMAIN_UUID"
BASE_DIR="$ROOT/base"
BASE="$BASE_DIR/ws2025-opencode-1.18.21-v001.qcow2"
BASE_NVRAM="$BASE_DIR/ws2025-opencode-1.18.21-v001_VARS.fd"
BASE_TPM="$BASE_DIR/ws2025-opencode-1.18.21-v001_tpm"
TEMP="$BASE.tmp"
CONFIG="/home/miku/runtime-topo-windows/config"
BUILD_XML="$CONFIG/ws2025-base-build-v001.xml"
TEMPLATE_XML="$CONFIG/ws2025-domain-template.xml"

STATE="$(virsh --connect qemu:///system domstate "$DOMAIN")"
if [[ "$STATE" != "shut off" ]]; then
  echo "Refusing to freeze: $DOMAIN state is '$STATE', expected 'shut off'." >&2
  exit 3
fi
if [[ ! -f "$SOURCE" ]]; then
  echo "Source disk missing: $SOURCE" >&2
  exit 4
fi
if [[ ! -f "$SOURCE_NVRAM" || ! -d "$SOURCE_TPM" ]]; then
  echo "Canonical NVRAM or TPM state is missing." >&2
  exit 6
fi
if [[ -e "$BASE" || -e "$TEMP" || -e "$BASE_NVRAM" || -e "$BASE_TPM" ]]; then
  echo "Refusing to overwrite existing base or temp image." >&2
  exit 5
fi

install -d -m 2770 -o root -g libvirt "$BASE_DIR" "$ROOT/runs" "$ROOT/templates"
virsh --connect qemu:///system dumpxml --inactive "$DOMAIN" > "$BUILD_XML"
python3 /home/miku/runtime-topo-windows/scripts/render-domain-template.py "$BUILD_XML" "$TEMPLATE_XML"

qemu-img convert -p -O qcow2 -o compat=1.1,lazy_refcounts=on "$SOURCE" "$TEMP"
qemu-img check "$TEMP"
chown root:libvirt "$TEMP"
chmod 0440 "$TEMP"
mv "$TEMP" "$BASE"
sha256sum "$BASE" > "$BASE.sha256"
cp --reflink=auto --preserve=all "$SOURCE_NVRAM" "$BASE_NVRAM"
cp -a "$SOURCE_TPM" "$BASE_TPM"
chown -R root:libvirt "$BASE_NVRAM" "$BASE_TPM"
chmod 0440 "$BASE_NVRAM"
find "$BASE_TPM" -type d -exec chmod 0750 {} +
find "$BASE_TPM" -type f -exec chmod 0640 {} +
sha256sum "$BASE_NVRAM" > "$BASE_NVRAM.sha256"
find "$BASE_TPM" -type f -print0 | sort -z | xargs -0 sha256sum > "$BASE_TPM.sha256"
chown root:libvirt "$BASE.sha256"
chown root:libvirt "$BASE_NVRAM.sha256" "$BASE_TPM.sha256"
chmod 0440 "$BASE.sha256" "$BASE_NVRAM.sha256" "$BASE_TPM.sha256"

echo "Frozen base: $BASE"
cat "$BASE.sha256"
