#!/bin/sh
set -e

# Seul le service « backend » prépare la base (le service « worker » attend).
if [ "${INITIALISER:-0}" = "1" ]; then
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput --verbosity 0
fi

exec "$@"
