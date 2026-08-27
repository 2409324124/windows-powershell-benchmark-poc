#!/bin/sh
set -eu

test "$#" -eq 2
test "$1" = '--root'
root=$2
if [ -n "${WCB_MANIFEST_AUDIT:-}" ]; then
  printf '%s' "$root" > "$WCB_MANIFEST_AUDIT"
fi
find "$root" -type f -printf '%P\n'
