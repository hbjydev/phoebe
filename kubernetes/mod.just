set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

# Sync Git repository to cluster
sync:
  flux reconcile source git flux-system -n flux-system

# Sync a specific Kustomization
sync-ks ks ns='default':
  flux reconcile kustomization {{ ks }} -n {{ ns }} --with-source
