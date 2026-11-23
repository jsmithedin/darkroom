#!/bin/sh
# Restore a dump into a named database.
#   restore.sh <dump> <database>             create <database> from the dump (it must not exist)
#   restore.sh <dump> <database> --replace   swap the restored copy in for an existing <database>
# The dump is restored into a temporary database first and only swapped in once the restore has
# fully succeeded, so a bad dump never touches the existing database. With --replace the old
# database is kept, renamed <database>_old_<time>; drop it yourself when you are happy.
# Stop the app first when replacing the live database. Prints row counts afterwards.
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
if [ "${#TARGET}" -gt 30 ]; then
  echo "restore: database name is too long (30 characters at most)" >&2
  exit 64
fi
if [ -n "$REPLACE" ] && [ "$REPLACE" != "--replace" ]; then
  echo "restore: unknown option $REPLACE" >&2
  exit 64
fi
pg_restore --list "$DUMP" > /dev/null || { echo "restore: $DUMP is not a valid dump" >&2; exit 65; }

sql() { psql -d postgres -v ON_ERROR_STOP=1 -Atc "$1"; }
exists="$(sql "SELECT 1 FROM pg_database WHERE datname = '$TARGET'")"
if [ -n "$exists" ] && [ "$REPLACE" != "--replace" ]; then
  echo "restore: database $TARGET already exists; pass --replace to swap it out" >&2
  exit 73
fi

TMPDB="${TARGET}_restore_$$"
OLD="${TARGET}_old_$(date -u +%Y%m%d%H%M%S)"
cleanup() { sql "DROP DATABASE IF EXISTS \"$TMPDB\" WITH (FORCE)" > /dev/null 2>&1 || true; }
trap cleanup EXIT

sql "CREATE DATABASE \"$TMPDB\"" > /dev/null
if ! pg_restore --no-owner --exit-on-error --single-transaction -d "$TMPDB" "$DUMP"; then
  echo "restore: failed; nothing was changed" >&2
  exit 1
fi

if [ -n "$exists" ]; then
  # no one may be connected to a database being renamed
  sql "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$TARGET' AND pid <> pg_backend_pid()" > /dev/null
  sql "ALTER DATABASE \"$TARGET\" RENAME TO \"$OLD\"" > /dev/null
  echo "restore: kept the previous database as $OLD"
fi
sql "ALTER DATABASE \"$TMPDB\" RENAME TO \"$TARGET\"" > /dev/null
trap - EXIT

echo "restore: restored $DUMP into $TARGET. Row counts:"
for table in rolls stock_movements; do
  count="$(psql -d "$TARGET" -Atc "SELECT count(*) FROM $table")" || {
    echo "restore: table $table is missing from $TARGET" >&2
    exit 1
  }
  echo "  $table: $count"
done
