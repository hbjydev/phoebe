# Ceph migration research

Researched 2026-10-19 against current upstream documentation and source. This is
an investigation and proposed migration sequence; it does not deploy a CSI or
change existing storage. Longhorn is excluded by the user's decision.

## Recommendation

Start with **Miroir using local LVM-thin volumes**, with **OpenEBS LocalPV LVM as
the fallback**. This preserves the previous direction: reduce storage overhead
on one Talos node now, retain a path to replication when more nodes exist, and
prove that ordinary maintenance can replace the current manual shutdown
workflow. Treat the maintenance improvement as an acceptance test, not a promise
that changing CSI alone fixes every drain or application shutdown dependency.

OpenEBS is a family of engines. LocalPV LVM and ZFS are local storage;
Mayastor is the replicated engine. Moving from LocalPV to Mayastor later is a
second storage migration, rather than enabling replication on existing local
volumes. The local engines bind data to their node. [LVM architecture](https://github.com/openebs/lvm-localpv),
[ZFS architecture](https://github.com/openebs/zfs-localpv).

| Candidate | Fit for this investigation | Main qualification |
| --- | --- | --- |
| Miroir, local LVM-thin | First pilot; Talos is an explicit primary target | Young driver with operational changes between minor releases |
| OpenEBS LocalPV LVM | Established local-storage fallback | No cross-node replication or automatic data failover |
| OpenEBS LocalPV ZFS | Consider if ZFS features are themselves a requirement | Adds pool/module administration; still node-local |
| OpenEBS Mayastor | Reconsider with a larger cluster and a performance requirement | Three-node supported minimum and substantial dedicated resources |

These are recommendations inferred from the sourced capabilities below, not
benchmark results for Phoebe.

## Recovered context and current Phoebe inventory

The earlier chat, **Compare CSI options** (2026-10-13), established one Talos
node, a maximum 1Gbps network, a preference for local disk performance, tolerance
for Miroir's immaturity, future multi-node growth, and rejection of Longhorn.
The main objective was easier maintenance without manually stopping every
storage consumer. That chat recommended Miroir first and LocalPV LVM as the
fallback, conditional on an upgrade rehearsal. The local Codex memory database
had no matching storage records; the original chat supplied this context.

Read-only Kubernetes and Ceph queries on 2026-10-19 established:

| Item | Observed state |
| --- | --- |
| Node | One Ready node, Talos 1.14.1, Kubernetes 1.37.0 |
| Claims | 48 bound `ceph-block` PVCs, all ReadWriteOnce |
| Provisioned capacity | 787.5GiB; this is not the amount to copy |
| Ceph capacity | 932GiB raw, 103GiB used; block pool reports 101GiB stored |
| Kopiur coverage | 26 policies covering 26 claims; 22 claims have no Kopiur policy |
| PostgreSQL | Two PVCs; separate daily CNPG backups, latest completed 2026-10-19 00:32:14 UTC |

These observations came from `kubectl get nodes,pvc`, separate listings of
Kopiur policies and CNPG backups, and `ceph df` through the toolbox. They are a
point-in-time inventory, not restore validation or proof of application-used
bytes. No cluster objects were changed.

The [Ceph manifest](../../kubernetes/apps/rook-ceph/rook-ceph/cluster/helmrelease.yaml)
uses one monitor, pool replication size 1 and a particular NVMe device, with no
CephFS or RGW. It requests 4GiB memory per OSD, 1GiB for the monitor and 512MiB
for the manager, before CSI/operator overhead. Comparing this with candidate
requests suggests room to save resources, but actual savings need measurement.
The [Talos inventory](../../talos/topf.yaml) also has one node; its configured
Talos version is 1.14.0, while the live node is already 1.14.1.

Claims without Kopiur need individual treatment:

- PostgreSQL has Barman backups; use CNPG recovery into a new cluster with the
  new StorageClass, including required WAL and extension images. A completed
  backup status alone is not a verified recovery. [CNPG recovery](https://github.com/cloudnative-pg/cloudnative-pg/blob/main/docs/src/recovery.md).
- Active claims needing a preservation decision include `ai/mcp-auth-proxy`,
  `downloads/config-slskd-0`, `observability/config-gatus-0`,
  `observability/grafana-pvc`, the VictoriaLogs/Metrics/Traces claims, and
  `security/kanidm-data-kanidm-default-0`. Absence of a Kopiur policy does not
  rule out application-native protection; verify it.
- Seven apparent cache/model-cache claims need confirmation that their contents
  can be regenerated. Names alone are insufficient to discard data.
- Five claims had no Pod consumers: `ai/openclaw-misc`, the old Prometheus and
  Alertmanager claims, `observability/gatus`, and the Nextcloud Redis claim.
  Decide whether to archive or restore them; absence of consumers is not
  authorization to delete them.

Kopiur's [Hetzner repository](../../kubernetes/apps/kopiur-system/kopiur/repository/clusterrepository.yaml)
is external S3, and PostgreSQL has a separate external
[Barman object store](../../kubernetes/apps/database/postgres/cluster/objectstore.yaml).
The recovery path therefore need not depend on the Ceph-backed Garage instance.
Keep access credentials and the Kopia encryption password independently usable.

The shared [Kopiur component](../../kubernetes/components/kopiur/pvc.yaml)
already exposes `KOPIUR_STORAGECLASS`; its snapshot policy exposes
`KOPIUR_SNAPSHOTCLASS`. However, resources marked `IfNotPresent` and existing
bound PVCs will not migrate just because defaults change. Its bootstrap Restore
uses `onMissingSnapshot: Continue`. For migration, create a fresh Restore pinned
to the intended backup and use `onMissingSnapshot: Fail`; preserve the source
identity when target names change. Kopiur pins restore resolution once, so
reusing an old bootstrap Restore can select the wrong recovery point.
[Restore semantics](https://kopiur.home-operations.com/reference/crds/restore/).

## Missing snapshot policy review

Follow-up read-only inspection on 2026-10-19 confirmed 22 persistent application
claims without Kopiur policies. Two additional claims observed during this check
were temporary source PVCs owned by running Kopiur Snapshot operations for Plex
and Immich; they do not need their own policies. None of the 22 application
claims had an extant CSI VolumeSnapshot referencing it at inspection time.

The eight active state/history volumes are:

| PVC | Approximate filesystem usage | Evidence and recommendation |
| --- | --- | --- |
| `security/kanidm-data-kanidm-default-0` | 48MiB | Identity service state; highest priority. No backup-related fields in the live Kanidm spec and no external backup configuration found in Git. Add protection and verify recovery before migration. |
| `ai/mcp-auth-proxy` | 180KiB | `/data` contains `db`, `private_key.pem`, and `secret`. Preserve the whole volume. |
| `observability/grafana-pvc` | 270MiB | `/var/lib/grafana` contains `grafana.db` plus plugins and other directories. Preserve local state even though much configuration is declarative. |
| `downloads/config-slskd-0` | 3.6MiB | `/config` contains data, scripts, logs and download directories; configuration also comes from a mounted file. Back up the whole claim. |
| `observability/config-gatus-0` | 5.3MiB | Active StatefulSet claim; configured SQLite database `/config/gatus.db`. Preserve uptime history. The separate `observability/gatus` claim is unused by current Pods. |
| `observability/vmsingle-victoria-metrics` | 15.4GiB | Metrics history; preserve by default unless losing history is explicitly acceptable. |
| `observability/vlsingle-victoria-logs` | 6.8GiB | Logs history; same preservation decision. |
| `observability/vtsingle-victoria-traces` | 431MiB | Trace history; same preservation decision. |

Sizes come from kubelet volume statistics and fluctuate; they are neither
requested capacities nor predicted compressed backup sizes. Directory inspection
read names, ownership and usage only, not file contents. Gatus, Kanidm, Logs and
Traces images lack `sh`, so their directories/ownership were not inspected;
their sizes came from kubelet statistics.

The remaining fourteen claims do not imply fourteen missing generic policies:

- `database/postgres-2` and `postgres-3`: retain application-native Barman
  protection; the latest completed backup was still 2026-10-19 00:32:14 UTC.
  Validate WAL coverage and perform a restore drill instead of treating a live
  generic PVC copy as an equivalent PostgreSQL backup.
- `ai/llmkube-model-cache` (`/models`), `default/home-assistant-cache`
  (`/config/.venv`), `default/jellyseerr-cache` (`/app/config/cache`),
  `default/radarr-cache` and `default/sonarr-cache` (`/config/MediaCover`),
  `media/jellyfin-cache` (`/cache`), and `selfhosted/immich-machine-learning`
  (`/cache`): live mounts support classifying these as regeneration candidates.
  Verify model sources remain available and accept rebuild/download time before
  excluding them from migration backups.
- No current Pod mounts `ai/openclaw-misc`, `observability/gatus`,
  `observability/prometheus-kube-prometheus-stack-db-prometheus-kube-prometheus-stack-0`,
  `observability/alertmanager-kube-prometheus-stack-db-alertmanager-kube-prometheus-stack-0`,
  or `selfhosted/redis-data-nextcloud-redis-master-0`. Retain pending an explicit
  archive/discard decision. Their contents were not mounted or inspected.

For implementation, add backup-only SnapshotPolicy resources targeting the
existing claim names, plus schedules where application consistency is handled.
Do not blindly attach the entire shared Kopiur component: it also creates a PVC
and Restore and could target the wrong claim for operator/StatefulSet volumes.
The default mover UID/GID 1000 fits the observed MCP auth, Grafana and slskd data.
VictoriaMetrics currently writes as root; Gatus uses pod user namespaces. Check
readability and ownership on restored snapshots before choosing their mover
security settings, and verify Kanidm/Logs/Traces separately.

For the migration, take the final snapshots after clean application shutdown,
then upload them through Kopiur to Hetzner. Scheduled live snapshots need an
application-consistency plan: Kanidm documents native online backups or a
stopped full-directory copy, while Grafana documents stopping the service before
copying SQLite. Keep Kanidm's exact server version available for recovery.
[Kanidm backup and restore](https://kanidm.github.io/kanidm/stable/backup_and_restore.html),
[Grafana backup](https://grafana.com/docs/grafana/latest/administration/back-up-grafana/).
For ongoing metrics backups, evaluate native `vmbackup`; Logs and Traces also
document disk snapshots, with Traces explicitly requiring consistency. A
SnapshotPolicy alone does not prove that an application can restore.
[vmbackup](https://docs.victoriametrics.com/vmbackup/),
[VictoriaLogs](https://docs.victoriametrics.com/victorialogs/#backups),
[VictoriaTraces](https://docs.victoriametrics.com/victoriatraces/#backups).

No policies, schedules, workloads or storage objects were changed in the cluster
during this review. All eight should have a tested external recovery path before
reuse of the Ceph disk.

### Manifest implementation

The subsequent manifest change adds one SnapshotPolicy and SnapshotSchedule in
each application's `kopiur.yaml`, targeting the existing claim without creating
a new PVC or Restore:

- [MCP auth proxy](../../kubernetes/apps/ai/mcp-auth-proxy/app/kopiur.yaml)
- [slskd](../../kubernetes/apps/downloads/slskd/app/kopiur.yaml)
- [Gatus](../../kubernetes/apps/observability/gatus/app/kopiur.yaml)
- [Grafana](../../kubernetes/apps/observability/grafana/instance/kopiur.yaml)
- [Kanidm](../../kubernetes/apps/security/kaniop/instance/kopiur.yaml)
- [VictoriaMetrics](../../kubernetes/apps/observability/victoria-metrics-stack/metrics/kopiur.yaml)
- [VictoriaLogs](../../kubernetes/apps/observability/victoria-metrics-stack/logs/kopiur.yaml)
- [VictoriaTraces](../../kubernetes/apps/observability/victoria-metrics-stack/traces/kopiur.yaml)

They use the Hetzner repository, `csi-ceph-blockpool`, the existing retention
settings (8 hourly / 7 daily), and the existing 12-hour schedule with hashed
minutes and 10-minute jitter. A schedule forbids overlapping runs of itself;
different policies can still run concurrently. `runOnCreate: false` avoids an
immediate burst on installation. File/directory read errors remain fatal.

MCP auth, Grafana and slskd pin UID/GID 1000. The other five pin root, confirmed
through runtime identities, and use namespace-gated `privilegedMode` for Kopiur's
operation-specific capabilities while keeping container `privileged: false`.
Both relevant namespaces already permit elevated movers. Explicit contexts also
work when the maintenance workflow has stopped the source Pods. Gatus's user
namespace makes restored ownership a particular restore-drill check.

Each affected Flux Kustomization depends on `kopiur-repository`, which depends on
the Kopiur installation. All eight application Kustomize builds passed, and all
16 backup resources passed server-side dry-run against the installed API.
At that validation stage, nothing was deployed and no backup or restore was run.
The required follow-up was to verify all eight uploads and restore each workload;
the policies alone did not close the migration acceptance gate. Results follow.

Scheduled copies are live-volume snapshots, not application-aware exports.
They do not automatically stop writers or claim application consistency. The
existing `shutdown-ceph` workflow discovers these policies after deployment and
takes final backups after stopping consumers; retain that step for the disk
cutover. Native backup workflows or explicit quiescing can be added separately
where stronger ongoing consistency is required.

### Restore drill, 2026-10-19

After deployment, all eight new policies and schedules were Ready. The drill
used the Mise-installed `kubectl kopiur` 0.10.16 to trigger manual snapshots and
restore their exact Kopia snapshot IDs from the Hetzner repository. Production
writers remained running. All eight manual backups succeeded without reported
file errors, all eight restores completed, and the application checks below
passed. Scratch PVCs used `ceph-block` in the temporary
`storage-restore-check-20261019` namespace. Validation pods had ingress and
egress denied, no service-account token, and no Services or routes.

| Workload | Remote Kopia snapshot ID | Validation |
| --- | --- | --- |
| Kanidm | `87a183b8a103d619c9399c59473c2edd` | Restore completed; SQLite integrity and `kanidmd database verify` passed; isolated 1.11.2 server returned HTTP 200 from `/status` using disposable TLS. |
| MCP auth proxy | `94e2c59e096dc8b65082a1bf9ce60b2c` | Restore completed on retry; key and secret hashes matched the originals; mode 0600 and UID/GID 1000 preserved; running process opened restored `/data/db`; `/healthz` returned 200. |
| Grafana | `ae7bb2386477a31f42b1df8bad9105cc` | Restore completed; SQLite integrity passed; isolated server `/api/health` reported database `ok`. |
| slskd | `e38610b8129a39c4ca3acb141db14d12` | Restore completed; all nine discovered SQLite databases passed integrity checks; server used restored `/data/data` and returned HTTP 200. External shares and Soulseek connectivity were excluded. |
| Gatus | `7acb3bcb983d11b64d2ef3f55d0392ba` | Restore completed; SQLite integrity passed; `/health` returned 200, including a repeat with production's `hostUsers: false` setting. |
| VictoriaTraces | `20352f5fb8efa7b479644e5194df272d` | Restore completed; `/health` returned 200; LogsQL read a stored span and a time-bounded Jaeger query returned one trace with five spans. Latest timestamp, 2026-09-10 00:38:58 UTC, matched production. |
| VictoriaLogs | `a643da72f85a26bf5408379c4ed7e973` | Restore completed for 6,324,306,384 logical bytes across 426,323 files; `/health` returned 200; LogsQL returned a historical record timestamped 2026-10-19 12:46:50 UTC. |
| VictoriaMetrics | `56c8beeb5de1b560ac3e25072df01c1d` | Restore completed for 16,525,717,788 logical bytes across 1,509 files; `/health` returned 200; `count(up)` at 2026-10-19 12:40 UTC returned 85, matching the production query at the same timestamp. |

After validation, the scratch namespace was deleted and all eight scratch PVs
were confirmed reclaimed. Disposable TLS material was removed. All eight
production workloads and the Hetzner repository were Ready after cleanup.

Manual Snapshot names use `csi-drill-20261019-<policy>` in the source namespace,
with `deletionPolicy: Retain`. Restore names use the same prefix in the scratch
namespace; the MCP auth and Logs retries add `-r2`. Record the remote IDs rather
than relying on catalog object names remaining present indefinitely.
These recovery points remain subject to repository retention; take and record
fresh stopped-writer backups for the actual cutover.

The first MCP auth restore failed with `chown ... operation not permitted`.
The generated mover ran as UID 0 but dropped all Linux capabilities, despite
`privilegedMode: true`. A fresh restore of the same backup passed after explicitly
adding capabilities. This tested override belongs under `Restore.spec.mover`:

```yaml
privilegedMode: true
podSecurityContext:
  runAsUser: 0
  runAsGroup: 0
  runAsNonRoot: false
  fsGroup: 0
securityContext:
  runAsUser: 0
  runAsGroup: 0
  runAsNonRoot: false
  privileged: false
  capabilities:
    drop: [ALL]
    add: [CHOWN, DAC_OVERRIDE, FOWNER, FSETID]
```

The scratch namespace opted in with the
`kopiur.home-operations.com/privileged-movers: "true"` annotation. The CLI created
a passive populator Restore first; its mover was patched before creating the
claim with `dataSourceRef`, so no restore Job could start with the old settings.
All restores required missing snapshots and permission errors to fail:
`onMissingSnapshot: Fail`, `ignoreErrors: false`,
`ignorePermissionErrors: false`, `skipOwners: false`, `skipPermissions: false`.
No production mover defaults were changed. See the upstream
[security-context reference](https://kopiur.home-operations.com/security-context/)
and [Restore reference](https://kopiur.home-operations.com/reference/crds/restore/).

The first Logs restore was deliberately replaced early with a fresh target and
`--parallel 32` instead of the default eight workers, because its many small
files were restoring slowly. Both attempts used the same pinned backup and
strict error/ownership settings. This is a drill tuning choice, not a change to
production backup policy. End-to-end creation-to-Ready times for the five small
volumes were 42–62 seconds; Traces took 5 minutes 24 seconds for 10,198 files.
Metrics took 9 minutes 27 seconds for 1,509 files and 16.5GB of logical data.
Logs took 52 minutes 45 seconds with 32 workers for 426,323 files and 6.3GB.
These include scheduling and volume provisioning as well as remote restoration.
The first full Logs backup's mover ran for 12 minutes 3 seconds; Metrics took
29 minutes 29 seconds. Those upload timings exclude some staging and controller
reconciliation time. They are observations from concurrent work on this cluster,
not guaranteed cutover timings or measurements of a new CSI.

These checks exercise remote recovery into fresh Ceph volumes. They do not test
Miroir/OpenEBS, a wiped disk, a fresh cluster, full authentication flows, or every
historical record. Application startup used isolated configuration without
production integration credentials. Final stopped-writer backups, the separate
CNPG recovery drill, and the remaining PVC preservation decisions are still
required before disk reuse. Passing one live-snapshot drill does not establish
that every future live snapshot will be application-consistent.

## Miroir

The observed release page identifies **0.12.4, dated 2026-09-14**. Recent fixes
include DRBD teardown and stale replication bitmaps; the upgrade guide documents
changes to CRDs, node topology, and CSI sidecars. This supports treating Miroir as
a promising, actively changing driver whose exact version should be pinned and
tested. It does not establish production reliability from the age of DRBD or
LVM alone. [Releases](https://github.com/home-operations/miroir/releases),
[upgrade procedure](https://miroir.home-operations.com/upgrading/).

For local LVM-thin, Talos supplies `dm_thin_pool`; Miroir carries storage
userland in its agent image, so no separate LVM extension is required by its
documented setup. Replication adds the `siderolabs/drbd` extension, DRBD >=9.3.1
(documented Talos minimum 1.13.0), and module configuration disabling the host
usermode helper. Replication also requires graceful node shutdown; its default
60-second agent termination window must fit inside the critical-pod shutdown
window. Kubernetes minimum is 1.31. [Requirements](https://miroir.home-operations.com/requirements/).

The pinned 0.12.4 chart requests 10m CPU/32Mi for each of the controller,
provisioner, snapshotter, resizer and agent, plus 5m/16Mi for the node registrar.
That totals **55m CPU and 176Mi requested memory on one node**, excluding the
shared snapshot controller, kernel memory, filesystem caches and workload I/O.
These are scheduler reservations, not measured consumption. The chart declares
no hugepage reservation. [Pinned chart values](https://github.com/home-operations/miroir/blob/0.12.4/charts/miroir/values.yaml).

Use a separately owned disk/partition or existing VG, one `MiroirNode`, an
explicit local StorageClass with `replicas: "1"`, `WaitForFirstConsumer`, and
expansion enabled, plus a matching VolumeSnapshotClass. The namespace needs
privileged pod admission. The driver supports snapshots and restores; its docs
describe mounted local LVM-thin snapshots as filesystem-consistent. Application
consistency still needs application-aware backup or quiescing. Reuse the
cluster's existing snapshot controller. [Quickstart](https://miroir.home-operations.com/quickstart/).

The future replication path is explicit: **a local volume cannot gain DRBD in
place**. Snapshot or clone it into a new PVC using a replicated class, then
repoint its workload. Miroir supports up to three data replicas. With two data
replicas, default `freeze` quorum requires both unless a third node supplies a
diskless tie-breaker. With that tie-breaker, one node failure retains a majority;
without it, one node failure stops writes. `last-man-standing` permits isolated
writes but can create split-brain requiring manual resolution. [Replication and
quorum](https://miroir.home-operations.com/replication/),
[project scope](https://github.com/home-operations/miroir).

For multi-node maintenance, cordon/drain, upgrade one node, wait for all affected
volumes to become Ready after resync, then continue. A single local-storage node
necessarily has application downtime during reboot; the useful improvement is
predictable shutdown and recovery. Replication does not remove the maintenance
ordering requirements. [Maintenance](https://miroir.home-operations.com/maintenance/).

Optional RWX uses a per-volume NFS gateway, requires replicated storage and
`freeze` quorum, and documents failover stalls lasting tens of seconds. This is
available for future requirements but unnecessary for a current all-RWO
migration. [RWX](https://miroir.home-operations.com/rwx/).

## OpenEBS

The current 4.6.x release page lists LocalPV LVM **1.10.1**, LocalPV ZFS
**2.11.2**, and Mayastor **2.12.2** as Stable. It also lists single-node controller
scheduling issues on some upgrade paths and an LVM thin-pool capacity-accounting
caveat. Verify these against the chosen pinned chart during the pilot. The same
page documents that Mayastor's polling engine consumes its allocated CPU cores
even when I/O is idle. [4.6 release notes](https://openebs.io/docs/releases).

### LocalPV LVM

The driver is a CSI control plane over kernel LVM, with no separate userspace
data engine. Upstream explicitly lists Talos and says there is no strict LVM
memory requirement. It provides thin provisioning, resizing and snapshots;
current limitations include no resize while snapshots exist, no restore from
thick-volume snapshots, and no direct volume-to-volume clone. Prefer thin
volumes for a snapshot/restore workflow. [Driver documentation](https://github.com/openebs/lvm-localpv).

Unlike Miroir's pool setup, OpenEBS expects a pre-created physical volume and
volume group. Its general instructions require LVM tooling and `dm-snapshot`;
do not translate their package-manager commands literally to immutable Talos.
Provision and verify the selected VG through an explicit Talos-compatible
administrative procedure. The current chart's controller/node resource maps are
empty, so they do not provide a useful consumption estimate. Disable its bundled
snapshot controller if the cluster already owns one. [Quickstart](https://github.com/openebs/lvm-localpv/blob/develop/docs/quickstart.md),
[chart values](https://github.com/openebs/lvm-localpv/blob/develop/deploy/helm/charts/values.yaml).

A relevant, scoped maintenance report is Talos issue #13354: LUKS-encrypted
RawVolumeConfig with LVM stacked above it failed teardown on Talos 1.11.6/1.12.7
without manual VG deactivation. The issue was open when inspected. This does
**not** prove Talos 1.14 has the problem, or that unencrypted LVM is affected;
if choosing this encrypted layout, include it in the reboot/upgrade test.
[Talos issue](https://github.com/siderolabs/talos/issues/13354).

### LocalPV ZFS

ZFS supplies snapshots, restores, clones, compression and filesystem features,
but LocalPV ZFS still has no replication between nodes. The driver has a small
control-plane architecture; total memory must also account for ZFS caching and
chosen features. No reliable universal per-node footprint was established.
[Driver documentation](https://github.com/openebs/zfs-localpv).

Talos requires the ZFS extension, loaded module and deliberate pool setup.
Verify the extension against the selected Talos image and Secure Boot before
committing to this backend; this investigation did not establish that exact
combination. ZFS adds little to the initial objective unless its features are
wanted independently. [Talos ZFS extension](https://github.com/siderolabs/extensions/blob/main/storage/zfs/README.md).

### Mayastor

The supported minimum is **three worker nodes**. Each I/O engine node needs
**two exclusive CPU cores, 1GiB RAM, plus 2GiB of 2MiB hugepages**. The guide
requires x86-64/SSE4.2 and an NVMe-TCP-capable kernel; HA needs NVMe multipath.
These requirements make it a poor first answer to reducing overhead on this
single-node cluster. [Prerequisites](https://openebs.io/docs/quickstart-guide/prerequisites).

There is an official Talos installation guide. Talos-specific work includes
privileged pod admission, hugepages and labels; Sidero additionally documents
disabling the init container which checks the already built-in NVMe-TCP module.
[OpenEBS Talos guide](https://openebs.io/docs/Solutioning/openebs-on-kubernetes-platforms/talos),
[Sidero storage guide](https://docs.siderolabs.com/kubernetes-guides/csi/storage).

Mayastor supports CSI snapshots, filesystem quiescing and snapshot restore.
Snapshot capacity commitments can prevent snapshots when pools lack headroom.
Off-cluster protection still needs data movement; OpenEBS documents Velero's CSI
snapshot data mover to object storage. [Snapshots](https://openebs.io/docs/user-guides/replicated-storage-user-guide/replicated-pv-mayastor/advanced-operations/volume-snapshots),
[backup/restore example](https://openebs.io/docs/4.4.x/Solutioning/backup-and-restore/velerobrfs).

## Migration approach and acceptance gates

The user has confirmed there is no spare SSD/NVMe and intends to reuse the
current Ceph disk. **The practical path is an outage with external backup and
restore**, with preparation and restore drills done gradually beforehand. Free
space inside the existing Ceph OSD is not a separate destination for another
CSI. This sequence is a proposal for a later implementation:

1. Account for every existing PVC, including stopped workloads and caches.
   Record which need restoration, which have application-native recovery, and
   which are explicitly disposable. Measure actual data rather than treating
   requested PVC capacity as backup size.
2. Close backup gaps and rehearse restores while Ceph is available. Restore to
   disposable storage on a confirmed independent system disk with enough space,
   or a separate test environment. A loopfile pilot can validate the CSI and
   backup integration, but does not validate the eventual LVM layout. The OS
   disk being different from the Ceph disk does not establish spare capacity.
3. Keep the recovery procedure, manifests, encryption keys, object-store
   credentials and backup identifiers available independently of Ceph. Verify
   the remote Kopiur repository and database-native backups before the outage.
   Copying a snapshot object or preserving only Kubernetes manifests is
   insufficient to recover the data after reformatting.
4. At cutover, stop all writers in application dependency order, prevent GitOps
   and operators from restarting them, take final application-consistent
   backups, and wait for the **off-disk uploads** to complete. Record the exact
   backup identity for each restored workload and verify completeness.
5. Only in a later explicitly authorized implementation, remove Ceph's use of
   the disk and reprovision it for the selected CSI. This is the destructive
   boundary: after it, reverting a manifest cannot recover the old data.
6. Before restoring valuable data, test the real LVM pool with disposable
   volumes: provisioning, writes, expansion, snapshots/restores, controller and
   agent restarts, and planned Talos maintenance. Measure resources and verify
   shutdown/recovery. Investigate failures before continuing.
7. Restore databases and application volumes in dependency order. Create fresh
   target PVCs and fresh restore operations with explicit source identities;
   require missing backups to fail. Switch each application's snapshot and
   backup classes with its storage. Check ownership, permissions, data
   integrity and application behaviour, then resume schedules and writers.

After the destructive boundary, recovery depends on the external backups and
rebuilding either storage backend. Outage duration includes final backup,
reprovisioning, validation, downloads and application recovery. Benchmark a
representative restore before choosing the maintenance window.

Ceph CSI snapshots are driver-specific storage objects, not a generic image
that Miroir/OpenEBS can directly restore. The migration therefore needs backup
data movement or copying rather than changing `storageClassName` or substituting
a target CSI name in a snapshot. Kubernetes records the CSI driver and its
opaque snapshot handle in snapshot content. [Kubernetes snapshot model](https://kubernetes.io/docs/concepts/storage/volume-snapshots/),
[snapshot classes](https://kubernetes.io/docs/concepts/storage/volume-snapshot-classes/).

On the future 1Gbps replication network, wire rate is at most 125MB/s before
protocol overhead, competing traffic and disk costs (arithmetic, not a measured
benchmark). Synchronous replication and rebuilds will share that limit. Test
realistic write latency and rebuild duration before moving critical volumes to
replicated classes.

Open questions before implementation: independent restore-drill capacity, backup
coverage and restore identity for each PVC, exact chart/module versions, actual
resource savings, and whether the chosen upgrade path meets the desired
unattended recovery behaviour. No live migration or destructive disk operation
is authorized by this research note.
