#!/usr/bin/env bash
# Runs on the Lightsail instance as the forced command of GitHub's deploy key,
# so that key can do nothing except deploy a frontend image tag.
#
# Install:  sudo install -m 755 konverter-deploy.sh /usr/local/bin/konverter-deploy
# GitHub connects with:  ssh <user>@<host> sha-abc1234
# (sshd passes "sha-abc1234" in SSH_ORIGINAL_COMMAND.)
#
# The container listens on 127.0.0.1:8080 only; the web server in front of it
# (ports 80/443) forwards visitors there, as with the original hand-built setup.
set -euo pipefail

IMAGE="ghcr.io/4bits-capstone/konverter-frontend"
NAME="konverter-frontend"
BIND="127.0.0.1"
PORT="8080"

TAG="${SSH_ORIGINAL_COMMAND:-${1:-}}"
if [[ ! "$TAG" =~ ^sha-[0-9a-f]{7,40}$ ]]; then
  echo "Refused: expected a tag like sha-abc1234, got '$TAG'" >&2
  exit 1
fi

# Remember what is running now, so a failed deploy can be put back.
previous="$(docker inspect --format '{{.Config.Image}}' "$NAME" 2>/dev/null || true)"

docker pull "$IMAGE:$TAG"

# Other running containers bound to our host port (e.g. the old hand-built
# one), with their restart policies so they can be put back exactly.
others=()
policies=()
for id in $(docker ps -q); do
  [[ "$(docker inspect --format '{{.Name}}' "$id")" == "/$NAME" ]] && continue
  if docker port "$id" 2>/dev/null | grep -qE ":$PORT\$"; then
    others+=("$id")
    policies+=("$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' "$id")")
  fi
done

restore_others() {
  local i
  for i in "${!others[@]}"; do
    docker update --restart="${policies[$i]:-no}" "${others[$i]}" >/dev/null || true
    docker start "${others[$i]}" >/dev/null || true
  done
}

start() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker run -d --name "$NAME" --restart unless-stopped \
    -p "$BIND:$PORT:80" "$1" >/dev/null
}

healthy() {
  for _ in $(seq 1 15); do
    if curl -fsS -o /dev/null "http://$BIND:$PORT/"; then
      return 0
    fi
    sleep 2
  done
  return 1
}

# Stopped, not removed, so they can be started again if this deploy fails.
if (( ${#others[@]} )); then
  echo "Stopping other container(s) on $BIND:$PORT: ${others[*]}"
  docker update --restart=no "${others[@]}" >/dev/null
  docker stop "${others[@]}" >/dev/null
fi

if start "$IMAGE:$TAG" && healthy; then
  echo "Deployed $IMAGE:$TAG"
  docker image prune -f >/dev/null || true
  exit 0
fi

echo "New version did not come up on $BIND:$PORT" >&2
docker rm -f "$NAME" >/dev/null 2>&1 || true
if [[ -n "$previous" ]]; then
  echo "Restoring $previous" >&2
  start "$previous" || true
fi
if (( ${#others[@]} )); then
  echo "Restarting the previous container(s): ${others[*]}" >&2
  restore_others
fi
exit 1
