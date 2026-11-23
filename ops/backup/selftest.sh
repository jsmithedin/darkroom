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

i=0
until docker exec "$NAME-db" pg_isready -U darkroom -d darkroom > /dev/null 2>&1; do
  i=$((i + 1)); [ "$i" -lt 60 ] || { echo "database did not start" >&2; exit 1; }
  sleep 1
done
sleep 2  # the init script restarts the server once

tool /usr/bin/psql -d darkroom -v ON_ERROR_STOP=1 -c "
  CREATE EXTENSION IF NOT EXISTS citext;
  CREATE TABLE rolls (id serial PRIMARY KEY, film citext NOT NULL, note text);
  CREATE TABLE stock_movements (id serial PRIMARY KEY, rolls int NOT NULL);
  INSERT INTO rolls (film, note) SELECT 'Film ' || g, 'é ünïcode ' || g FROM generate_series(1, 117) g;
  INSERT INTO stock_movements (rolls) SELECT g FROM generate_series(1, 49) g;" > /dev/null

# an old dump is removed, a recent one kept
touch -d '20 days ago' "$DIR/darkroom-20000101.dump"
touch "$DIR/darkroom-29990101.dump"
tool /ops/run.sh once
[ ! -e "$DIR/darkroom-20000101.dump" ] || { echo "FAIL: old dump kept" >&2; exit 1; }
[ -e "$DIR/darkroom-29990101.dump" ] || { echo "FAIL: recent dump removed" >&2; exit 1; }
DUMP="$(ls "$DIR"/darkroom-2[0-9][0-9][0-9][01][0-9][0-3][0-9].dump | grep -v 2999 | head -1)"
[ -s "$DUMP" ] || { echo "FAIL: no dump written" >&2; exit 1; }

out="$(tool /ops/restore.sh "/backups/$(basename "$DUMP")" scratch)"
echo "$out"
echo "$out" | grep -q "rolls: 117" || { echo "FAIL: rolls count differs" >&2; exit 1; }
echo "$out" | grep -q "stock_movements: 49" || { echo "FAIL: stock_movements count differs" >&2; exit 1; }
note="$(tool /usr/bin/psql -d scratch -Atc "SELECT note FROM rolls WHERE film = 'FILM 7'")"
[ "$note" = "é ünïcode 7" ] || { echo "FAIL: data differs ($note)" >&2; exit 1; }

# restoring over an existing database needs --replace; a bad dump or name is refused
if tool /ops/restore.sh "/backups/$(basename "$DUMP")" scratch > /dev/null 2>&1; then
  echo "FAIL: restored over an existing database" >&2; exit 1
fi
tool /ops/restore.sh "/backups/$(basename "$DUMP")" scratch --replace > /dev/null
echo "garbage" > "$DIR/bad.dump"
if tool /ops/restore.sh /backups/bad.dump other > /dev/null 2>&1; then
  echo "FAIL: accepted a bad dump" >&2; exit 1
fi
if tool /ops/restore.sh "/backups/$(basename "$DUMP")" 'bad;name' > /dev/null 2>&1; then
  echo "FAIL: accepted a bad database name" >&2; exit 1
fi
echo "backup selftest: OK"
