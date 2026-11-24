# Same major version as the db service, so pg_dump and pg_restore match the server.
FROM postgres:16

COPY backup.sh restore.sh run.sh /ops/
RUN chmod +x /ops/*.sh

# Connection settings come from compose (PGHOST, PGUSER, PGPASSWORD, PGDATABASE).
ENTRYPOINT ["/ops/run.sh"]
