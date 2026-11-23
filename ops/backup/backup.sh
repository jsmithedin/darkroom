#!/bin/sh
# Dump the database to /backups/darkroom-YYYYMMDD.dump (custom format) and delete dumps older
# than RETENTION_DAYS (default 14). A dump is written to a temporary name, checked with
# `pg_restore --list` and only then moved into place, so a failed run never leaves a bad
# dump that looks good. Running twice on one day replaces that day's dump.
set -eu

DIR="${BACKUP_DIR:-/backups}"
DAYS="${RETENTION_DAYS:-14}"
STAMP="$(date -u +%Y%m%d)"
OUT="$DIR/darkroom-$STAMP.dump"
TMP="$DIR/.darkroom-$STAMP.dump.partial"

mkdir -p "$DIR"
trap 'rm -f "$TMP"' EXIT

pg_dump -Fc --no-owner --file "$TMP" "${PGDATABASE:-darkroom}"
pg_restore --list "$TMP" > /dev/null
chmod 644 "$TMP"  # readable on the host, where the container runs as root
mv "$TMP" "$OUT"
echo "backup: wrote $OUT ($(wc -c < "$OUT") bytes)"

find "$DIR" -maxdepth 1 -name 'darkroom-*.dump' -type f -mtime "+$DAYS" -print -delete |
  sed 's/^/backup: removed old dump /'
