set positional-arguments := true
set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

bootstrap_dir := justfile_dir() + '/bootstrap'
kubernetes_dir := justfile_dir() + '/kubernetes'

[private]
default: talos (kubeconfig "node") wait namespaces resources crds apps kubeconfig

# Install Talos
talos:
  just log info "Running stage..." "stage" "$0"
  if ! op=$(just talos apply --auto-bootstrap --confirm=false 2>&1); then \
    just log fatal "Failed to apply Talos configuration" "stage" "$0" "output" "$op"; \
  fi

# Fetch kubeconfig
kubeconfig lb="cilium":
  just log info "Running stage..." "stage" "$0"
  if ! talosctl kubeconfig -n "$(just talos controller)" -f --force-context-name main {{ justfile_dir() }}; then \
    just log fatal "Failed to fetch kubeconfig" "stage" "$0"; \
  fi
  if [[ "{{ lb }}" != "cilium" ]]; then \
    if ! kubectl config set-cluster main --server "https://$(just talos controller):6443"; then \
      just log fatal "Failed to set kubectl cluster server address" "stage" "$0"; \
    fi; \
  fi

[doc('Wait for nodes to be not-ready')]
wait:
  just log info "Running stage..." "stage" "$0"
  if ! kubectl wait nodes --for=condition=Ready=True --all --timeout=10s &>/dev/null; then \
    until kubectl wait nodes --for=condition=Ready=False --all --timeout=10s &>/dev/null; do \
      just log info "Nodes not available, waiting for nodes to be available. Retrying in 5 seconds..." "stage" "$0"; \
      sleep 5; \
    done \
  fi

# Apply Kubernetes namespaces
namespaces:
  just log info "Running stage..." "stage" "$0"
  find "{{ kubernetes_dir }}/apps" -mindepth 1 -maxdepth 1 -type d -printf "%f\n" | while IFS= read -r ns; do \
    if ! kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply --server-side --field-manager flux-client-side-apply -f -; then \
      just log fatal "Failed to apply namespace" "stage" "$0" "namespace" "$ns"; \
    fi; \
  done

# Apply Kubernetes resources
resources:
  just log info "Running stage..." "stage" "$0"
  if ! just template "{{ bootstrap_dir }}/resources.yaml.j2" | kubectl apply --server-side --field-manager flux-client-side-apply -f -; then \
    just log fatal "Failed to apply resources" "stage" "$0"; \
  fi;

# Apply Helmfile CRDs
crds:
  just log info "Running stage..." "stage" "$0"
  if ! helmfile -f "{{ bootstrap_dir }}/helmfile.d/00-crds.yaml" template -q | kubectl apply --server-side --field-manager flux-client-side-apply -f -; then \
    just log fatal "Failed to apply crds" "stage" "$0"; \
  fi;

# Apply Helmfile Apps
apps:
  just log info "Running stage..." "stage" "$0"
  if ! helmfile -f "{{ bootstrap_dir }}/helmfile.d/01-apps.yaml" sync --hide-notes; then \
    just log fatal "Failed to sync helmfile" "stage" "$0"; \
  fi
