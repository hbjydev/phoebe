# Persistent storage maintenance

The Kubernetes just module provides independent shutdown and restore stages for
PostgreSQL clients, Dragonfly clients, and Rook-Ceph PVC consumers. Run these
commands from the repository with its mise environment active; they require
`just`, `python3`, and `kubectl`, and the context must be `admin@phoebe`.

## Inspect and preview

Inspect storage health, backups, and running workloads before starting:

```bash
kubectl config current-context
kubectl get cephcluster --namespace rook-ceph
kubectl exec --namespace rook-ceph deployment/rook-ceph-tools -- ceph status
kubectl get backup.postgresql.cnpg.io --all-namespaces
kubectl get volumesnapshot --all-namespaces
kubectl get pods --all-namespaces

just kube maintenance-plan postgres
just kube maintenance-plan dragonfly
just kube maintenance-plan ceph
```

The plan commands are read-only. They show both consumers and reconciliation
controllers that must stop. Do not proceed with Ceph maintenance if Ceph reports
`HEALTH_ERR`. Allow backup and restore operations to finish first.

## Staged shutdown

```bash
just kube shutdown-postgres
just kube shutdown-dragonfly
just kube shutdown-ceph
```

| Stage | What stops | What stays running |
| --- | --- | --- |
| `postgres` | PostgreSQL client Deployments, StatefulSets, DaemonSets, applicable CronJobs, and PostgreSQL backup schedules | PostgreSQL and its pooler |
| `dragonfly` | Clients of all Dragonfly instances | Dragonfly instances and their operator |
| `ceph` | Direct Ceph PVC consumers, PostgreSQL clients, observability writers, and backup schedules; PostgreSQL hibernates, snapshots complete, then Kopiur stops | Rook, Ceph daemons, CSI, and CloudNativePG |

Each stage can be used independently. The Ceph stage also stops PostgreSQL
clients because PostgreSQL's own PVCs use Ceph. The first two stages give you a
point to perform separate database or Dragonfly maintenance before continuing.
These tasks do not shut down the Dragonfly instances themselves.

### Automatic maintenance snapshots

`shutdown-ceph` includes a mandatory snapshot step. It pauses PostgreSQL and
Kopiur schedules, stops application writers, and hibernates PostgreSQL. While
Kopiur, the snapshot controller, Ceph, and CSI remain running, it then:

1. Creates a CSI `VolumeSnapshot` for every bound Ceph PVC and waits for
   `status.readyToUse=true`. This includes volumes without a Kopiur policy,
   unused volumes, caches, and PostgreSQL's primary and replica volumes.
2. Creates a manual Kopiur `Snapshot` for every configured policy and waits for
   `Succeeded` or `Unchanged`. Failed runs or unreadable files block shutdown.
3. Waits for other queued Kopiur operations and active movers to finish before
   stopping Kopiur and performing the final Ceph consumer check.

The live inventory inspected during implementation has 48 Ceph PVCs and 26
Kopiur policies. CSI snapshots remain on Ceph; only the configured Kopiur policies
upload backups to their repositories. A CSI snapshot alone does not protect
against losing the Ceph storage itself.

The helper uses the Kubernetes APIs directly; the `kubectl kopiur` plugin is not
required. Home Assistant's maintenance invocation uses the root mover settings
already specified in its repository configuration, because its older live
`IfNotPresent` policy still uses UID 1000.

Snapshot names and the maintenance run label are saved before shutdown begins.
A timeout or interrupted command reuses the same requests on the next run;
an older successful snapshot does not satisfy the new run. Each snapshot wait
has a one-hour timeout. Failed snapshot objects remain available for inspection,
and Kopiur stays running if the snapshot step fails. Fix the failure and remove
its failed request before rerunning to recreate it, or use `restore-ceph` to
cancel maintenance.

The resulting snapshots remain after recovery. Inspect them using the run label
printed by the helper:

```bash
kubectl get volumesnapshot,snapshots.kopiur.home-operations.com --all-namespaces \\
  --selector maintenance.home.arpa/run=RUN
```

