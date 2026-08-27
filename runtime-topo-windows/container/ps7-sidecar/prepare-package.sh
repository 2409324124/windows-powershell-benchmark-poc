#!/bin/sh
set -eu

url='https://github.com/PowerShell/PowerShell/releases/download/v7.6.4/powershell_7.6.4-1.deb_amd64.deb'
expected='e5688e0569568d48051c49d3e93504cde47af709cdaaabd9a8892bc676b3bdf3'
directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/.cache
package="$directory/powershell.deb"
mkdir -p "$directory"
curl -fL --retry 5 --retry-all-errors --connect-timeout 20 --max-time 180 -C - "$url" -o "$package"
actual=$(sha256sum "$package" | awk '{print $1}')
if [ "$actual" != "$expected" ]; then
  printf 'PowerShell package integrity check failed\n' >&2
  exit 1
fi
