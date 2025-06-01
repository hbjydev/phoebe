#!/usr/bin/env bash
set -Eeuo pipefail

source "$(dirname "${0}")/lib/common.sh"
export ROOT_DIR="$(git rev-parse --show-toplevel)"

readonly NODE_BASE="${1:?}" NODE_PATCH="${2:?}"

function main() {
  local -r LOG_LEVEL="info"

  check_env KUBERNETES_VERSION TALOS_VERSION
  check_cli minijinja-cli op talosctl

  if ! op whoami --format=json &>/dev/null; then
    log error "Failed to authenticate with 1Password CLI"
  fi

  local base patch machine_config

  if ! base=$(render_template "${NODE_BASE}") || [[ -z "${base}" ]]; then
    exit 1
  fi

  if ! patch=$(render_template "${NODE_PATCH}") || [[ -z "${patch}" ]]; then
      exit 1
  fi

  BASE_TMPFILE=$(mktemp)
  echo "${base}" >"${BASE_TMPFILE}"

  PATCH_TMPFILE=$(mktemp)
  echo "${patch}" >"${PATCH_TMPFILE}"

  if ! machine_config=$(echo "${base}" | talosctl machineconfig patch "${BASE_TMPFILE}" --patch "@${PATCH_TMPFILE}") || [[ -z "${machine_config}" ]]; then
      log error "Failed to merge configs" "base=$(basename "${NODE_BASE}")" "patch=$(basename "${NODE_PATCH}")"
  fi

  echo "${machine_config}"
}

main "$@"
