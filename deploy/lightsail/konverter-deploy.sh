#!/usr/bin/env bash
# Runs on the Lightsail instance as the forced command of GitHub's deploy key,
# so that key can do nothing except deploy a frontend image tag.
#
# Install:  sudo install -m 755 konverter-deploy.sh /usr/local/bin/konverter-deploy
# GitHub connects with:  ssh <user>@<host> sha-abc1234
# (sshd passes "sha-abc1234" in SSH_ORIGINAL_COMMAND.)
set -euo pipefail

IMAGE="ghcr.io/4bits-capstone/konverter-frontend"
NAME="konverter-frontend"
PORT="${KONVERTER_PORT:-80}"

TAG="${SSH_ORIGINAL_COMMAND:-${1:-}}"
if [[ ! "$TAG" =~ ^sha-[0-9a-f]{7,40}$ ]]; then
  echo "Refused: expected a tag like sha-abc1234, got '$TAG'" >&2
  exit 1
fi

# Remember what is running now, so a failed deploy can be put back.
previous="$(docker inspect --format '{{.Config.Image}}' "$NAME" 2>/dev/null || true)"

docker pull "$IMAGE:$TAG"

# Any other container holding the port (e.g. the old hand-built one) is
# stopped, not removed, so it can be started again if this deploy fails.
others="$(docker ps -q --filter "publish=$PORT" | while read -r id; do
  [[ "$(docker inspect --format '{{.Name}}' "$id")" == "/$NAME" ]] || echo "$id"
done)"
if [[ -n "$others" ]]; then
  echo "Stopping other container(s) on port $PORT: $others"
  docker update --restart=no $others >/dev/null
  docker stop $others >/dev/null
fi

start() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker run -d --name "$NAME" --restart unless-stopped -p "$PORT:80" "$1" >/dev/null
}

healthy() {
  for _ in $(seq 1 15); do
    if curl -fsS -o /dev/null "http://localhost:$PORT/"; then
      return 0
    fi
    sleep 2
  done
  return 1
}

start "$IMAGE:$TAG"
if healthy; then
  echo "Deployed $IMAGE:$TAG"
  docker image prune -f >/dev/null || true
  exit 0
fi

echo "New version did not respond on port $PORT" >&2
docker rm -f "$NAME" >/dev/null 2>&1 || true
if [[ -n "$previous" ]]; then
  echo "Restoring $previous" >&2
  start "$previous"
elif [[ -n "$others" ]]; then
  echo "Restarting the previous container(s): $others" >&2
  docker update --restart=unless-stopped $others >/dev/null
  docker start $others >/dev/null
fi
exit 1
