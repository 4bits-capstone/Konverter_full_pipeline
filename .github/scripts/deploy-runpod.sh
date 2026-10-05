#!/usr/bin/env bash
# Point the existing RunPod pod at a new image, then wait until /api/health is up.
#
#   deploy-runpod.sh <image> [expected-version-prefix]
#
# Needs env: RUNPOD_API_KEY, RUNPOD_POD_ID, BACKEND_URL.
# Updating the same pod keeps its ID, proxy URL, env vars and network volume.
set -euo pipefail

IMAGE="${1:-}"
EXPECTED="${2:-}"

# An empty name is accepted by RunPod but leaves the pod unable to start.
if [[ ! "$IMAGE" =~ ^[a-z0-9._/-]+:[A-Za-z0-9._-]+$ ]]; then
  echo "::error::Invalid image name: '$IMAGE'. Nothing was changed."
  exit 1
fi
WAIT_SECONDS="${DEPLOY_WAIT_SECONDS:-600}"

: "${RUNPOD_API_KEY:?RUNPOD_API_KEY is not set}"
: "${RUNPOD_POD_ID:?RUNPOD_POD_ID is not set}"
: "${BACKEND_URL:?BACKEND_URL is not set}"
BACKEND_URL="${BACKEND_URL%/}"

echo "Deploying $IMAGE to pod $RUNPOD_POD_ID"

# RunPod responses are the full pod object, including its env vars (secrets) -
# never print them. Only read single fields, or show the body on an error status.
response_file="$(mktemp)"
trap 'rm -f "$response_file"' EXIT

# Refuse to deploy to a stopped pod: we'd change its image but never see it
# come up. Starting it is a deliberate (billable) choice left to a person.
status="$(curl -sS -o "$response_file" -w '%{http_code}' \
  "https://rest.runpod.io/v1/pods/$RUNPOD_POD_ID" \
  -H "Authorization: Bearer $RUNPOD_API_KEY")"
if [[ "$status" != 2* ]]; then
  echo "::error::Could not read pod $RUNPOD_POD_ID from RunPod (HTTP $status)"
  head -c 500 "$response_file"; echo
  exit 1
fi
pod_state="$(jq -r '.desiredStatus // empty' "$response_file")"
if [[ -n "$pod_state" && "$pod_state" != "RUNNING" ]]; then
  echo "::error::Pod $RUNPOD_POD_ID is $pod_state, not RUNNING. Start it in RunPod, then re-run this job. Nothing was changed."
  exit 1
fi

status="$(curl -sS -o "$response_file" -w '%{http_code}' -X PATCH \
  "https://rest.runpod.io/v1/pods/$RUNPOD_POD_ID" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"imageName\": \"$IMAGE\"}")"
if [[ "$status" != 2* ]]; then
  echo "::error::RunPod rejected the update (HTTP $status)"
  head -c 500 "$response_file"; echo
  exit 1
fi
echo "RunPod accepted the update (HTTP $status); pod is restarting on the new image"

# Give the old container time to stop so we don't mistake it for the new one.
sleep 30

deadline=$((SECONDS + WAIT_SECONDS))
while (( SECONDS < deadline )); do
  body="$(curl -sS --max-time 10 "$BACKEND_URL/api/health" 2>/dev/null || true)"
  health="$(jq -r '.status // empty' <<<"$body" 2>/dev/null || true)"
  version="$(jq -r '.version // empty' <<<"$body" 2>/dev/null || true)"
  if [[ "$health" == "ok" ]]; then
    if [[ -z "$EXPECTED" || "$version" == "$EXPECTED"* ]]; then
      echo "Healthy: version=${version:-unknown}"
      exit 0
    fi
    echo "Up, but still old version (${version:-unknown}); waiting..."
  else
    echo "Not healthy yet; waiting..."
  fi
  sleep 15
done

echo "::error::Backend did not report a healthy ${EXPECTED:-new} version within ${WAIT_SECONDS}s"
exit 1
