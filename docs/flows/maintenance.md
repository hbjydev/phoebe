# Miroir maintenance

Use this runbook for a planned node reboot or shutdown with the existing storage disk intact.
Phoebe has one node and one copy of each `miroir-local` volume.
All cluster services stop during the outage.

This procedure does not cover disk replacement, pool repair, or a Miroir upgrade.
For lost data, use [application recovery](./restore-application.md) or [PostgreSQL recovery](./restore-postgres.md).
A pool is the disk space that Miroir uses for volumes.

## 1. Establish the maintenance scope

Run these commands in Bash from the repository root on your administration machine.
Use the tools and credentials selected by `mise.toml`.
Mise sets `KUBECONFIG` and `TALOSCONFIG` for this repository.
Keep this shell open until recovery finishes.

1. Record the maintenance purpose and the authorized outage window.
2. Arrange a pause in deployments and automated upgrades during that window.
3. Make sure that you can reach the physical machine if remote access fails.

Select the target from `talos/topf.yaml`:

```bash
MAINT_NODE='phoebe-k-ctrl-01'
MAINT_IP="$(yq -er '.nodes[] | select(.host == "phoebe-k-ctrl-01") | .ip' talos/topf.yaml)"

kubectl get node "$MAINT_NODE" -o wide
talosctl --nodes "$MAINT_IP" --endpoints "$MAINT_IP" version
```

These commands read cluster state.
Make sure that the node address matches `talos/topf.yaml`.
If the live topology differs from `talos/topf.yaml`, stop and revise the plan.

## 2. Inspect storage and workloads

Read the current storage state:

```bash
kubectl get storageclass miroir-local -o yaml
kubectl get miroirnodes.miroir.home-operations.com "$MAINT_NODE" -o yaml
kubectl get miroirvolumes.miroir.home-operations.com -o wide
kubectl get pods -n miroir-system -o wide
kubectl get pvc -A
kubectl get pods -A --field-selector "spec.nodeName=$MAINT_NODE"
kubectl get poddisruptionbudgets -A
kubectl get talosupgrades,kubernetesupgrades -o yaml
```

Make sure that the node is Ready and the Miroir Pods are healthy.
Make sure that existing Miroir volumes report `Ready`.
Inspect the MiroirNode pool statistics for capacity warnings, stale samples, or errors.
If storage is unhealthy or an upgrade is active, stop before scheduling downtime.

