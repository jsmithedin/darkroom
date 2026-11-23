#!/bin/sh
# Sidecar entrypoint: back up once at start-up, then every day at BACKUP_HOUR (UTC, default 02).
# Pass `once` to run a single backup and exit (used for testing), or any other command to run it.
set -eu

case "${1:-loop}" in
  once) exec /ops/backup.sh ;;
  loop) ;;
  *) exec "$@" ;;
esac

HOUR="${BACKUP_HOUR:-2}"
until pg_isready -q; do sleep 2; done
/ops/backup.sh || echo "backup: FAILED" >&2
while true; do
  now="$(date -u +%s)"
  next="$(date -u -d "$(date -u +%Y-%m-%d) $HOUR:00:00" +%s)"
  [ "$next" -le "$now" ] && next=$((next + 86400))
  sleep $((next - now))
  /ops/backup.sh || echo "backup: FAILED" >&2
done
