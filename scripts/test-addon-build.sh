#!/usr/bin/env bash
# Build-test one or more Home Assistant add-on Docker images.
# Usage:
#   scripts/test-addon-build.sh                  # all add-ons with a Dockerfile
#   scripts/test-addon-build.sh audio_cast_bridge
#   scripts/test-addon-build.sh audio_cast_bridge icecast
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is required for add-on build tests" >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "ERROR: docker daemon is not reachable" >&2
  exit 1
fi

arch="$(uname -m)"
case "${arch}" in
  x86_64|amd64) build_from="ghcr.io/home-assistant/amd64-base:latest" ;;
  aarch64|arm64) build_from="ghcr.io/home-assistant/aarch64-base:latest" ;;
  armv7l) build_from="ghcr.io/home-assistant/armv7-base:latest" ;;
  *) build_from="ghcr.io/home-assistant/base:latest" ;;
esac

if [[ $# -gt 0 ]]; then
  addons=("$@")
else
  mapfile -t addons < <(
    find . -mindepth 2 -maxdepth 2 -name Dockerfile -printf '%h\n' \
      | sed 's|^\./||' \
      | sort
  )
fi

if [[ ${#addons[@]} -eq 0 ]]; then
  echo "No add-ons with Dockerfiles found" >&2
  exit 1
fi

echo "BUILD_FROM=${build_from}"
failed=0
for addon in "${addons[@]}"; do
  dockerfile="${ROOT}/${addon}/Dockerfile"
  if [[ ! -f "${dockerfile}" ]]; then
    echo "ERROR: missing ${dockerfile}" >&2
    failed=1
    continue
  fi
  tag="hassio-addons/${addon//\//-}:build-test"
  echo "==> Building ${addon} (${tag})"
  if ! docker build \
      --build-arg "BUILD_FROM=${build_from}" \
      -t "${tag}" \
      "${ROOT}/${addon}"; then
    echo "ERROR: docker build failed for ${addon}" >&2
    failed=1
    continue
  fi

  # Smoke-check Python apps if present
  if docker run --rm --entrypoint python3 "${tag}" -c "import sys; print(sys.version)" >/dev/null 2>&1; then
    if [[ -d "${ROOT}/${addon}/app" ]]; then
      echo "==> Smoke import check for ${addon}"
      if ! docker run --rm --entrypoint python3 "${tag}" -c "import aiohttp; print('aiohttp', aiohttp.__version__)"; then
        echo "ERROR: runtime import check failed for ${addon}" >&2
        failed=1
        continue
      fi
    fi
  fi
  echo "OK: ${addon}"
done

if [[ "${failed}" -ne 0 ]]; then
  echo "Add-on build test FAILED" >&2
  exit 1
fi
echo "Add-on build test PASSED (${#addons[@]} add-on(s))"
