#!/bin/sh
# Restore a dump into a named database.
#   restore.sh <dump> <database>             create <database> and restore into it (it must not exist)
#   restore.sh <dump> <database> --replace   drop <database> first (disaster recovery; stop the app)
# Prints the row counts of the main tables afterwards so you can compare them.
set -eu

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  echo "usage: restore.sh <dump> <database> [--replace]" >&2
  exit 64
fi
DUMP="$1"
TARGET="$2"
REPLACE="${3:-}"

[ -f "$DUMP" ] || { echo "restore: no such file: $DUMP" >&2; exit 66; }
case "$TARGET" in
  *[!A-Za-z0-9_]* | "") echo "restore: database name may only use letters, digits and _" >&2; exit 64 ;;
esac
if [ -n "$REPLACE" ] && [ "$REPLACE" != "--replace" ]; then
  echo "restore: unknown option $REPLACE" >&2
  exit 64
fi
pg_restore --list "$DUMP" > /dev/null || { echo "restore: $DUMP is not a valid dump" >&2; exit 65; }

exists="$(psql -d postgres -Atc "SELECT 1 FROM pg_database WHERE datname = '$TARGET'")"
if [ -n "$exists" ]; then
  if [ "$REPLACE" != "--replace" ]; then
    echo "restore: database $TARGET already exists; pass --replace to drop it first" >&2
    exit 73
  fi
  psql -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE \"$TARGET\" WITH (FORCE)"
fi
psql -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$TARGET\""

# Citext is created by the dump itself; --no-owner keeps it independent of the original role.
pg_restore --no-owner --exit-on-error -d "$TARGET" "$DUMP"

echo "restore: restored $DUMP into $TARGET. Row counts:"
for table in rolls stock_movements; do
  count="$(psql -d "$TARGET" -Atc "SELECT count(*) FROM $table" 2>/dev/null || echo 'n/a')"
  echo "  $table: $count"
done
