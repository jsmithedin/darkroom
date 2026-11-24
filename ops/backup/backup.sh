#!/bin/sh
# Dump the database to /backups/darkroom-YYYYMMDD.dump (custom format) and prune old dumps.
# A dump is written to a temporary file, checked with `pg_restore --list` (which reads the table
# of contents, so `pg_dump` exiting 0 is the real guarantee) and only then moved into place, so
# a failed run never leaves a half-written dump. An existing dump is never overwritten: a second
# run on the same day writes darkroom-YYYYMMDD-HHMMSS.dump.
# Pruning removes dumps older than RETENTION_DAYS (default 14) but always keeps the newest
# KEEP_MIN (default 3), so a run of bad or empty dumps cannot push out the last good ones.
set -eu

DIR="${BACKUP_DIR:-/backups}"
DAYS="${RETENTION_DAYS:-14}"
KEEP="${KEEP_MIN:-3}"
STAMP="$(date -u +%Y%m%d)"
OUT="$DIR/darkroom-$STAMP.dump"
[ ! -e "$OUT" ] || OUT="$DIR/darkroom-$STAMP-$(date -u +%H%M%S).dump"

mkdir -p "$DIR"
TMP="$(mktemp "$DIR/.darkroom-XXXXXX.partial")"
trap 'rm -f "$TMP"' EXIT

pg_dump -Fc --no-owner --file "$TMP" "${PGDATABASE:-darkroom}"
pg_restore --list "$TMP" > /dev/null
chmod 644 "$TMP"  # readable on the host, where the container runs as root
mv "$TMP" "$OUT"
echo "backup: wrote $OUT ($(wc -c < "$OUT") bytes)"

# leftovers from a run that was killed
find "$DIR" -maxdepth 1 -name '.darkroom-*.partial' -type f -mmin +1440 -delete

# `-mtime +N` means older than N whole days, so +(DAYS-1) removes dumps of DAYS days or more
ls -1 "$DIR"/darkroom-*.dump | sort | head -n "-$KEEP" | while read -r old; do
  find "$old" -maxdepth 0 -type f -mtime "+$((DAYS - 1))" -print -delete |
    sed 's/^/backup: removed old dump /'
done
