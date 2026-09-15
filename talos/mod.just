set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

talos_dir := justfile_dir() + "/talos"

[private]
default:
  just -l talos

[private]
controller:
  yq -er '.nodes[] | select(.role == "control-plane") | .ip' "{{ talos_dir }}/topf.yaml" | head -n1

[private]
nodes:
  yq -er '.nodes[].host' "{{ talos_dir }}/topf.yaml"

# Applies the desired configuration to every node.
apply *args:
  cd "{{ talos_dir }}" && topf apply {{ args }}

# Applies the desired configuration to one node selected by its TOPF host name.
apply-node node *args:
  cd "{{ talos_dir }}" && topf --nodes-filter '^{{ node }}$' apply {{ args }}

# Renders the generated Talos machine configurations without applying them.
render *args:
  cd "{{ talos_dir }}" && topf render --output output {{ args }}

# Compatibility alias for the previous recipe name.
genconfig: render

# Generates the admin kubeconfig managed by this repository.
kubeconfig *args:
  cd "{{ talos_dir }}" && topf kubeconfig {{ args }} > kubeconfig

# Generates talosconfig from the configured secrets bundle.
talosconfig *args:
  cd "{{ talos_dir }}" && topf talosconfig {{ args }} > talosconfig

# Prints the deterministic image-factory schematic ID.
schematic-id:
  cd "{{ talos_dir }}" && topf schematic-ids

# Upgrades a node to the Talos version and schematic declared in topf.yaml.
upgrade node *args:
  cd "{{ talos_dir }}" && topf --nodes-filter '^{{ node }}$' upgrade {{ args }}

# Upgrades Kubernetes; TOPF intentionally delegates this operation to talosctl.
upgrade-k8s node *args:
  talosctl upgrade-k8s --nodes "{{ node }}" --to "$KUBE_VERSION" {{ args }}
