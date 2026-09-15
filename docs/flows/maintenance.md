# Ceph Maintenance

This runbook quiesces workloads that use Ceph-backed storage before planned
storage, Talos, or node maintenance. It stops direct RBD consumers, PostgreSQL
clients, observability writers, and Kopiur before hibernating PostgreSQL.

The procedure deliberately leaves the Rook operator, Ceph daemons, and Ceph CSI
drivers running. They can be stopped later as part of the maintenance operation
after the final consumer check is empty.

## Preconditions

- Run the commands from a shell with `kubectl`, `flux`, and `jq` installed.
- The current Kubernetes context must be `admin@phoebe`.
- Do not continue if Ceph reports `HEALTH_ERR`.
- Let any active backup or restore finish before stopping the storage layer.
- Keep the terminal open until the shutdown verification completes.

Check the cluster before starting:

```bash
kubectl config current-context
kubectl get cephcluster --namespace rook-ceph
kubectl exec --namespace rook-ceph deployment/rook-ceph-tools -- ceph status
kubectl get volumesnapshot --all-namespaces
kubectl get pods --all-namespaces
```

## Shutdown

The first two suspensions freeze the Flux hierarchy so it cannot restore
replica counts during maintenance. The ResourceSet annotation separately
freezes the generated CloudNativePG Kustomization.

The target list includes applications that mount `ceph-block` directly and
applications that write to the Ceph-backed PostgreSQL cluster. When a new
Ceph-backed application is added, it must also be added to this list.

```bash
bash <<'BASH'
set -euo pipefail

expected_context="admin@phoebe"
[[ "$(kubectl config current-context)" == "$expected_context" ]]

flux suspend kustomization flux-system --namespace flux-system
flux suspend kustomization cluster-apps --namespace flux-system

kubectl annotate resourceset/cnpg-cluster \
  --namespace database \
  fluxcd.controlplane.io/reconcile=disabled \
  --overwrite

while read -r namespace kustomization; do
  flux suspend kustomization "$kustomization" --namespace "$namespace"

  while read -r helmrelease; do
    [[ -n "$helmrelease" ]] || continue

    flux suspend helmrelease "$helmrelease" --namespace "$namespace"

    while read -r controller; do
      [[ -n "$controller" ]] || continue
      kubectl scale "$controller" --namespace "$namespace" --replicas=0
      kubectl rollout status "$controller" \
        --namespace "$namespace" \
        --timeout=5m
    done < <(
      kubectl get deployment,statefulset \
        --namespace "$namespace" \
        --selector "helm.toolkit.fluxcd.io/name=${helmrelease}" \
        --output name
    )
  done < <(
    kubectl get helmreleases.helm.toolkit.fluxcd.io \
      --namespace "$namespace" \
      --selector "kustomize.toolkit.fluxcd.io/name=${kustomization}" \
      --output jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
  )
done <<'TARGETS'
ai hermes
ai honcho
ai litellm
ai llama-cpp-reranking
ai mcp-auth-proxy
ai memini
ai mimi
ai openclaw
database cnpg-cluster
default home-assistant
default jellyseerr
default lidarr
default matter-server
default openthread
default prowlarr
default radarr
default sonarr
dev forgejo
downloads qbittorrent
downloads qui
downloads sabnzbd
downloads slskd
kguardian kguardian
kopiur-system kopiur
matrix continuwuity
media dispatcharr
media jellyfin
media navidrome
media picard
media pinepods
media plex
media suwayomi
observability gatus
observability grafana-instance
observability victoria-logs
observability victoria-metrics
observability victoria-traces
security kaniop-instance
selfhosted immich
selfhosted miniflux
selfhosted ntfy
selfhosted paperless
selfhosted searxng
selfhosted tranquil
TARGETS

# Stop the operator-managed application workloads.
kubectl patch litellmproxy/litellm \
  --namespace ai \
  --type merge \
  --patch '{"spec":{"replicas":0}}'
kubectl wait deployment/litellm \
  --namespace ai \
  --for='jsonpath={.spec.replicas}=0' \
  --timeout=2m
kubectl rollout status deployment/litellm --namespace ai --timeout=5m

# Stop observability writers before their stores.
kubectl patch vlagent/logs-agent \
  --namespace observability \
  --type merge \
  --patch '{"spec":{"paused":true}}'
kubectl delete daemonset/vlagent-logs-agent \
  --namespace observability \
  --ignore-not-found \
  --wait=true

kubectl patch vmagent/metrics-agent \
  --namespace observability \
  --type merge \
  --patch '{"spec":{"paused":true}}'
kubectl scale deployment/vmagent-metrics-agent \
  --namespace observability \
  --replicas=0
kubectl rollout status deployment/vmagent-metrics-agent \
  --namespace observability \
  --timeout=5m

kubectl patch vlsingle/victoria-logs \
  --namespace observability \
  --type merge \
  --patch '{"spec":{"paused":true}}'
kubectl scale deployment/vlsingle-victoria-logs \
  --namespace observability \
  --replicas=0
kubectl rollout status deployment/vlsingle-victoria-logs \
  --namespace observability \
  --timeout=5m

kubectl patch vmsingle/victoria-metrics \
  --namespace observability \
  --type merge \
  --patch '{"spec":{"paused":true}}'
kubectl scale deployment/vmsingle-victoria-metrics \
  --namespace observability \
  --replicas=0
kubectl rollout status deployment/vmsingle-victoria-metrics \
  --namespace observability \
  --timeout=5m

kubectl patch vtsingle/victoria-traces \
  --namespace observability \
  --type merge \
  --patch '{"spec":{"paused":true}}'
kubectl scale deployment/vtsingle-victoria-traces \
  --namespace observability \
  --replicas=0
kubectl rollout status deployment/vtsingle-victoria-traces \
  --namespace observability \
  --timeout=5m

kubectl patch grafanas.grafana.integreatly.org/grafana \
  --namespace observability \
  --type merge \
  --patch '{"spec":{"suspend":true}}'
kubectl scale deployment/grafana-deployment \
  --namespace observability \
  --replicas=0
kubectl rollout status deployment/grafana-deployment \
  --namespace observability \
  --timeout=5m

kubectl patch kanidm/kanidm \
  --namespace security \
  --type json \
  --patch '[{"op":"replace","path":"/spec/replicaGroups/0/replicas","value":0}]'
kubectl wait statefulset/kanidm-default \
  --namespace security \
  --for='jsonpath={.spec.replicas}=0' \
  --timeout=2m
kubectl rollout status statefulset/kanidm-default \
  --namespace security \
  --timeout=5m

# PostgreSQL is the final Ceph-backed application to stop.
kubectl annotate cluster/postgres \
  --namespace database \
  cnpg.io/hibernation=on \
  --overwrite
kubectl wait cluster/postgres \
  --namespace database \
  --for='jsonpath={.status.conditions[?(@.type=="cnpg.io/hibernation")].status}=True' \
  --timeout=10m
BASH
```

