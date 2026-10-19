#!/bin/sh
# Starts the backend as the unprivileged "app" user.
#
# The container starts as root only so it can hand KONVERTER_DATA_DIR to
# "app": on RunPod that's a network volume whose existing files were written
# by root before the image stopped running as root. Anything not yet owned
# by "app" is chowned (a no-op after the first start), then root is dropped
# for good before uvicorn runs.
#
# If the volume won't accept the ownership change, the server keeps running
# as root with a warning instead of failing to start, so a storage quirk
# can't take the site down.
set -eu

if [ "$(id -u)" != "0" ]; then
  exec "$@"
fi

data_dir="${KONVERTER_DATA_DIR:-/app/data}"
mkdir -p "$data_dir"
find "$data_dir" ! -user app -exec chown app:app {} + 2>/dev/null || true

if [ -n "$(find "$data_dir" ! -user app -print -quit 2>/dev/null)" ]; then
  echo "WARNING: could not give $data_dir to the app user; running as root" >&2
  exec "$@"
fi

export HOME=/home/app
exec setpriv --reuid=app --regid=app --init-groups "$@"
