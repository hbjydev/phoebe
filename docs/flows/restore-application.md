# Restore an application

Use this procedure to recover one application volume from a Kopiur backup.
Start with a restore drill, a practice recovery into a separate volume.
Keep the original volume until the application works and its recovery period ends.

A PVC is a Kubernetes request for persistent storage.
A Kopiur `Snapshot` identifies a backup in object storage.
A CSI `VolumeSnapshot` is a storage-level snapshot that remains dependent on its storage system.
Read [Backups](./backups.md) for the backup destinations and coverage.

This procedure uses the Kopiur `0.10.17` API configured in this repository.
It does not recover NAS files or PostgreSQL databases.
For an application with PostgreSQL data, coordinate its recovery point with [Restore PostgreSQL](./restore-postgres.md).

## Prepare the drill

Run these commands from the repository root in one Bash session with the mise environment active.
Use `kubectl`, the Kopiur plugin, and Python 3 from that environment.
Mise sets `KUBECONFIG` to `talos/kubeconfig` for this repository.
Replace every `REPLACE_` value before continuing.

These commands read cluster state and create a local evidence directory:

```bash
set -euo pipefail
umask 077
namespace='REPLACE_NAMESPACE'
policy='REPLACE_POLICY'
source_pvc='REPLACE_SOURCE_PVC'
workdir=$(mktemp -d /tmp/phoebe-restore.XXXXXX)
printf 'Evidence directory: %s\n' "$workdir"
kubectl cluster-info
kubectl -n "$namespace" get snapshotpolicy "$policy" -o yaml
kubectl -n "$namespace" get pvc "$source_pvc" --ignore-not-found -o yaml
kubectl -n "$namespace" get snapshots.kopiur.home-operations.com \
  --sort-by=.metadata.creationTimestamp
kubectl get clusterrepository hetzner -o yaml
kubectl get storageclass miroir-local -o yaml
kubectl get miroirnodes -A
kubectl get namespace "$namespace" -o yaml
```

Make sure that Miroir and the `hetzner` repository report healthy conditions.
Make sure that the node has capacity for another copy of the volume.
Record the application image, volume size, access mode, and numeric user and group IDs.
If the original claim is missing, establish its identity from the Git manifest and backup evidence.
Keep the evidence directory private because file paths and logs can reveal application details.

This example restores one filesystem volume into `miroir-local` with `ReadWriteOnce` access.
If the application needs multiple volumes, prepare one reviewed restore per volume.
If its storage requirements differ, adapt the target before creating resources.
Stop if the backup coverage or application recovery point is unclear.

## Select an exact backup

