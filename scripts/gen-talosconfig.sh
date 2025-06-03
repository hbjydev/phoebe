#!/usr/bin/env bash
set -Eeuo pipefail

source "$(dirname "${0}")/lib/common.sh"
export ROOT_DIR="$(git rev-parse --show-toplevel)"
export SCRIPTS_DIR="${ROOT_DIR}/scripts"
export TALOS_DIR="${ROOT_DIR}/talos"

readonly TMPDIR="$(mktemp -d)"
readonly NODE_BASE="${1:-${TALOS_DIR}/controlplane.yaml.j2}" NODE_PATCH="${2:-${TALOS_DIR}/nodes/192.168.1.3.yaml.j2}"

export OP_SECRETS="$(op item get --format json --vault phoebe talos --fields MACHINE_CA_CRT,MACHINE_CA_KEY)"
export CA_CRT="$(echo "$OP_SECRETS" | jq -r '.[0].value' | base64 -d)"
export CA_KEY="$(echo "$OP_SECRETS" | jq -r '.[1].value' | base64 -d)"

echo "$CA_CRT" > "$TMPDIR/ca.crt"
echo "$CA_KEY" > "$TMPDIR/ca.key"

talosctl gen key --name "$TMPDIR/admin"
talosctl gen csr --key "$TMPDIR/admin.key" --ip 127.0.0.1
talosctl gen crt --ca "$TMPDIR/ca" --csr "$TMPDIR/admin.csr" --name "$TMPDIR/admin"

export ADMIN_CRT="$(cat "$TMPDIR/admin.crt" | base64 -w0)"
export ADMIN_KEY="$(cat "$TMPDIR/admin.key" | base64 -w0)"
export CA_CRT="$(echo "$CA_CRT" | base64 -w0)"

minijinja-cli "$TALOS_DIR/talosconfig.j2" > "$TALOS_DIR/talosconfig"
