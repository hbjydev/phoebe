sync:
  flux reconcile source git flux-system -n flux-system

sync-ks ks ns='default':
  flux reconcile kustomization {{ ks }} -n {{ ns }} --with-source
