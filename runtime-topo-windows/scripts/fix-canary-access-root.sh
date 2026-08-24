#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root." >&2
  exit 2
fi

DOMAIN="wcb-canary-transport-001"
BASE_DIR="/mnt/PM983/windows-benchmark/base"
BASE="$BASE_DIR/ws2025-opencode-1.18.21-v001.qcow2"
RUNS="/mnt/PM983/windows-benchmark/runs"
RUN="$RUNS/canary-transport-001"
OVERLAY="$RUN/overlay.qcow2"
NVRAM="$RUN/VARS.fd"

STATE="$(virsh --connect qemu:///system domstate "$DOMAIN")"
if [[ "$STATE" != "shut off" ]]; then
  echo "Refusing ACL change while domain state is '$STATE'." >&2
  exit 3
fi
for path in "$BASE_DIR" "$BASE" "$RUNS" "$RUN" "$OVERLAY" "$NVRAM"; do
  if [[ ! -e "$path" ]]; then
    echo "Required path missing: $path" >&2
    exit 4
  fi
done

chown miku:kvm "$RUN" "$OVERLAY" "$NVRAM"
chmod 0770 "$RUN"
chmod 0660 "$OVERLAY" "$NVRAM"

ls -ld "$RUN"
ls -l "$OVERLAY" "$NVRAM"
