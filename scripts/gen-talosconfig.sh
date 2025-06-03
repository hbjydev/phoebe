#!/usr/bin/env bash
set -Eeuo pipefail

source "$(dirname "${0}")/lib/common.sh"
export ROOT_DIR="$(git rev-parse --show-toplevel)"
export SCRIPTS_DIR="${ROOT_DIR}/scripts"
export TALOS_DIR="${ROOT_DIR}/talos"

readonly NODE_BASE="${1:-${TALOS_DIR}/controlplane.yaml.j2}" NODE_PATCH="${2:-${TALOS_DIR}/nodes/192.168.1.3.yaml.j2}"

function main() {
  local -r LOG_LEVEL="info"

  check_cli minijinja-cli op talosctl jq

  if ! op whoami --format=json &>/dev/null; then
    log error "Failed to authenticate with 1Password CLI"
  fi

  local tmpdir="$(mktemp -d)"
  local op_secrets ca_crt ca_key admin_crt admin_key

  log info "Fetching Talos CA certificate & key from 1Password"
  if ! op_secrets=$(op item get --format json --vault phoebe talos --fields MACHINE_CA_CRT,MACHINE_CA_KEY) || [[ -z "${op_secrets}" ]]; then
    log error "Failed to get 1Password secret"
    exit 1
  fi

  if ! ca_crt=$(echo "$op_secrets" | jq -r '.[0].value' | base64 -d) || [[ -z "${ca_crt}" ]]; then
    log error "Failed to get CA certificate from 1Password secret"
    exit 1
  fi

  if ! ca_key=$(echo "$op_secrets" | jq -r '.[1].value' | base64 -d) || [[ -z "${ca_key}" ]]; then
    log error "Failed to get CA key from 1Password secret"
    exit 1
  fi

  log debug "Persisting CA certificate & key to tmpdir" "tmpdir=$tmpdir"
  echo "$ca_crt" > "$tmpdir/ca.crt"
  echo "$ca_key" > "$tmpdir/ca.key"

  log info "Generating Talos admin authentication certificate with CA"
  talosctl gen key --name "${tmpdir}/admin"
  talosctl gen csr --key "${tmpdir}/admin.key" --ip 127.0.0.1
  talosctl gen crt --ca "${tmpdir}/ca" --csr "${tmpdir}/admin.csr" --name "${tmpdir}/admin"

  log info "Rendering talosconfig file"
  export ADMIN_CRT="$(cat "${tmpdir}/admin.crt" | base64 -w0)"
  export ADMIN_KEY="$(cat "${tmpdir}/admin.key" | base64 -w0)"
  export CA_CRT="$(echo "${ca_crt}" | base64 -w0)"
  minijinja-cli "$TALOS_DIR/talosconfig.j2" > "$TALOS_DIR/talosconfig"
}

main "$@"