## Shutdown verification

This query lists every non-Rook Pod that still mounts a Ceph-backed PVC. It
must produce no output before the Ceph storage layer or node is stopped.

```bash
kubectl get pods --all-namespaces --output json |
  jq -r --slurpfile pvc <(kubectl get pvc --all-namespaces --output json) '
    ($pvc[0].items
      | map(select(
          .spec.storageClassName == "ceph-block" or
          ((.metadata.annotations["volume.kubernetes.io/storage-provisioner"] // "")
            | contains("ceph"))
        ))
      | map({
          key: (.metadata.namespace + "/" + .metadata.name),
          value: true
        })
      | from_entries) as $ceph_claims
    | .items[] as $pod
    | select($pod.metadata.namespace != "rook-ceph")
    | select(any(
        $pod.spec.volumes[]?;
        .persistentVolumeClaim.claimName as $claim
        | $ceph_claims[$pod.metadata.namespace + "/" + $claim]
      ))
    | $pod.metadata.namespace + "/" + $pod.metadata.name
  '
```

If the query reports a mover, backup, restore, or snapshot Pod, allow that
operation to complete and run the check again. Investigate any other result
before continuing; do not stop Ceph while a consumer remains mounted.

Check Ceph once more immediately before maintenance:

```bash
kubectl exec --namespace rook-ceph deployment/rook-ceph-tools -- ceph status
```

## Recovery

Recover Ceph and its CSI drivers before running these commands. The recovery
sequence starts stateful services before their clients, then restores normal
GitOps reconciliation.

