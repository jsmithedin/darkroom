#!/bin/sh
# End-to-end check of backup.sh and restore.sh against a throwaway Postgres: back up a database,
# restore it into a scratch database and compare row counts. Needs Docker.
#   ops/backup/selftest.sh
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
NAME="darkroom-backup-test-$$"
NET="$NAME"
DIR="$(mktemp -d)"
IMAGE="$NAME:latest"

cleanup() {
  docker rm -f "$NAME-db" > /dev/null 2>&1 || true
  docker network rm "$NET" > /dev/null 2>&1 || true
  docker rmi "$IMAGE" > /dev/null 2>&1 || true
  rm -rf "$DIR"
}
trap cleanup EXIT

docker build -q -t "$IMAGE" "$HERE" > /dev/null
docker network create "$NET" > /dev/null
docker run -d --name "$NAME-db" --network "$NET" -e POSTGRES_USER=darkroom \
  -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=darkroom postgres:16 > /dev/null

tool() { # run a command in the backup image against the throwaway database
  entry="$1"
  shift
  docker run --rm --network "$NET" -v "$DIR:/backups" \
    -e PGHOST="$NAME-db" -e PGUSER=darkroom -e PGPASSWORD=pw -e PGDATABASE=darkroom \
    --entrypoint "$entry" "$IMAGE" "$@"
}

# over TCP: the temporary server the image starts for its init scripts has no TCP listener
compose_run() { # as the README runs it: through the image's own entrypoint
  docker run --rm --network "$NET" -v "$DIR:/backups" \
    -e PGHOST="$NAME-db" -e PGUSER=darkroom -e PGPASSWORD=pw -e PGDATABASE=darkroom \
    "$IMAGE" "$@"
}

i=0
until tool /usr/bin/pg_isready -q; do
  i=$((i + 1)); [ "$i" -lt 60 ] || { echo "database did not start" >&2; exit 1; }
  sleep 1
done

tool /usr/bin/psql -d darkroom -v ON_ERROR_STOP=1 -c "
  CREATE EXTENSION IF NOT EXISTS citext;
  CREATE TABLE rolls (id serial PRIMARY KEY, film citext NOT NULL, note text);
  CREATE TABLE stock_movements (id serial PRIMARY KEY, rolls int NOT NULL);
  INSERT INTO rolls (film, note) SELECT 'Film ' || g, 'é ünïcode ' || g FROM generate_series(1, 117) g;
  INSERT INTO stock_movements (rolls) SELECT g FROM generate_series(1, 49) g;" > /dev/null

# retention: old dumps go, but the newest KEEP_MIN (3) stay however old they are
for d in 20000101 20000102 20000103 20000104; do
  echo x > "$DIR/darkroom-$d.dump"
  touch -d '20 days ago' "$DIR/darkroom-$d.dump"
done
touch "$DIR/.darkroom-OLD.partial" -d '3 days ago'
tool /ops/run.sh once
[ ! -e "$DIR/darkroom-20000101.dump" ] || { echo "FAIL: old dump kept" >&2; exit 1; }
[ ! -e "$DIR/darkroom-20000102.dump" ] || { echo "FAIL: old dump kept" >&2; exit 1; }
[ -e "$DIR/darkroom-20000103.dump" ] || { echo "FAIL: newest-3 dump removed" >&2; exit 1; }
[ ! -e "$DIR/.darkroom-OLD.partial" ] || { echo "FAIL: stale partial kept" >&2; exit 1; }
DUMP="$(ls "$DIR"/darkroom-2026*.dump "$DIR"/darkroom-2[1-9]*.dump 2> /dev/null | tail -1)"
[ -s "$DUMP" ] || { echo "FAIL: no dump written" >&2; exit 1; }
# a second run the same day keeps the first dump
tool /ops/run.sh once > /dev/null
[ -s "$DUMP" ] || { echo "FAIL: first dump was replaced" >&2; exit 1; }
ls "$DIR"/darkroom-[0-9]*-[0-9]*.dump > /dev/null 2>&1 || { echo "FAIL: no second dump" >&2; exit 1; }
# a bad BACKUP_HOUR stops the sidecar instead of looping
if docker run --rm --network "$NET" -e PGHOST="$NAME-db" -e PGUSER=darkroom -e PGPASSWORD=pw \
  -e BACKUP_HOUR=24 -v "$DIR:/backups" "$IMAGE" > /dev/null 2>&1; then
  echo "FAIL: accepted BACKUP_HOUR=24" >&2; exit 1
fi

out="$(compose_run /ops/restore.sh "/backups/$(basename "$DUMP")" scratch)"
echo "$out"
echo "$out" | grep -q "rolls: 117" || { echo "FAIL: rolls count differs" >&2; exit 1; }
echo "$out" | grep -q "stock_movements: 49" || { echo "FAIL: stock_movements count differs" >&2; exit 1; }
note="$(tool /usr/bin/psql -d scratch -Atc "SELECT note FROM rolls WHERE film = 'FILM 7'")"
[ "$note" = "é ünïcode 7" ] || { echo "FAIL: data differs ($note)" >&2; exit 1; }

# restoring over an existing database needs --replace; a bad dump or name is refused
if tool /ops/restore.sh "/backups/$(basename "$DUMP")" scratch > /dev/null 2>&1; then
  echo "FAIL: restored over an existing database" >&2; exit 1
fi
# a truncated dump passes `--list` but fails to restore: the existing database must survive
head -c 2000 "$DUMP" > "$DIR/trunc.dump"
if tool /ops/restore.sh /backups/trunc.dump scratch --replace > /dev/null 2>&1; then
  echo "FAIL: restored a truncated dump" >&2; exit 1
fi
n="$(tool /usr/bin/psql -d scratch -Atc "SELECT count(*) FROM rolls")"
[ "$n" = 117 ] || { echo "FAIL: --replace damaged the database on a failed restore" >&2; exit 1; }
out="$(tool /ops/restore.sh "/backups/$(basename "$DUMP")" scratch --replace)"
echo "$out" | grep -q "kept the previous database as scratch_old_" || { echo "FAIL: old not kept" >&2; exit 1; }
echo "garbage" > "$DIR/bad.dump"
if tool /ops/restore.sh /backups/bad.dump other > /dev/null 2>&1; then
  echo "FAIL: accepted a bad dump" >&2; exit 1
fi
if tool /ops/restore.sh "/backups/$(basename "$DUMP")" 'bad;name' > /dev/null 2>&1; then
  echo "FAIL: accepted a bad database name" >&2; exit 1
fi
echo "backup selftest: OK"
