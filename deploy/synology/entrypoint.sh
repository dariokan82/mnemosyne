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

# Second mode: periodic consolidation instead of the MCP server.
# Nothing in the MCP server process (mcp_server.py) or this script ever
# triggered `mnemosyne sleep` on its own -- there is no background
# scheduler anywhere in this image. Without an external driver, working
# memory accumulates indefinitely and episodic promotion / tiered
# degradation never run. This mode is that external driver, run as a
# second compose service (mnemosyne-sleep) against the same bind-mounted
# DB. WAL mode + busy_timeout are already on for the sqlite connection
# (see core/memory.py::_get_connection), so a second writer is safe.
#
# --all-sessions is required, not optional. Bare `mnemosyne sleep` routes
# to the session-scoped BeamMemory.sleep(), which filters
# `COALESCE(session_id,'default') = 'default'` -- but every write through
# the MCP server is tagged `mcp_<bank>` (mcp_tools.py::_create_instance),
# so the two sets never intersect and the loop logs "No old working
# memories to consolidate" forever while nothing is consolidated. That
# matters beyond the missing summaries: _trim_working_memory() deletes
# working_memory rows with consolidated_at IS NULL past
# WORKING_MEMORY_TTL_HOURS (168h), and exempts consolidated ones. Sleep
# is what saves a memory from the reaper, so a sleep that matches nothing
# is silent data loss on a 7-day fuse.
if [ "$1" = "sleep-loop" ]; then
  interval="${MNEMOSYNE_SLEEP_INTERVAL_SECONDS:-21600}"
  echo "mnemosyne-sleep: starting periodic consolidation loop (every ${interval}s)"
  exec gosu mnemosyne sh -c '
    while true; do
      echo "[$(date -Iseconds)] running mnemosyne sleep --all-sessions"
      mnemosyne sleep --all-sessions \
        || echo "[$(date -Iseconds)] mnemosyne sleep failed (continuing)"
      sleep "'"$interval"'"
    done
  '
fi

exec gosu mnemosyne mnemosyne mcp "$@"
