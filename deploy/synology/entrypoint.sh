#!/bin/sh
# Reconciles the 'mnemosyne' user's uid/gid with PUID/PGID at container
# start, so the /data bind mount ends up owned by your actual Synology
# account instead of a hardcoded guess baked into the image at build time.
#
# Find your account's ids over SSH: `id <your-dsm-username>`
# Then set PUID/PGID in the stack's environment (defaults to 1000/1000,
# same default as the linuxserver.io images).
set -e

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ "$(id -u mnemosyne)" != "$PUID" ]; then
  usermod -o -u "$PUID" mnemosyne
fi
if [ "$(id -g mnemosyne)" != "$PGID" ]; then
  groupmod -o -g "$PGID" mnemosyne
fi

mkdir -p /data/home
chown -R mnemosyne:mnemosyne /data

exec gosu mnemosyne mnemosyne mcp "$@"