The [Miroir configuration](https://github.com/hbjydev/phoebe/tree/main/kubernetes/apps/miroir-system/miroir/config)
selects `/dev/disk/by-partlabel/r-miroir` and one replica.
The [Talos storage configuration](https://github.com/hbjydev/phoebe/blob/main/talos/node/phoebe-k-ctrl-01/04-miroir.yaml)
selects the disk by serial number.
Keep both selections unchanged during this procedure.

Inspect the effective kubelet shutdown periods:

```bash
kubectl get --raw "/api/v1/nodes/$MAINT_NODE/proxy/configz" \
  | python3 -c 'import json, sys; c=json.load(sys.stdin)["kubeletconfig"]; print({k:c.get(k) for k in ("shutdownGracePeriod", "shutdownGracePeriodCriticalPods")})'
kubectl get daemonsets -n miroir-system \
  -o custom-columns='NAME:.metadata.name,GRACE:.spec.template.spec.terminationGracePeriodSeconds'
```

The kubelet is the node service that stops workload containers.
Make sure that its shutdown periods allow workloads to stop before the Miroir agent.
Make sure that the critical-Pod period covers the agent termination period.
[Miroir documents this shutdown ordering](https://github.com/home-operations/miroir/blob/main/docs/requirements.md).
If the values are unavailable or insufficient, resolve that before rebooting.

## 3. Record recovery evidence

Use the [backup guide](./backups.md) to inspect Kopiur and PostgreSQL backups.
Record the selected backup identifiers and their ages.
If the recovery points do not meet the outage plan, create fresh backups before continuing.

A local snapshot shares the storage disk with its source volume.
It cannot recover data after that disk fails.
Use the restore runbooks to establish that the required external backups are readable.

Save local evidence outside the repository:

```bash
umask 077
MAINT_DIR="$(mktemp -d /tmp/phoebe-maintenance.XXXXXX)"
printf '%s\n' "$MAINT_NODE" "$MAINT_IP" > "$MAINT_DIR/target.txt"
kubectl get node "$MAINT_NODE" -o json > "$MAINT_DIR/node-before.json"
kubectl get miroirvolumes.miroir.home-operations.com -o json > "$MAINT_DIR/volumes-before.json"
kubectl get pvc -A -o json > "$MAINT_DIR/claims-before.json"
```

These commands write local files without changing the cluster.
Record the directory path in your maintenance notes.
Keep the original node scheduling state for recovery.

If you need a fresh Kubernetes state backup, save an etcd snapshot:

```bash
talosctl --nodes "$MAINT_IP" --endpoints "$MAINT_IP" etcd snapshot "$MAINT_DIR/etcd.snapshot"
```

Etcd stores Kubernetes objects, including Secrets.
Keep this file private and copy it to your protected backup location before the outage.
It does not contain application volume data.

## 4. Cordon the node

The next command changes cluster scheduling.
Cordoning prevents ordinary replacement Pods from starting on the node.
Existing Pods continue to run until Talos stops them.

```bash
kubectl cordon "$MAINT_NODE"
kubectl get node "$MAINT_NODE"
```

Make sure that the node reports `SchedulingDisabled`.
[Miroir requires cordoning before reboot](https://github.com/home-operations/miroir/blob/main/docs/maintenance.md).
Leave the Miroir agent running so that it can release storage during shutdown.

Read backup and restore activity again:

```bash
kubectl get snapshots.kopiur.home-operations.com,restores.kopiur.home-operations.com -A
kubectl get backups.postgresql.cnpg.io -n database
kubectl get jobs,pods -A
```

Wait for active backup and restore work to finish.
If an operation cannot finish while cordoned, cancel this maintenance attempt and restore the original scheduling state.
Investigate the operation before starting a new attempt.

## 5. Reboot or shut down

Choose one operation below.
Both operations stop services across the cluster.
Phoebe has no second node for moving workloads during a drain.
This reboot path uses Talos graceful shutdown after cordoning.

For a reboot, run:

```bash
talosctl --nodes "$MAINT_IP" --endpoints "$MAINT_IP" reboot --wait --timeout=30m
```

Shutdown attempts a drain, which requests Pod eviction before stopping the node.
A disruption budget limits how many application Pods can stop together.
On one node, that budget can prevent eviction because replacement Pods cannot start elsewhere.
Review the recorded budgets before choosing shutdown.

For a powered-off maintenance window, run:

```bash
talosctl --nodes "$MAINT_IP" --endpoints "$MAINT_IP" shutdown --wait --timeout=30m
```

Wait for physical shutdown before touching hardware.
Keep the original storage disk and its contents intact.
Power the machine on when the hardware work finishes.

If shutdown reports an eviction or disruption-budget failure, stop and inspect the named workload.
Prepare its application-specific shutdown plan before retrying.
If either command times out, inspect the node state before sending another command.
Do not use forced reboot, forced shutdown, or a power cut to bypass a failed shutdown.
Those actions can interrupt storage writes.
The local `talosctl reboot --help` and `talosctl shutdown --help` describe the installed command behavior.

## 6. Restore scheduling and inspect recovery

Wait for the Talos API and Kubernetes API to return:

```bash
talosctl --nodes "$MAINT_IP" --endpoints "$MAINT_IP" version
kubectl wait node/"$MAINT_NODE" --for=condition=Ready --timeout=10m
kubectl get pods -n miroir-system -o wide
```

If an API remains unavailable, inspect the physical console and Talos logs before changing storage.
If the node was schedulable before this procedure, restore scheduling:

```bash
kubectl uncordon "$MAINT_NODE"
```

On this single-node cluster, replacement controller Pods need scheduling before full storage recovery can finish.
If the node was already cordoned, resolve the original maintenance reason before enabling scheduling.
Wait for Miroir recovery after controllers restart:

```bash
kubectl get pods -n miroir-system -o wide
kubectl wait miroirvolumes.miroir.home-operations.com --all \
  --for=jsonpath='{.status.phase}'=Ready --timeout=10m
kubectl get miroirnodes.miroir.home-operations.com "$MAINT_NODE" -o yaml
kubectl get pvc -A
kubectl get clusters.postgresql.cnpg.io -n database
kubectl get pods -A
kubectl get kustomizations.kustomize.toolkit.fluxcd.io,helmreleases.helm.toolkit.fluxcd.io -A
```

Make sure that the original claims still bind to the recorded volumes.
Make sure that Miroir volumes are Ready and the pool reports fresh statistics without new errors.
Make sure that PostgreSQL, application Pods, and Flux resources recover.
Open the affected applications and test their normal read and write operations.
Use a fresh backup from the [backup guide](./backups.md) to establish that backups work after the outage.

## If recovery stops

Keep the local evidence and the failed objects for diagnosis.
Inspect events and Miroir Pods before attempting repairs:

```bash
kubectl get events -n miroir-system --sort-by=.lastTimestamp
kubectl get pods -n miroir-system -o wide
kubectl get miroirvolumes.miroir.home-operations.com -o yaml
talosctl --nodes "$MAINT_IP" --endpoints "$MAINT_IP" dmesg
```

Do not delete claims or remove storage finalizers to clear a stalled operation.
The `miroir-local` class deletes backing storage when Kubernetes releases the volume.
A finalizer is a deletion guard that waits for cleanup.

If a new shell is required, restore the target variables from `target.txt` and repeat the read-only identity steps.
Keep existing suspension and scheduling states until their purpose is understood.
Finish maintenance only after storage, applications, and backups meet the recovery criteria above.
