#!/usr/bin/env bash
# Cursor hook: before `git commit`, build-test staged add-ons with Dockerfiles.
set -euo pipefail

input="$(cat)"
# Always allow if we cannot parse; failClosed still covers crashes.
command="$(printf '%s' "${input}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("command",""))' 2>/dev/null || true)"

allow() {
  printf '%s\n' '{"permission":"allow"}'
  exit 0
}

deny() {
  local msg="$1"
  python3 -c 'import json,sys; print(json.dumps({"permission":"deny","user_message":sys.argv[1],"agent_message":sys.argv[1]}))' "${msg}"
  exit 0
}

# Only gate real commits (not commit --help, etc.)
if [[ ! "${command}" =~ git[[:space:]]+commit ]]; then
  allow
fi
if [[ "${command}" =~ --help|/help|-h([[:space:]]|$) ]]; then
  allow
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

if ! command -v git >/dev/null 2>&1; then
  allow
fi

mapfile -t staged < <(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null || true)
if [[ ${#staged[@]} -eq 0 ]]; then
  allow
fi

declare -A need=()
for path in "${staged[@]}"; do
  case "${path}" in
    */Dockerfile|*/rootfs/*|*/app/*|*/build.yaml|*/config.yaml)
      addon="${path%%/*}"
      if [[ -f "${ROOT}/${addon}/Dockerfile" ]]; then
        need["${addon}"]=1
      fi
      ;;
  esac
done

if [[ ${#need[@]} -eq 0 ]]; then
  allow
fi

addons=("${!need[@]}")
if ! "${ROOT}/scripts/test-addon-build.sh" "${addons[@]}" >&2; then
  deny "Add-on Docker build test failed for: ${addons[*]}. Fix the image before committing."
fi

allow
