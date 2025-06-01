scripts_dir := "./scripts"
talos_dir := "./talos"

# Applies a Talos config to a given node
talos-apply-node ip machine_type='controlplane' mode='auto':
  bash {{ scripts_dir }}/render-machine-config.sh {{ talos_dir }}/{{ machine_type }}.yaml.j2 {{ talos_dir }}/nodes/{{ ip }}.yaml.j2 \
    | talosctl --nodes {{ ip }} apply-config --mode {{ mode }} --file /dev/stdin

# Generates the necessary Kubeconfig to access the cluster
kubeconfig ip:
  talosctl kubeconfig {{ talos_dir }} --force --nodes "{{ ip }}"

sync:
  flux reconcile source git flux-system -n flux-system

sync-ks ks ns='default':
  flux reconcile kustomization {{ ks }} -n {{ ns }} --with-source