```bash
bash <<'BASH'
set -euo pipefail

expected_context="admin@phoebe"
[[ "$(kubectl config current-context)" == "$expected_context" ]]

kubectl wait cephcluster/rook-ceph \
  --namespace rook-ceph \
  --for='jsonpath={.status.ceph.health}=HEALTH_OK' \
  --timeout=10m
kubectl exec --namespace rook-ceph deployment/rook-ceph-tools -- ceph status

# Restore PostgreSQL before its clients.
kubectl annotate cluster/postgres \
  --namespace database \
  cnpg.io/hibernation=off \
  --overwrite
kubectl wait cluster/postgres \
  --namespace database \
  --for='jsonpath={.status.readyInstances}=2' \
  --timeout=10m

# Restore identity.
kubectl patch kanidm/kanidm \
  --namespace security \
  --type json \
  --patch '[{"op":"replace","path":"/spec/replicaGroups/0/replicas","value":1}]'
kubectl wait statefulset/kanidm-default \
  --namespace security \
  --for='jsonpath={.spec.replicas}=1' \
  --timeout=2m
kubectl rollout status statefulset/kanidm-default \
  --namespace security \
  --timeout=10m

# Restore the observability stores, then their writers.
kubectl patch vlsingle/victoria-logs \
  --namespace observability \
  --type merge \
  --patch '{"spec":{"paused":false}}'
kubectl scale deployment/vlsingle-victoria-logs \
  --namespace observability \
  --replicas=1
kubectl rollout status deployment/vlsingle-victoria-logs \
  --namespace observability \
  --timeout=10m

kubectl patch vmsingle/victoria-metrics \
  --namespace observability \
  --type merge \
  --patch '{"spec":{"paused":false}}'
kubectl scale deployment/vmsingle-victoria-metrics \
  --namespace observability \
  --replicas=1
kubectl rollout status deployment/vmsingle-victoria-metrics \
  --namespace observability \
  --timeout=10m

kubectl patch vtsingle/victoria-traces \
  --namespace observability \
  --type merge \
  --patch '{"spec":{"paused":false}}'
kubectl scale deployment/vtsingle-victoria-traces \
  --namespace observability \
  --replicas=1
kubectl rollout status deployment/vtsingle-victoria-traces \
  --namespace observability \
  --timeout=10m

kubectl patch vlagent/logs-agent \
  --namespace observability \
  --type merge \
  --patch '{"spec":{"paused":false}}'
kubectl wait daemonset/vlagent-logs-agent \
  --namespace observability \
  --for=create \
  --timeout=2m
kubectl rollout status daemonset/vlagent-logs-agent \
  --namespace observability \
  --timeout=10m

kubectl patch vmagent/metrics-agent \
  --namespace observability \
  --type merge \
  --patch '{"spec":{"paused":false}}'
kubectl scale deployment/vmagent-metrics-agent \
  --namespace observability \
  --replicas=1
kubectl rollout status deployment/vmagent-metrics-agent \
  --namespace observability \
  --timeout=10m

kubectl patch grafanas.grafana.integreatly.org/grafana \
  --namespace observability \
  --type merge \
  --patch '{"spec":{"suspend":false}}'
kubectl scale deployment/grafana-deployment \
  --namespace observability \
  --replicas=1
kubectl rollout status deployment/grafana-deployment \
  --namespace observability \
  --timeout=10m

kubectl patch litellmproxy/litellm \
  --namespace ai \
  --type merge \
  --patch '{"spec":{"replicas":1}}'
kubectl wait deployment/litellm \
  --namespace ai \
  --for='jsonpath={.spec.replicas}=1' \
  --timeout=2m
kubectl rollout status deployment/litellm --namespace ai --timeout=10m

# Resume each application and its Helm releases.
while read -r namespace kustomization; do
  flux resume kustomization "$kustomization" --namespace "$namespace"

  while read -r helmrelease; do
    [[ -n "$helmrelease" ]] || continue
    flux resume helmrelease "$helmrelease" --namespace "$namespace"
  done < <(
    kubectl get helmreleases.helm.toolkit.fluxcd.io \
      --namespace "$namespace" \
      --selector "kustomize.toolkit.fluxcd.io/name=${kustomization}" \
      --output jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
  )
done <<'TARGETS'
ai hermes
ai honcho
ai litellm
ai llama-cpp-reranking
ai mcp-auth-proxy
ai memini
ai mimi
ai openclaw
default home-assistant
default jellyseerr
default lidarr
default matter-server
default openthread
default prowlarr
default radarr
default sonarr
dev forgejo
downloads qbittorrent
downloads qui
downloads sabnzbd
downloads slskd
kguardian kguardian
kopiur-system kopiur
matrix continuwuity
media dispatcharr
media jellyfin
media navidrome
media picard
media pinepods
media plex
media suwayomi
observability gatus
observability grafana-instance
observability victoria-logs
observability victoria-metrics
observability victoria-traces
security kaniop-instance
selfhosted immich
selfhosted miniflux
selfhosted ntfy
selfhosted paperless
selfhosted searxng
selfhosted tranquil
TARGETS

flux resume kustomization cnpg-cluster --namespace database
kubectl annotate resourceset/cnpg-cluster \
  --namespace database \
  fluxcd.controlplane.io/reconcile=enabled \
  --overwrite

flux resume kustomization cluster-apps --namespace flux-system
flux resume kustomization flux-system --namespace flux-system
BASH
```

## Recovery verification

```bash
kubectl get kustomizations --all-namespaces
kubectl get helmreleases --all-namespaces
kubectl get cluster/postgres --namespace database
kubectl get kanidm/kanidm --namespace security
kubectl get pods --all-namespaces
kubectl exec --namespace rook-ceph deployment/rook-ceph-tools -- ceph status
```

All resumed Kustomizations and HelmReleases should become ready. PostgreSQL
should report two ready instances, and Ceph should remain `HEALTH_OK`.

## Aborting the process

If shutdown fails before PostgreSQL hibernates, fix or inspect the reported
workload and rerun the shutdown block. The operations are idempotent.

If maintenance is cancelled after PostgreSQL hibernates, run the complete
recovery procedure. Do not resume only the root Flux Kustomizations: doing so
can start clients before PostgreSQL, identity, and observability storage are
ready.
