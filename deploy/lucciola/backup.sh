#!/bin/sh
# Called by mnemosyne-backup.service. Runs backup.py in the production image
# as dario (1000), so backups are owned by the same user as the data.
#
# The HDD mirror is mounted into the container only if /mnt/hdd is a real
# mountpoint. If the drive is dead or unmounted, /mnt/hdd is just an empty
# directory on the SSD, and binding it would quietly fill the SSD instead.
set -e
MIRROR=""
if mountpoint -q /mnt/hdd; then
  MIRROR="-v /mnt/hdd/mnemosyne-backups:/mirror"
fi
exec docker run --rm --user 1000:1000 --entrypoint python \
  -v /srv/mnemosyne/data:/data \
  -v /srv/mnemosyne/backups:/backups \
  $MIRROR \
  -v /home/dario/src/mnemosyne/deploy/lucciola/backup.py:/backup.py:ro \
  mnemosyne-mcp:lucciola /backup.py
