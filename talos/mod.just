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
apply-node node *args:
  just talos render-config "{{ node }}" | talosctl -n "{{ node }}" apply-config -f /dev/stdin {{ args }}

# Generates the necessary Kubeconfig to access the cluster
kubeconfig node:
  talosctl kubeconfig {{ talos_dir }} --force --nodes "$(just talos controller)"

# Generates the Talosconfig file to access the cluster
talosconfig:
  just log info "Fetching CA from 1Password"; \
  export OP_SECRETS="$(op item get --format json --vault phoebe talos --fields MACHINE_CA_CRT,MACHINE_CA_KEY)"; \
  export CA_CRT="$(echo "$OP_SECRETS" | jq -r '.[0].value' | base64 -d)"; \
  export CA_KEY="$(echo "$OP_SECRETS" | jq -r '.[1].value' | base64 -d)"; \
  echo "$CA_CRT" > "{{ tmp_dir }}/ca.crt"; \
  echo "$CA_KEY" > "{{ tmp_dir }}/ca.key"; \

  just log info "Generating admin authentication certificates"; \
  talosctl gen key --name "{{ tmp_dir }}/admin"; \
  talosctl gen csr --key "{{ tmp_dir }}/admin.key" --ip 127.0.0.1; \
  talosctl gen crt --ca "{{ tmp_dir }}/ca" --csr "{{ tmp_dir }}/admin.csr" --name "{{ tmp_dir }}/admin"; \

  just log info "Rendering Talosconfig"; \
  export ADMIN_CRT="$(cat "{{ tmp_dir }}/admin.crt" | base64 -w0)"; \
  export ADMIN_KEY="$(cat "{{ tmp_dir }}/admin.key" | base64 -w0)"; \
  export CA_CRT="$(cat "{{ tmp_dir }}/ca.crt" | base64 -w0)"; \
  rm "{{ talos_dir }}/talosconfig" || true; \
  just template "{{ talos_dir }}/talosconfig.yaml.j2" > "{{ talos_dir }}/talosconfig"

# Generate a schematic ID from the schematic definition
schematic-id:
  curl -fsSL -X POST --data-binary @{{ talos_dir }}/schematic.yaml https://factory.talos.dev/schematics | jq -r .id

# Upgrade Kubernetes version on a node
upgrade-k8s version:
  talosctl -n "$(just talos controller)" upgrade-k8s --to {{ version }}

# Upgrade Talos version on a node
upgrade-node node:
  talosctl -n "{{ node }}" upgrade -i "$(just talos machine-image)" -m powercycle --timeout=10m

# Render talos config for a node
render-config node:
  export IS_CONTROLLER="$(just talos machine-controller {{ node }})"; \
  export TALOS_SCHEMATIC="$(just talos schematic-id)"; \
  talosctl machineconfig patch <(just template "{{ talos_dir }}/machineconfig.yaml.j2") \
    -p @<(just template "{{ talos_dir }}/nodes/{{ node }}.yaml.j2")

[private]
machine-controller node:
  export TALOS_SCHEMATIC="$(just talos schematic-id)"; \
  just template "{{ talos_dir }}/nodes/{{ node }}.yaml.j2" | yq -e 'select(.machine) | (.machine.type == "controlplane") // ""'

[private]
machine-image:
  export TALOS_SCHEMATIC="$(just talos schematic-id)"; \
  just template "{{ talos_dir }}/machineconfig.yaml.j2" | yq -e 'select(.machine) | .machine.install.image'
