# Backups

Use this guide to inspect backup coverage and create an application backup.
For recovery, use [Restore an application](./restore-application.md) or [Restore PostgreSQL](./restore-postgres.md).

## What protects the data

A persistent volume claim (PVC) requests storage for a workload.
A snapshot records data at a point in time.
A mover is the Job that transfers backup files.
Kopiur uses Kopia to copy files from selected volumes into Hetzner object storage.
Miroir supplies the local storage and volume snapshots.

A `SnapshotPolicy` defines the source volumes, destination, and retention rules.
A `SnapshotSchedule` starts the policy on a schedule.
A `Snapshot` records one backup operation and its result.
These resources cover only their declared sources.
A PVC without a matching policy is not covered by Kopiur.

The [shared Kopiur component](https://github.com/hbjydev/phoebe/tree/main/kubernetes/components/kopiur) uses `copyMethod: Snapshot` and `miroir-snap`.
Kopiur mounts a temporary volume from the Miroir snapshot, then copies its files to the repository.
The [copy-method reference](https://kopiur.home-operations.com/copy-methods/) explains this sequence and its limits.

Do not treat a local volume snapshot as an off-node backup.
The default [Miroir storage class](https://github.com/hbjydev/phoebe/blob/main/kubernetes/apps/miroir-system/miroir/config/storageclass.yaml) uses one replica.
Losing its disk can also lose its local snapshots.

PostgreSQL uses CloudNativePG and Barman for separate database backups and transaction-log archives.
Its [object store](https://github.com/hbjydev/phoebe/blob/main/kubernetes/apps/database/postgres/cluster/objectstore.yaml) points to `s3://phoebe-postgres` with a `14d` retention policy.
The application file backup does not replace the database backup.

An application can also depend on NAS files, external services, and secrets.
Do not infer their protection from a successful PVC backup.
Make sure that the recovery plan covers every dependency.

## Destination and schedules

The [Hetzner repository](https://github.com/hbjydev/phoebe/blob/main/kubernetes/apps/kopiur-system/kopiur/repository/clusterrepository.yaml) is named `hetzner`.
It uses bucket `phoebe-backup`, prefix `kopiur`, and endpoint `hel1.your-objectstorage.com`.
Its credentials and Kopia encryption password come from `kopiur-system/kopia-hetzner-secret`.
Keep access to those credentials available outside the cluster.
Do not print their values in incident notes or agent output.

The shared schedule uses `H */12 * * *`, with up to ten minutes of jitter.
Jitter adds a delay to spread backup operations.
`H` selects a stable minute rather than starting every policy together.
The schedule forbids overlapping scheduled operations and does not run when first created.
See the [schedule documentation](https://kopiur.home-operations.com/backups/#snapshotschedule-the-cron) for scheduling behavior.

The shared retention values are `keepHourly: 8` and `keepDaily: 7`.
These values select hourly and daily retention buckets.
They do not create hourly backups or guarantee eight distinct hourly recovery points.
The [Garage policies](https://github.com/hbjydev/phoebe/blob/main/kubernetes/apps/garage-system/garage/app/kopiur.yaml) use different values.
Read the selected live policy before a backup or restore.

The shared resources carry Flux's `IfNotPresent` label.
Flux creates missing resources but does not replace existing resources with that policy.
An edit to the shared defaults does not prove that an existing live policy changed.
Compare its live values with the intended repository configuration.

## Select the target

Run these commands in Bash on your administration machine, from the repository root.
Use the tools and environment from `mise.toml`.
Mise sets `KUBECONFIG` to `talos/kubeconfig` for this repository.
The Kopiur commands require the `kubectl-kopiur` plugin.

Start with these read-only commands:

```bash
kubectl kopiur --version
kubectl get nodes -o wide
kubectl get clusterrepositories.kopiur.home-operations.com
kubectl get snapshotpolicies.kopiur.home-operations.com -A
```

Make sure that the node identity matches `talos/topf.yaml`.
The manifests describe intended configuration, not proof of live backup health.

Select an existing namespace and policy from the output:

```bash
BACKUP_NAMESPACE='REPLACE_WITH_NAMESPACE'
BACKUP_POLICY='REPLACE_WITH_POLICY'
```

## Inspect coverage and health

Read the selected policy, its schedules, and the repository status:

```bash
kubectl -n "$BACKUP_NAMESPACE" \
  get snapshotpolicy.kopiur.home-operations.com "$BACKUP_POLICY" -o yaml
kubectl -n "$BACKUP_NAMESPACE" \
  get snapshotschedules.kopiur.home-operations.com -o yaml
kubectl \
  get clusterrepository.kopiur.home-operations.com hetzner -o yaml
kubectl -n "$BACKUP_NAMESPACE" get pvc
kubectl -n "$BACKUP_NAMESPACE" \
  get snapshots.kopiur.home-operations.com --sort-by=.metadata.creationTimestamp
```

Make sure that `spec.sources` names the intended volumes.
Make sure that each source PVC is `Bound`.
Make sure that the policy targets the intended repository and snapshot class.
If it targets another repository, inspect that repository instead of `hetzner`.

Read the status conditions and their messages.
Stop if the repository is not ready or the policy reports an unresolved error.
Compare the latest successful backup time with the live schedule and its delay.
If a backup or restore is still running for these volumes, let it finish before maintenance.

Use the policy inventory to find gaps:

```bash
kubectl get pvc -A
kubectl get snapshotpolicies.kopiur.home-operations.com -A \
  -o 'custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,PVCS:.spec.sources[*].pvc.name'
kubectl -n database get scheduledbackups.postgresql.cnpg.io
kubectl -n database get backups.postgresql.cnpg.io
```

Record unmatched application volumes and their intended protection.
Account separately for PostgreSQL and disposable data.
Do not count an empty policy column as proof that a volume is protected.
Inspect any policy that uses a source selector or another source type.

## Create an application backup

This step changes the live cluster and writes data to Hetzner.
It creates a Kopiur `Snapshot` and temporary backup resources.
Use it only for the selected application policy.

The command can back up a running application.
A volume snapshot alone does not coordinate application transactions across files, volumes, or PostgreSQL.
For a coordinated recovery point, prepare the writer controls described in [application recovery](./restore-application.md#switch-a-production-application).
Stop the selected writers before capturing their data.
If the application needs a database backup, follow its database procedure too.
Restore the recorded writer and controller states after the coordinated capture finishes.
The [maintenance procedure](./maintenance.md) covers node reboot or shutdown, not application-specific writer controls.

Create one named backup:

```bash
BACKUP_RUN="${BACKUP_POLICY}-manual-$(date -u +%Y%m%d%H%M%S)"
kubectl kopiur -n "$BACKUP_NAMESPACE" snapshot now \
  --policy "$BACKUP_POLICY" \
  --name "$BACKUP_RUN" \
  --tag reason=manual-runbook \
  --wait --timeout 1h
```

Keep the generated name in the maintenance or incident record.
If the command times out, inspect the same operation before retrying.
The timeout ends the wait, not the backup.
The [CLI reference](https://kopiur.home-operations.com/cli/backup-restore/#snapshot-now) documents these flags and exit states.

Read its result:

```bash
kubectl -n "$BACKUP_NAMESPACE" \
  get snapshot.kopiur.home-operations.com "$BACKUP_RUN" -o yaml
```

Make sure that `status.phase` is `Succeeded` or `Unchanged`.
Read `status.conditions`, `status.failure`, and `status.stats.filesFailed` for incomplete data or errors.
If `filesFailed` is greater than zero, stop the maintenance that depends on this backup.

For `Succeeded`, record `status.snapshot.kopiaSnapshotID` and the backup time.
For `Unchanged`, identify the previous successful snapshot with a real snapshot ID.
An `Unchanged` operation creates no new restore point.
The [Snapshot reference](https://kopiur.home-operations.com/reference/crds/snapshot/) defines these result fields.

A successful upload does not prove that the application can recover.
Complete a [practice application restore](./restore-application.md) before relying on a new backup policy.
Record the recovered files and the application-level results.

## Investigate a failure

Keep the failed Snapshot object while you investigate.
Deleting a manual Snapshot can delete its stored backup, depending on its deletion policy.
Start with these read-only commands:

```bash
kubectl -n "$BACKUP_NAMESPACE" \
  describe snapshot.kopiur.home-operations.com "$BACKUP_RUN"
kubectl kopiur -n "$BACKUP_NAMESPACE" \
  logs snapshot "$BACKUP_RUN"
kubectl -n "$BACKUP_NAMESPACE" \
  get volumesnapshots.snapshot.storage.k8s.io,pvc,jobs,pods
kubectl -n "$BACKUP_NAMESPACE" \
  get events --sort-by=.metadata.creationTimestamp
kubectl -n kopiur-system get externalsecrets
```

Use the failed condition to choose the next action:

- If repository access fails, inspect the repository conditions and ExternalSecret status.
- If snapshot staging fails, inspect the named Miroir volume snapshot and temporary PVC.
- If file access fails, compare the mover user and group with the application data ownership.
- If a schedule stops firing, inspect its suspension state, policy reference, and previous operation.

Fix the specific cause before creating another Snapshot.
Keep the source data and existing restore points intact during diagnosis.
Use the [Kopiur troubleshooting guide](https://kopiur.home-operations.com/troubleshooting/) for the reported condition.

After the operation reports `Failed`, repeat the backup step with a new name.
Make sure that the replacement operation meets the success criteria above.
If the backup still fails, keep maintenance paused and record the unresolved condition.
