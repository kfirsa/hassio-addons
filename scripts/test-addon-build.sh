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
  x86_64|amd64)
    build_from="ghcr.io/home-assistant/amd64-base:latest"
    build_from_debian="ghcr.io/home-assistant/amd64-base-debian:bookworm"
    ;;
  aarch64|arm64)
    build_from="ghcr.io/home-assistant/aarch64-base:latest"
    build_from_debian="ghcr.io/home-assistant/aarch64-base-debian:bookworm"
    ;;
  armv7l)
    build_from="ghcr.io/home-assistant/armv7-base:latest"
    build_from_debian="${build_from}"
    ;;
  *)
    build_from="ghcr.io/home-assistant/base:latest"
    build_from_debian="${build_from}"
    ;;
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
  addon_from="${build_from}"
  if [[ -f "${ROOT}/${addon}/build.yaml" ]] && grep -q 'base-debian' "${ROOT}/${addon}/build.yaml"; then
    addon_from="${build_from_debian}"
  fi
  echo "==> Building ${addon} (${tag}) BUILD_FROM=${addon_from}"
  if ! docker build \
      --build-arg "BUILD_FROM=${addon_from}" \
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
      if [[ "${addon}" == "audio_cast_bridge" ]]; then
        if ! docker run --rm --entrypoint python3 "${tag}" -c "import websockets; print('websockets', websockets.__version__)"; then
          echo "ERROR: websockets import failed for ${addon}" >&2
          failed=1
          continue
        fi
        if ! docker run --rm --entrypoint /usr/local/bin/vibecast "${tag}" --help >/dev/null; then
          echo "ERROR: vibecast binary missing/broken for ${addon}" >&2
          failed=1
          continue
        fi
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
