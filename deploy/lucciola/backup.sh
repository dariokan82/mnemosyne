#!/bin/sh
# Called by mnemosyne-backup.service. Runs backup.py in the production image
# as dario (1000), so backups are owned by the same user as the data.
set -e
exec docker run --rm --user 1000:1000 --entrypoint python \
  -v /srv/mnemosyne/data:/data \
  -v /srv/mnemosyne/backups:/backups \
  -v /home/dario/src/mnemosyne/deploy/lucciola/backup.py:/backup.py:ro \
  mnemosyne-mcp:lucciola /backup.py
