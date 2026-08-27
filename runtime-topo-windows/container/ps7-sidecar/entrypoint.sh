#!/bin/sh
set -eu

test -n "${WCB_AUTHORIZED_KEY:-}"
if [ ! -f /etc/ssh/keys/ssh_host_ed25519_key ]; then
  ssh-keygen -q -t ed25519 -N '' -f /etc/ssh/keys/ssh_host_ed25519_key
fi
install -d -m 0700 -o wcb-task -g wcb-task /home/wcb-task/.ssh
printf '%s\n' "$WCB_AUTHORIZED_KEY" > /home/wcb-task/.ssh/authorized_keys
chown wcb-task:wcb-task /home/wcb-task/.ssh/authorized_keys
chmod 0600 /home/wcb-task/.ssh/authorized_keys
install -d -m 0700 -o wcb-task -g wcb-task /srv/wcb/runs
exec /usr/sbin/sshd -D -e
