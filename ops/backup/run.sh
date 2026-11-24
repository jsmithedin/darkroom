#!/bin/sh
# Sidecar entrypoint: back up at start-up (unless a dump from the last 12 hours exists, so a
# restart loop cannot pile up dumps), then every day at BACKUP_HOUR (UTC, default 2).
# `once` runs a single backup and exits; any other command is run as given.
set -eu

case "${1:-loop}" in
  once) exec /ops/backup.sh ;;
  loop) ;;
  *) exec "$@" ;;
esac

HOUR="${BACKUP_HOUR:-2}"
case "$HOUR" in
  [0-9] | 1[0-9] | 2[0-3]) ;;
  *) echo "backup: BACKUP_HOUR must be 0-23, got '$HOUR'" >&2; exit 64 ;;
esac

# PID 1 ignores SIGTERM unless it has a handler; this makes `docker compose stop` prompt.
trap 'exit 143' TERM INT

until pg_isready -q; do sleep 2; done
recent="$(find "${BACKUP_DIR:-/backups}" -maxdepth 1 -name 'darkroom-*.dump' -mmin -720 2> /dev/null | head -1)"
if [ -z "$recent" ]; then
  /ops/backup.sh || echo "backup: FAILED" >&2
fi
while true; do
  now="$(date -u +%s)"
  next="$(date -u -d "$(date -u +%Y-%m-%d) $HOUR:00:00" +%s)"
  [ "$next" -le "$now" ] && next=$((next + 86400))
  sleep $((next - now)) &
  wait $!
  /ops/backup.sh || echo "backup: FAILED" >&2
done
