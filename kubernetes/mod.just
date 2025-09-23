set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

kubernetes_dir := justfile_dir() + "/kubernetes"

[private]
default:
  just -l kube

# Sync GitRepositories
sync-git:
  kubectl get gitrepo --no-headers -A | while read -r ns name _; do \
    kubectl -n "$ns" annotate --field-manager flux-client-side-apply --overwrite gitrepo "$name" reconcile.fluxcd.io/requestedAt="$(date +%s)"; \
  done

# Sync HelmReleases
sync-hr:
  kubectl get hr --no-headers -A | while read -r ns name _; do \
    kubectl -n "$ns" annotate --field-manager flux-client-side-apply --overwrite hr "$name" reconcile.fluxcd.io/requestedAt="$(date +%s)" reconcile.fluxcd.io/forceAt="$(date +%s)"; \
  done

# Sync Kustomizations
sync-ks:
  kubectl get ks --no-headers -A | while read -r ns name _; do \
    kubectl -n "$ns" annotate --field-manager flux-client-side-apply --overwrite ks "$name" reconcile.fluxcd.io/requestedAt="$(date +%s)"; \
  done

# Sync OCIRepositories
sync-oci:
  kubectl get ocirepo --no-headers -A | while read -r ns name _; do \
    kubectl -n "$ns" annotate --field-manager flux-client-side-apply --overwrite ocirepo "$name" reconcile.fluxcd.io/requestedAt="$(date +%s)"; \
  done

[private]
render-local-ks dir ks="*":
  flux-local build ks --all-namespaces --path "{{ kubernetes_dir }}/apps/{{ dir }}" {{ if ks != "*" { ks } else { "" } }}
