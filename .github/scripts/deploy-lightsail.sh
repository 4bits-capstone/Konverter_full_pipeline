#!/usr/bin/env bash
# Ask the Lightsail instance to deploy a frontend image tag.
#
#   deploy-lightsail.sh <tag>        e.g. sha-abc1234
#
# Needs env: LIGHTSAIL_SSH_KEY, LIGHTSAIL_KNOWN_HOSTS, LIGHTSAIL_HOST, LIGHTSAIL_USER.
# The key is restricted on the server to /usr/local/bin/konverter-deploy
# (deploy/lightsail/konverter-deploy.sh), which receives the tag as its only
# input, pulls the image, swaps the container and rolls back if it won't serve.
set -euo pipefail

TAG="${1:-}"
if [[ ! "$TAG" =~ ^sha-[0-9a-f]{7,40}$ ]]; then
  echo "::error::Invalid tag: '$TAG'. Nothing was changed."
  exit 1
fi

: "${LIGHTSAIL_SSH_KEY:?LIGHTSAIL_SSH_KEY is not set}"
: "${LIGHTSAIL_KNOWN_HOSTS:?LIGHTSAIL_KNOWN_HOSTS is not set}"
: "${LIGHTSAIL_HOST:?LIGHTSAIL_HOST is not set}"
: "${LIGHTSAIL_USER:?LIGHTSAIL_USER is not set}"

dir="$(mktemp -d)"
trap 'rm -rf "$dir"' EXIT
printf '%s\n' "$LIGHTSAIL_SSH_KEY" > "$dir/key"
printf '%s\n' "$LIGHTSAIL_KNOWN_HOSTS" > "$dir/known_hosts"
chmod 600 "$dir/key"

echo "Deploying ghcr.io/4bits-capstone/konverter-frontend:$TAG to $LIGHTSAIL_HOST"
# Host key is pinned: connecting to anything else fails instead of trusting it.
ssh -i "$dir/key" \
  -o IdentitiesOnly=yes \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile="$dir/known_hosts" \
  -o ConnectTimeout=20 \
  "$LIGHTSAIL_USER@$LIGHTSAIL_HOST" "$TAG"
