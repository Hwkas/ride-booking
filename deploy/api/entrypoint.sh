#!/bin/sh
set -e

# compose waits for the db healthcheck, so the database is already up here.
echo "Applying migrations.."
alembic upgrade head

echo "Seeding admin user (idempotent).."
python -m scripts.seed

exec "$@"
