#!/bin/sh
# AdaptiveMemoryEngine container entrypoint.
#
# On first boot, if /data/memories.db is empty AND /seed-data has files,
# copy the seed data into /data. Existing Zeabur volumes with data are
# unaffected (memories.db already exists).
set -e

if [ ! -s /data/memories.db ]; then
  if [ -d /seed-data ] && [ "$(ls -A /seed-data 2>/dev/null)" ]; then
    echo "[Seed] Copying seed data to /data..."
    cp /seed-data/* /data/ 2>/dev/null || true
    echo "[Seed] Done."
  else
    echo "[Seed] /data empty and no seed-data bundled; starting with empty store."
  fi
fi

exec "$@"