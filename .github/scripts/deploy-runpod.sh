#!/usr/bin/env bash
# Point the existing RunPod pod at a new image, then wait until /api/health is up.
# If the new image never becomes healthy, put the previous image back.
#
#   deploy-runpod.sh <image> [expected-version-prefix]
#
# Needs env: RUNPOD_API_KEY, RUNPOD_POD_ID, BACKEND_URL.
# Updating the same pod keeps its ID, proxy URL, env vars and network volume.
set -euo pipefail

IMAGE="${1:-}"
EXPECTED="${2:-}"
IMAGE_PATTERN='^[a-z0-9._/-]+:[A-Za-z0-9._-]+$'

# An empty name is accepted by RunPod but leaves the pod unable to start.
if [[ ! "$IMAGE" =~ $IMAGE_PATTERN ]]; then
  echo "::error::Invalid image name: '$IMAGE'. Nothing was changed."
  exit 1
fi
WAIT_SECONDS="${DEPLOY_WAIT_SECONDS:-600}"
# Seconds to let the old container stop so we don't mistake it for the new one.
SETTLE_SECONDS="${DEPLOY_SETTLE_SECONDS:-30}"
POLL_SECONDS="${DEPLOY_POLL_SECONDS:-15}"

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
# Reading a pod returns "image"; updating one takes "imageName".
previous="$(jq -r '.image // .imageName // empty' "$response_file")"
echo "Currently running: ${previous:-unknown}"

# set_image <image>: returns non-zero if RunPod rejects the update.
set_image() {
  local code
  code="$(curl -sS -o "$response_file" -w '%{http_code}' -X PATCH \
    "https://rest.runpod.io/v1/pods/$RUNPOD_POD_ID" \
    -H "Authorization: Bearer $RUNPOD_API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"imageName\": \"$1\"}")"
  if [[ "$code" != 2* ]]; then
    echo "::error::RunPod rejected the update to $1 (HTTP $code)"
    head -c 500 "$response_file"; echo
    return 1
  fi
  echo "RunPod accepted the update (HTTP $code); pod is restarting on $1"
}

# wait_healthy <expected-version-prefix>: an empty prefix accepts any version.
wait_healthy() {
  local expected="$1" deadline body health version
  sleep "$SETTLE_SECONDS"
  deadline=$((SECONDS + WAIT_SECONDS))
  while (( SECONDS < deadline )); do
    body="$(curl -sS --max-time 10 "$BACKEND_URL/api/health" 2>/dev/null || true)"
    health="$(jq -r '.status // empty' <<<"$body" 2>/dev/null || true)"
    version="$(jq -r '.version // empty' <<<"$body" 2>/dev/null || true)"
    if [[ "$health" == "ok" ]]; then
      if [[ -z "$expected" || "$version" == "$expected"* ]]; then
        echo "Healthy: version=${version:-unknown}"
        return 0
      fi
      echo "Up, but still old version (${version:-unknown}); waiting..."
    else
      echo "Not healthy yet; waiting..."
    fi
    sleep "$POLL_SECONDS"
  done
  return 1
}

# A failed update changed nothing, so there is nothing to roll back.
set_image "$IMAGE" || exit 1

if wait_healthy "$EXPECTED"; then
  exit 0
fi
echo "::error::Backend did not report a healthy ${EXPECTED:-new} version within ${WAIT_SECONDS}s"

# The job fails either way; rolling back only gets the old version serving again.
# Never roll back to :latest - CI has already moved it to the image that failed.
if [[ -z "$previous" || "$previous" == "$IMAGE" || ! "$previous" =~ $IMAGE_PATTERN \
      || "${previous##*:}" == "latest" ]]; then
  echo "::error::No usable previous image ('${previous:-unknown}') to roll back to. Run 'Rollback backend' with a known good tag."
  exit 1
fi

echo "Rolling back to $previous"
previous_expected=""
if [[ "${previous##*:}" =~ ^sha-([0-9a-f]+)$ ]]; then
  previous_expected="${BASH_REMATCH[1]}"
fi
if set_image "$previous" && wait_healthy "$previous_expected"; then
  echo "::error::Deploy of $IMAGE failed; rolled back to $previous, which is serving again."
else
  echo "::error::Deploy of $IMAGE failed and rolling back to $previous also failed. The backend may be down: check the pod in RunPod and run 'Rollback backend' with a known good tag."
fi
exit 1
