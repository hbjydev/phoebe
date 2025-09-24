set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

tmp_dir := `mktemp -d`
talos_dir := justfile_dir() + "/talos"

[private]
default:
  just -l talos

[private]
controller:
  talosctl config info -o yaml | yq -e '.endpoints[0]'

[private]
nodes:
  talosctl config info -o yaml | yq -e '.nodes | join(" ")'

# Applies a Talos config to a given node
apply-node node *args: genconfig
  files=$(just talos render-config); \
  cmd=$(talhelper gencommand apply \
    --config-file "$(echo "$files" | jq -r .config)" \
    --node "{{ node }}" \
    --out-dir "{{ talos_dir }}" | sed 's/;//') && \
  $cmd {{ args }}

# Generates the necessary Kubeconfig to access the cluster
kubeconfig node *args: genconfig
  files=$(just talos render-config); \
  cmd=$(talhelper gencommand kubeconfig \
    --config-file "$(echo "$files" | jq -r .config)" \
    --node "{{ node }}" \
    --out-dir "{{ talos_dir }}" | sed 's/;//') && \
  $cmd {{ args }}

# Upgrades a given node to the provided Talos version
upgrade node *args: genconfig
  files=$(just talos render-config); \
  cmd=$(talhelper gencommand upgrade \
    --config-file "$(echo "$files" | jq -r .config)" \
    --node "{{ node }}" \
    --out-dir "{{ talos_dir }}" | sed 's/;//') && \
  $cmd {{ args }}

# Upgrades a given node to the provided Kubernetes version
upgrade-k8s node *args: genconfig
  files=$(just talos render-config); \
  cmd=$(talhelper gencommand upgrade-k8s \
    --config-file "$(echo "$files" | jq -r .config)" \
    --node "{{ node }}" \
    --out-dir "{{ talos_dir }}" | sed 's/;//') && \
  $cmd {{ args }}

# Generates Talos config and secret files into the talos directory
genconfig:
  files=$(just talos render-config); \
  talhelper genconfig \
    --secret-file "$(echo "$files" | jq -r .secret)" \
    --config-file "$(echo "$files" | jq -r .config)" \
    --out-dir "{{ talos_dir }}"

# Generate a schematic ID from the schematic definition
schematic-id:
  curl -fsSL -X POST --data-binary @{{ talos_dir }}/schematic.yaml https://factory.talos.dev/schematics | jq -r .id

# Render talos config for a node
render-config:
  export TALOS_DIR="{{ talos_dir }}"; \
  export TALOS_SCHEMATIC="$(just talos schematic-id)"; \
  secret_file="$(mktemp)"; \
  config_file="$(mktemp)"; \
  just template "{{ talos_dir }}/talsecret.yaml.optpl" > "$secret_file"; \
  just template "{{ talos_dir }}/talconfig.yaml.j2" > "$config_file"; \
  echo "{\"secret\":\"$secret_file\",\"config\":\"$config_file\"}"
