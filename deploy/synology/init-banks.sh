#!/bin/sh
# Create the seven project banks in the running mnemosyne-mcp container.
#
# Run once after the container is up and healthy, from the Synology host
# shell or a Portainer console:
#
#   sh deploy/synology/init-banks.sh
#
# Idempotent -- re-running just reports "already exists" for banks that
# are already there (mnemosyne bank create exits non-zero in that case,
# which is why each call is followed by `|| true`).

CONTAINER="${MNEMOSYNE_CONTAINER:-mnemosyne-mcp}"
BANKS="personal candle six-dimes karma-police signal-lost the-last-supper quiet-mile"

for bank in $BANKS; do
  echo "--- $bank ---"
  docker exec "$CONTAINER" mnemosyne bank create "$bank" || true
done

echo
echo "--- current banks ---"
docker exec "$CONTAINER" mnemosyne bank list