Remove CSI snapshots when you no longer need those maintenance restore points;
their snapshot class's deletion policy controls removal of the underlying Ceph
snapshots. Kopiur requests follow each policy's deletion and repository retention
settings. The status checks follow the installed CRD
schemas and the [Kopiur Snapshot reference](https://kopiur.home-operations.com/reference/crds/snapshot/).

The helper discovers database clients from Pod dependency labels and PostgreSQL
configuration references. LiveKit is explicitly included because its Dragonfly
connection lives in a Secret. Ceph detection uses StorageClass provisioners,
bound PV CSI drivers, mounted claims, and StatefulSet claim templates. An unknown
operator owner or an applicable autoscaler aborts planning before any mutation.
When adding a client configured only through a Secret, add its dependency label
(or an explicit supplemental target) so discovery includes it.

Flux's operator, Kustomize controller, and Helm controller are temporarily scaled
to zero so GitOps cannot reset the maintenance changes. Operators owning selected
workloads also stop. These reconciliation controllers remain stopped until the
last active maintenance stage is restored. Other applications continue running,
but GitOps changes are held during this period. The Flux source controller keeps
running.

Deployments and StatefulSets scale to zero. DaemonSets receive a temporary node
selector that matches no node. The tasks wait for active consumer Pods to
terminate, including terminating Pods. Active Jobs, backup movers, and unmanaged
consumers must finish naturally; the helper does not delete them. An active
PostgreSQL backup also blocks verification. Consumer checks time out after ten
minutes and report the remaining consumers; snapshot waits allow one hour.

PostgreSQL uses CloudNativePG's
[declarative hibernation](https://cloudnative-pg.io/docs/1.30/declarative_hibernation/),
which retains its PVCs. The Ceph task verifies hibernation and checks every active
non-Rook Pod for Ceph mounts before reporting success. A failed check means the
storage layer is not ready to stop.

## Recovery

Recover Ceph and its CSI drivers first, and inspect Ceph health again. If you
separately stopped PostgreSQL or Dragonfly, bring those services back before
restoring their clients.

```bash
kubectl exec --namespace rook-ceph deployment/rook-ceph-tools -- ceph status

just kube restore-ceph
just kube restore-dragonfly
just kube restore-postgres
```

The Ceph restore rehydrates PostgreSQL and waits for its configured number of
ready instances, then restores consumers before observability writers and
backup schedules. Each resumed Deployment, StatefulSet, and DaemonSet must
complete its rollout. Reconciliation controllers restore last.

Every task saves its inverse before changing the cluster in
`kubernetes/.maintenance-state.json` (ignored by Git). Recovery restores the
original replica counts, node selectors, schedule suspension values, and
hibernation annotation. Already-stopped services remain stopped. Keep this file
until recovery finishes, and use the same checkout and kubeconfig for all stages.
Do not run concurrent maintenance sessions from different checkouts.

Overlapping stages hold a shared consumer down until every stage that selected
it has been restored. For example, Forgejo stays stopped after `restore-ceph`
and `restore-dragonfly` if the `postgres` stage is still active. The state file
is removed after the final successful restore.

## Verification and interrupted operations

```bash
kubectl get deployments,statefulsets,daemonsets --all-namespaces
kubectl get kustomizations,helmreleases --all-namespaces
kubectl get cluster.postgresql.cnpg.io/postgres --namespace database
kubectl get pods --all-namespaces
kubectl exec --namespace rook-ceph deployment/rook-ceph-tools -- ceph status
```

Reconciliation should return to its previous state after the final restore.
Workloads should return to their saved replica counts, and PostgreSQL should
report its configured number of ready instances.

If shutdown fails, inspect the reported consumers and rerun the same shutdown
task, or run its restore task to cancel maintenance. Repeating a stage preserves
its original recovery values. If restore fails, fix the reported issue and rerun
it; the saved state remains available. A replaced resource with a different UID
requires manual review rather than applying recovery values to a new workload.

Run the helper's offline discovery and recovery tests with:

```bash
python3 -m unittest discover -s kubernetes -p 'test_maintenance.py'
```
