# Restore PostgreSQL

Use this runbook to practice recovery or prepare a replacement for `database/postgres`.
A restore drill is a recovery test on a separate cluster.
The drill creates resources but leaves production databases and services unchanged.

CloudNativePG restores a physical backup into a new cluster.
WAL means the transaction log used during recovery.
Use [application restoration](./restore-application.md) for files outside PostgreSQL.
Read [Backups](./backups.md) for backup coverage and status.

## Choose the source

Read the [PostgreSQL manifest](https://github.com/hbjydev/phoebe/blob/main/kubernetes/apps/database/postgres/cluster/cluster.yaml) before each recovery.
Its bootstrap source names the `postgres` archive and backup `20261019T153149`.
Current backups and WAL use the `postgres-miroir` archive.

Select the archive and backup for the intended recovery point before creating the replacement cluster.
A backup ID identifies a base backup, not the latest recoverable state.
Do not reuse the bootstrap backup ID without inspecting its contents and recovery time.

This drill reads `postgres-miroir` through `database/barman-hetzner`.
The [ObjectStore](https://github.com/hbjydev/phoebe/blob/main/kubernetes/apps/database/postgres/cluster/objectstore.yaml) points to `s3://phoebe-postgres` on Hetzner.
If the live archive differs, stop and revise the source before creating resources.

## Prepare the drill

Run the commands from the repository root in one Bash session with its mise environment active.
Use `kubectl`, the `kubectl cnpg` plugin, and Mike Farah's `yq` from `mise.toml`.
Mise sets `KUBECONFIG` to `talos/kubeconfig` for this repository.

These commands read cluster state:

```bash
kubectl get nodes -o wide
kubectl -n cnpg-system get deployments,pods
kubectl -n database get cluster.postgresql.cnpg.io postgres -o yaml
kubectl -n database get objectstore.barmancloud.cnpg.io barman-hetzner -o yaml
kubectl -n database get externalsecret
kubectl -n database get backups.postgresql.cnpg.io \
  -o custom-columns=NAME:.metadata.name,CLUSTER:.spec.cluster.name,PHASE:.status.phase,BACKUP_ID:.status.backupId,START:.status.startedAt,STOP:.status.stoppedAt
```

Use only a completed backup from the intended archive.
Record its resource name, `.status.backupId`, start time, and completion time.
Inspect the selected Backup resource and its plugin metadata before accepting the archive association.
If that association is unclear, inspect the Barman catalog before continuing.

Make sure that the node has capacity for one additional PostgreSQL instance and its restored volume.
Inspect Miroir capacity through the [maintenance procedure](./maintenance.md).
Match the PostgreSQL major version, extensions, and parameters to the backup.
If production differs from Git, resolve that difference before generating the drill manifest.

The repository pins CloudNativePG chart `0.29.1` and Barman Cloud plugin `v0.9.0`.
The chart declares CloudNativePG `1.30.1`.
Make sure that the running operator and plugin support these recovery fields.
Read the [versioned recovery documentation](https://github.com/cloudnative-pg/cloudnative-pg/blob/v1.30.1/docs/src/recovery.md) if the versions differ.

## Generate local resources

Choose a new drill name for each attempt.
Keep the directory path until you record the outcome and remove the drill resources.
These commands write local files only:

```bash
umask 077
export PG_DRILL="postgres-restore-$(date -u +%Y%m%d%H%M%S)"
export PG_DRILL_DIR="$(mktemp -d /tmp/phoebe-postgres-restore.XXXXXX)"
export PG_BACKUP_ID='REPLACE_WITH_COMPLETED_BARMAN_BACKUP_ID'
printf '%s\n' "$PG_DRILL" "$PG_DRILL_DIR"
```

Replace the backup ID before generating the manifest.
The example stops at the earliest consistent state of that backup.
It does not replay all subsequent transactions.

```bash
case "$PG_BACKUP_ID" in
  ''|REPLACE_*) echo 'Set PG_BACKUP_ID before continuing.'; exit 1 ;;
esac

yq eval '
  .metadata = {"name": strenv(PG_DRILL), "namespace": "database"} |
  .spec.instances = 1 |
  del(.spec.certificates, .spec.plugins, .spec.managed,
      .spec.postgresql.pg_hba, .spec.postgresql.pg_ident) |
  .spec.inheritedMetadata.labels = {
    "egress.policy.home.arpa/block-all": "true",
    "egress.policy.home.arpa/kube-api": "true"
  } |
  .spec.bootstrap = {
    "recovery": {
      "source": "recovery-source",
      "recoveryTarget": {
        "backupID": strenv(PG_BACKUP_ID),
        "targetImmediate": true
      }
    }
  } |
  .spec.externalClusters = [{
    "name": "recovery-source",
    "plugin": {
      "name": "barman-cloud.cloudnative-pg.io",
      "parameters": {
        "barmanObjectName": "barman-hetzner",
        "serverName": "postgres-miroir"
      }
    }
  }]
' kubernetes/apps/database/postgres/cluster/cluster.yaml \
  > "$PG_DRILL_DIR/cluster.yaml"
```

The manifest preserves the image, extension images, PostgreSQL parameters, resources, and storage size from Git.
It removes production certificate references and managed roles.
CloudNativePG creates [separate certificates](https://cloudnative-pg.io/docs/1.30/certificates/) for the drill.

The drill defines no backup plugin or backup schedule.
The recovery source reads the production archive without configuring new archive writes.
Do not add a WAL archiver that writes to `postgres-miroir` or `postgres`.

For recovery to a specific time, replace `targetImmediate` with `targetTime` before creation.
Use a timestamp with an explicit timezone, such as a UTC timestamp ending in `Z`.
Select a base backup that completes before that time.
Make sure that archived WAL reaches beyond the selected time.

```yaml
recoveryTarget:
  backupID: REPLACE_WITH_COMPLETED_BARMAN_BACKUP_ID
  targetTime: REPLACE_WITH_TARGET_TIMESTAMP
```

Do not combine `targetImmediate` and `targetTime`.
Read [recovery targets](https://github.com/cloudnative-pg/cloudnative-pg/blob/v1.30.1/docs/src/recovery.md#recovery-targets) before choosing another stopping condition.
Use a new drill name if you change the target after creation.

## Restrict drill traffic

Production [network policies](https://github.com/hbjydev/phoebe/blob/main/kubernetes/apps/database/postgres/cluster/networkpolicy.yaml) select `cnpg.io/cluster: postgres`.
They do not select the drill cluster.
Create a separate policy before creating its pods.

This policy allows the operator, drill peers, and Hetzner recovery traffic.
The inherited labels exclude the drill from the repository's default broad egress allowance.
Existing cluster policies allow DNS and Kubernetes API traffic.

Make sure that live policies match those assumptions.
Cilium combines allowed traffic across matching policies.
If another policy permits application access to the drill, resolve that access before continuing.

Write the local policy file:

```bash
cat > "$PG_DRILL_DIR/network-policy.yaml" <<EOF_POLICY
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: ${PG_DRILL}
  namespace: database
spec:
  endpointSelector:
    matchLabels:
      cnpg.io/cluster: ${PG_DRILL}
  ingress:
    - fromEndpoints:
        - matchLabels:
            io.kubernetes.pod.namespace: cnpg-system
            app.kubernetes.io/name: cloudnative-pg
        - matchLabels:
            cnpg.io/cluster: ${PG_DRILL}
  egress:
    - toEndpoints:
        - matchLabels:
            io.kubernetes.pod.namespace: cnpg-system
            app.kubernetes.io/name: cloudnative-pg
        - matchLabels:
            cnpg.io/cluster: ${PG_DRILL}
    - toFQDNs:
        - matchPattern: '*.your-objectstorage.com'
      toPorts:
        - ports:
            - port: '443'
              protocol: TCP
EOF_POLICY
```

Keep the existing Pooler, application secrets, and Database resources pointed at production.
Use `kubectl cnpg psql` inside the drill pod for inspection.
Do not run application clients against the drill.

## Create and observe

Read both generated files before applying them.
Make sure that the source archive is correct and the cluster name is new.
Make sure that no production resource appears in either file.

Submit both files for server-side admission without saving resources:

```bash
kubectl create --dry-run=server -f "$PG_DRILL_DIR/network-policy.yaml"
kubectl create --dry-run=server -f "$PG_DRILL_DIR/cluster.yaml"
```

If admission rejects either resource, stop and resolve the reported cause.
Admission success does not prove that storage, image pulls, or archive access will work.
Creating the cluster allocates storage and starts a restore workload on the single node.

These commands change the cluster:

```bash
kubectl create -f "$PG_DRILL_DIR/network-policy.yaml"
kubectl create -f "$PG_DRILL_DIR/cluster.yaml"
```

Observe the drill with read-only commands:

```bash
kubectl -n database get cluster.postgresql.cnpg.io "$PG_DRILL"
kubectl -n database get pods,pvc -l "cnpg.io/cluster=$PG_DRILL"
kubectl -n database get events --sort-by=.lastTimestamp
kubectl cnpg status "$PG_DRILL" -n database
kubectl -n database wait cluster.postgresql.cnpg.io/"$PG_DRILL" \
  --for=condition=Ready --timeout=30m
```

Treat the timeout as an inspection point, not permission to delete resources.
Inspect the affected pod and its recovery container logs.
If the archive is missing, credentials fail, or storage cannot attach, stop before changing the recovery target.

## Prove the recovery

Make sure that the cluster reports one ready instance.
Make sure that its logs identify the selected backup and the intended recovery endpoint.
Inspect database names without printing application records:

```bash
kubectl cnpg psql "$PG_DRILL" -n database --tty=false -- \
  -X -v ON_ERROR_STOP=1 -d postgres \
  -c 'SELECT pg_is_in_recovery();' \
  -c 'SELECT datname FROM pg_database WHERE datallowconn AND NOT datistemplate ORDER BY datname;'
```

Expect `pg_is_in_recovery()` to return `f` after promotion.
Promotion means that PostgreSQL leaves recovery and becomes a primary.
A ready pod alone does not prove that the required application data exists.

Select one restored application database for a read-only inspection.
Replace the database name in this command:

```bash
kubectl cnpg psql "$PG_DRILL" -n database --tty=false -- \
  -X -v ON_ERROR_STOP=1 -d APPLICATION_DATABASE \
  -c 'BEGIN READ ONLY;' \
  -c 'SELECT extname, extversion FROM pg_extension ORDER BY extname;' \
  -c 'COMMIT;'
```

Add an application-specific query for an expected record or timestamp.
Use a read-only transaction for that query.
Compare its result with evidence from the selected recovery time.
Record the source archive, backup ID, target, elapsed time, query result, and any failures.

## Retire the drill

Retain the drill if recovery failed and its logs are still needed.
If the drill succeeded, record the result before cleanup.
Make sure that the cluster name, pods, and volumes belong only to this drill.

Deleting a drill cluster can delete its volumes through owner references and storage reclamation.
Never substitute `postgres` for the drill name.
These commands delete only the named drill resources:

```bash
case "$PG_DRILL" in
  postgres-restore-*) ;;
  *) echo 'Refusing to delete a cluster without the drill prefix.'; exit 1 ;;
esac
kubectl -n database delete cluster.postgresql.cnpg.io "$PG_DRILL" --wait=true
kubectl -n database get pods,pvc -l "cnpg.io/cluster=$PG_DRILL"
```

If pods or volumes remain, inspect their owners and retention rules before deleting them by exact name.
Keep the drill policy until its pods are gone.
Then delete the policy:

```bash
kubectl -n database delete ciliumnetworkpolicy "$PG_DRILL"
```

## Prepare a production replacement

Use the successful drill as evidence for a separate cutover plan.
Cutover means switching applications to the recovered database.
Do not point the production Pooler at the drill as an unplanned shortcut.

Prepare a PostgreSQL-specific writer plan using the controls in [application switching](./restore-application.md#switch-a-production-application).
Include every database client, scheduled job, and controller that can restart writers.

Define these items before changing production:

1. Record the accepted recovery time and expected data loss.
2. Stop every database writer with the reviewed PostgreSQL-specific plan.
3. Record the Flux controllers and database operators that manage the affected resources.
4. Preserve the original cluster and volumes until the recovery outcome is accepted.
5. Prepare certificates for the new service names and trusted application connections.
6. Update Pooler references, network policies, Database resources, DatabaseRole resources, and any direct application connections together.
7. Configure a new, unused archive name for replacement backups and WAL.
8. Establish new backups before resuming normal operation.
9. Resume applications in dependency order and make sure that their data is usable.

Do not disable the empty-archive protection to reuse a production archive.
Keep the recovery source and the replacement archive destination separate.
The [Barman plugin documentation](https://cloudnative-pg.io/plugin-barman-cloud/docs/concepts/) describes their separate roles.

Before new writes reach the replacement, rollback can return clients to the untouched original cluster.
After new writes begin, the two databases diverge.
Stop writers and plan data reconciliation before returning to the original.

If recovery needs the original cluster name, prepare a separate replacement procedure with explicit volume retention.
This drill does not authorize deleting `database/postgres` or its volumes.