Choose a backup from before the incident or a known application state.
Do not select an `Unchanged` row without a snapshot ID.
Such a row reports a successful backup attempt, not a new restore point.
See the [Snapshot reference](https://kopiur.home-operations.com/reference/crds/snapshot/) for its status fields.

Set the selected name and read its evidence:

```bash
snapshot='REPLACE_SNAPSHOT'
kubectl -n "$namespace" get snapshot.kopiur.home-operations.com "$snapshot" \
  -o json > "$workdir/snapshot.json"
python3 - "$workdir/snapshot.json" <<'PY'
import json, sys
snapshot = json.load(open(sys.argv[1]))
status = snapshot.get('status', {})
assert status.get('phase') in ('Succeeded', 'Discovered'), 'Select a completed backup'
assert not status.get('stats', {}).get('filesFailed', 0), 'Backup contains unreadable files'
point = status.get('snapshot', {})
assert point.get('kopiaSnapshotID'), 'Snapshot has no restore point'
if snapshot.get('spec', {}).get('pin'):
    assert any(c.get('type') == 'Pinned' and c.get('status') == 'True'
               for c in status.get('conditions', [])), 'Wait for snapshot pinning'
print(json.dumps({'snapshot': point, 'resolved': status.get('resolved')}, indent=2))
PY
```

Make sure that the recorded identity and source path identify the intended volume.
Make sure that the repository is `ClusterRepository/hetzner`.
If either identity is missing or ambiguous, stop and inspect the catalog before proceeding.
If retention can remove the backup during recovery, arrange a retention hold before selecting its final ID.
Pinning can change the ID, so capture the evidence again after pinning completes.

The manifest below uses `snapshotRef` to name this specific backup.
The shared application component instead uses `fromPolicy` with `onMissingSnapshot: Continue`.
Do not copy that behavior into an incident restore: it permits an empty volume when no backup exists.
See the [Restore reference](https://kopiur.home-operations.com/reference/crds/restore/) for source selection and failure behavior.

## Create a separate restore target

Choose a unique short name, the required capacity, and the application user and group IDs.
The inspection pod runs with those IDs and mounts only the new volume.
It does not start the application or connect to its database.

```bash
restore="drill-$(date -u +%Y%m%d%H%M%S)"
capacity='REPLACE_CAPACITY'
app_uid='REPLACE_NUMERIC_UID'
app_gid='REPLACE_NUMERIC_GID'
```

The mover, a temporary pod that copies backup data, uses root to preserve ownership and filesystem timestamps.
The manifest grants only the capabilities needed to restore file ownership and permissions.
The application and inspection pod keep their normal user IDs.

Make sure that the namespace permits root movers through `kopiur.home-operations.com/privileged-movers: "true"`.
If admission rejects the mover, stop and review the namespace policy.
Do not weaken the namespace policy as an automatic retry.
See [Kopiur security contexts](https://kopiur.home-operations.com/security-context/) for the required permission model.

Write the local manifest:

```bash
cat > "$workdir/restore.yaml" <<YAML
apiVersion: kopiur.home-operations.com/v1alpha1
kind: Restore
metadata:
  name: ${restore}
  namespace: ${namespace}
spec:
  source:
    snapshotRef:
      name: ${snapshot}
      namespace: ${namespace}
  target:
    populator: {}
  credentialProjection:
    enabled: true
  policy:
    onMissingSnapshot: Fail
  options:
    ignoreErrors: false
    ignorePermissionErrors: false
    skipOwners: false
    skipPermissions: false
  failurePolicy:
    backoffLimit: 1
    activeDeadlineSeconds: 3600
  mover:
    privilegedMode: true
    podSecurityContext:
      runAsUser: 0
      runAsGroup: 0
      runAsNonRoot: false
      fsGroup: 0
      fsGroupChangePolicy: OnRootMismatch
    securityContext:
      runAsUser: 0
      runAsGroup: 0
      runAsNonRoot: false
      privileged: false
      capabilities:
        drop: [ALL]
        add: [CHOWN, DAC_OVERRIDE, FOWNER, FSETID]
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ${restore}
  namespace: ${namespace}
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: miroir-local
  resources:
    requests:
      storage: ${capacity}
  dataSourceRef:
    apiGroup: kopiur.home-operations.com
    kind: Restore
    name: ${restore}
---
apiVersion: v1
kind: Pod
metadata:
  name: ${restore}-inspect
  namespace: ${namespace}
spec:
  automountServiceAccountToken: false
  restartPolicy: Never
  securityContext:
    runAsUser: ${app_uid}
    runAsGroup: ${app_gid}
    runAsNonRoot: true
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: inspect
      image: busybox:1.37.0
      command: [sleep, "86400"]
      resources:
        requests:
          cpu: 1m
          memory: 16Mi
        limits:
          memory: 64Mi
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: [ALL]
      volumeMounts:
        - name: data
          mountPath: /data
          readOnly: true
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: ${restore}
        readOnly: true
YAML
```

For an application that runs as root, review the inspection identity and `runAsNonRoot` together.
Review all names, IDs, and capacity in the generated file.
Make sure that no target name matches an existing application claim.
The inspection pod also triggers provisioning because `miroir-local` uses `WaitForFirstConsumer`.

The next command sends the manifest for admission without storing resources:

```bash
kubectl create --dry-run=server -f "$workdir/restore.yaml"
```

The following commands change the cluster by creating the restore, new claim, and inspection pod:

```bash
kubectl create -f "$workdir/restore.yaml"
kubectl -n "$namespace" wait "restore.kopiur.home-operations.com/$restore" \
  --for=jsonpath='{.status.phase}'=Completed --timeout=60m
kubectl -n "$namespace" wait "pod/$restore-inspect" \
  --for=condition=Ready --timeout=10m
```

If either wait fails, stop before switching the application.
Keep the original claim and the partial restore for diagnosis.
A wait timeout does not cancel the restore.

## Make sure that the restored data is usable

These commands read the restore result and the new volume:

```bash
kubectl -n "$namespace" get restore.kopiur.home-operations.com "$restore" \
  -o json > "$workdir/result.json"
kubectl -n "$namespace" get pvc "$restore" -o yaml
kubectl kopiur -n "$namespace" logs restore "$restore" > "$workdir/mover.log"
kubectl -n "$namespace" exec "$restore-inspect" -- id
kubectl -n "$namespace" exec "$restore-inspect" -- ls -lan /data
python3 - "$workdir/snapshot.json" "$workdir/result.json" <<'PY'
import json, sys
snapshot, restore = (json.load(open(path)) for path in sys.argv[1:])
status = restore.get('status', {})
assert status.get('phase') == 'Completed', 'Restore is incomplete'
assert status.get('resolved', {}).get('kopiaSnapshotID') == \
    snapshot['status']['snapshot']['kopiaSnapshotID'], 'Restore point does not match'
print('The restore used the selected snapshot ID.')
PY
```

Make sure that the PVC is `Bound`.
Make sure that the mover log contains no skipped files or permission failures.
Inspect known files and expected record dates through the read-only mount.
Make sure that the application user can read the required files.
Make sure that numeric ownership matches the application configuration.

For an application test, isolate a copy from production databases, queues, scheduled jobs, and external integrations.
If you cannot provide that isolation, stop after file inspection and record that limitation.
A completed file restore alone does not prove that the application can recover.

Record the snapshot ID, application version, test results, elapsed time, and missing coverage in the recovery record.
Preserve `$workdir` outside temporary storage before ending the incident.
Keep the source snapshot available until the recovery record is complete.

## Switch a production application

Use the successful drill volume only after preparing an application-specific switch plan.
The plan must name every writer, owning controller, and Flux resource that can recreate a writer.
Include background jobs, other applications, and external database dependencies.

Use this order:

1. Record the current claim names, replica counts, suspension states, and deployed image versions.
2. Pause traffic and jobs that can submit new writes.
3. Suspend the relevant Flux parents before their child Kustomizations and HelmReleases.
4. Pause application-specific operators or autoscalers that can restart writers.
5. Stop every writer and make sure that no pod still mounts the original claims.
6. Complete any coordinated database recovery before starting the application.
7. Remove the inspection pod after its results are recorded.
8. Change the application configuration to reference the restored claim.
9. Start the application with the compatible image version and the reviewed configuration.
10. Make sure that the application reads the expected data and completes a controlled write.
11. Align the Git manifests with the recovered claim before resuming Flux.
12. Restore the recorded controller, schedule, and traffic states.

Use [Maintenance](./maintenance.md) for a planned node reboot or shutdown.
Prepare separate writer controls for an application restore.
Do not assume that scaling a Deployment stops an operator-managed service.
If a StatefulSet uses claim templates, prepare a separate controller plan before changing its storage.

Keep the original PVC and its data during the recovery period.
The `miroir-local` storage class uses `reclaimPolicy: Delete`, so deleting its claim can delete the backing volume.
Do not remove an old claim from a Flux inventory until its pruning behavior preserves the required recovery copy.

Update the backup policy to protect the recovered claim.
Make sure that a new backup completes before declaring production recovery complete.
If the restored application changes its database schema, assess that change before attempting an image rollback.

## Handle failure or interruption

Read the failure without changing the restore:

```bash
kubectl -n "$namespace" get restore.kopiur.home-operations.com "$restore" -o yaml
kubectl -n "$namespace" describe pvc "$restore"
kubectl -n "$namespace" get pods,jobs
kubectl kopiur -n "$namespace" logs restore "$restore"
```

If the restore still runs, wait or diagnose that operation before creating another.
If it fails, record its failure and fix the source, capacity, credentials, or permission cause.
Retry with a new restore name and a new empty claim after the previous mover stops.
Do not enable permission-error suppression to obtain a successful status.

If the switch fails before new writes, stop the recovered application before restoring the original claim reference.
If new writes occurred, keep both volumes and decide how to reconcile their data before switching back.
Resume only the controller and schedule states recorded before the operation.

For drill cleanup, remove the inspection pod first.
Remove only the named drill claim and Restore after making sure that no workload uses them.
Make sure that any associated temporary PVCs disappear through normal controller cleanup.
Keep the backup Snapshot and original application claim out of the cleanup operation.
