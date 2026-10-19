# Ceph → Miroir: reviewed cutover steps

These scripts are specific to Phoebe's shutdown on **19 October 2026**. They
prepare and recover storage while application writers and Flux remain stopped.
They do **not** resume applications or Flux. Run them from the repository root
with Mise so the installed tools and kubeconfig are available.

The disk handover is deliberately ordered:

1. Delete the old PVCs while Ceph and its CSI controllers can still process deletion.
2. Let Rook clean up Ceph and its OSD disk; then stop the remaining Ceph controllers.
3. Apply the Talos `RawVolumeConfig` and wait for `r-miroir` to exist.
4. Enable Miroir's pool and classes, test provisioning, then restore data.

The approved disk is selected by serial **`25044DD0CC34`**, not a hardcoded
`nvme` number. The scripts also check its size and reject a Talos system disk.
The Miroir agent may already be deployed; the pool must wait for step 3.

## Prepare and review

The first command reads the cluster and creates local files only:

```sh
mise exec -- python3 misc/ceph-to-miroir/prepare.py
```

It requires the completed maintenance state, stopped writers, frozen Flux,
the final 34 Kopiur backups and PostgreSQL backup `20261019T153149`. It writes
`kubernetes/.miroir-migration/`, which is ignored by Git and private to your user.
It refuses to overwrite an existing bundle. Keep the bundle and the original
maintenance state until recovery is complete; do not regenerate midway through
the migration. `--bundle /absolute/path` selects another location (keep it private
and outside Git yourself).

Review these generated files:

| File | Review |
| --- | --- |
| `plan.json` | 48 original PVC names, UIDs and PVs; each disposition; exact backup IDs; original Ceph identity |
| `claims/` | 34 pinned Kopiur restores and replacement PVCs, temporary binding Pods, seven empty cache PVCs |
| `postgres.json` | Live rendered roles/extensions, Miroir storage, pinned Barman recovery, new WAL prefix |
| `git-changes.patch` | Miroir classes/pool enabled, storage references changed, Ceph Flux Kustomizations suspended |
| `backup-evidence.json`, `postgres-backup-evidence.json` | Successful final backup records, retained as evidence rather than manifests to apply |

The five unused claims are discarded: `ai/openclaw-misc`, `observability/gatus`,
the old Prometheus and Alertmanager claims, and
`selfhosted/redis-data-nextcloud-redis-master-0`. The active Gatus claim
`observability/config-gatus-0` **is restored**. Seven cache claims are recreated
empty. The two old PostgreSQL claims are replaced by CNPG recovery.

Have the external Kopia password/S3 credentials, Barman credentials, and SOPS/age
recovery material available independently of these volumes. The bundle does not
export Secrets or prove that every remote object is still readable. This plan
uses the already completed restore checks; it does not repeat the database drill.
Keep the migration within the external backup retention window.

## Run one phase at a time

Every `step.py` invocation **without `--execute` is a description only**, including
`verify`. It does not read the cluster or require a prepared bundle. For example:

```sh
mise exec -- python3 misc/ceph-to-miroir/step.py ceph-cleanup
mise exec -- python3 misc/ceph-to-miroir/step.py talos-volume
```

After reviewing a phase and its inputs, add `--execute`. Mutating phases also
require a typed confirmation. There is no command that performs the whole cutover.
The following is the execution order, **not a block to paste and run unattended**:

| Phase | Effect / completion condition |
| --- | --- |
| `git` | Apply `git-changes.patch` locally. Review the diff and commit/push it yourself before Flux is resumed. |
| `retire` | First irreversible step: orphan-delete the hibernated PostgreSQL Cluster, delete Ceph CSI snapshots and the 48 approved source PVCs, wait for their PVs to disappear. Ceph remains running for these deletions. |
| `ceph-cleanup` | Delete the reviewed pools, enable Rook's destructive cleanup policy, delete CephCluster and wait for successful cleanup Jobs. Suspend Rook Helm releases/Kustomizations and stop its remaining controllers and Pods. Remove `ceph-block`. |
| `talos-volume` | Only after cleanup: apply `talos/node/phoebe-k-ctrl-01/04-miroir.yaml` with `talosctl patch machineconfig --mode=no-reboot`; wait for a ready `r-miroir` partition on the approved disk. |
| `activate` | Apply MiroirNode, `miroir-local` (new default) and `miroir-snap`. |
| `smoke` | Write/read a marker, expand a PVC, snapshot and restore it, verify the marker, clean up the disposable namespace and PVs. |
| `restore --claim namespace/name` | Restore one application claim from its pinned backup, using a temporary read-only consumer to trigger WaitForFirstConsumer provisioning. Start Kopiur's webhook/controller only; keep schedules stopped. |
| `restore-all` | Alternative to individual restore commands: restore all 34 application claims sequentially, stopping on the first failure. |
| `caches` | Create the seven empty cache claims. They may remain Pending until application Pods are resumed. |
| `postgres` | Recover CNPG from the final base backup plus archived WAL. The CNPG operator must remain available. Application database clients remain stopped. |
| `policies` | Change the 34 live Kopiur SnapshotPolicies to `miroir-snap`, including policies marked `IfNotPresent`. Schedules stay suspended. |
| `verify` | Read-only check of restored claims, pinned restore IDs, PostgreSQL readiness and policy classes. |

For example, the first actual phase is:

```sh
mise exec -- python3 misc/ceph-to-miroir/step.py git --execute
```

Later, an individual restore can be selected explicitly:

```sh
mise exec -- python3 misc/ceph-to-miroir/step.py restore --claim garage-system/garage-meta --execute
```

If Plex has already been restored and you have started it for playback, use the
explicit exception to continue the remaining restores:

```sh
mise exec -- python3 misc/ceph-to-miroir/step.py restore-all --allow-plex --execute
```

`--allow-plex` permits only the original `Deployment/media/plex`. Its only PVC
must be `media/plex`, Bound on Miroir, with a completed restore from the pinned
backup whose populated claim UID matches the live PVC. The saved Plex restore
phase must also be complete. Plex is verified and skipped on reruns; the script
does not recreate its binding Pod or restore its live data again. Other writers,
operators, schedules and Flux must remain paused.

Use the same flag for subsequent `caches`, `postgres`, `policies` and `verify`
commands while Plex is running. The exception is not saved in the maintenance
state and is rejected for disk retirement, Ceph cleanup and the smoke test.

Deleting the source PVCs already destroys their Ceph volumes under the `Delete`
reclaim policy. **Rollback from `retire` onward requires external backups**, even
before the disk is wiped. Local Ceph snapshots are not a rollback path after that
step. Neither script strips finalizers or falls back to a forced disk wipe.

Do not apply the raw volume configuration before `ceph-cleanup`: Talos could
provision it while Rook is still cleaning the disk. Retirement and cleanup refuse a
pending `r-miroir` VolumeConfig. If you already applied it, stop and review removal
of that pending configuration before proceeding; the script does not remove it.

## Checkpoint before resuming applications

After `verify --execute`, stop for review. The recovery scripts intentionally leave
application operators, Flux and schedules frozen. PostgreSQL and Kopiur are running
for recovery. Before a separately reviewed resumption:

- Check the recovered data through the applications and PostgreSQL, including
  Garage metadata/data pairing and preserved ownership. A completed Kopiur restore
  and a Ready database do not validate every application's contents.
- Resolve old StatefulSets whose immutable `volumeClaimTemplates` still name
  `ceph-block`. Their controllers may need to be recreated with the existing
  restored PVCs retained. Do not delete those PVCs to fix a template mismatch.
- Reconcile the new PostgreSQL Cluster UID with the saved maintenance state.
  **Do not run `just kube restore-ceph` unchanged**: its old UID checks and saved
  controller state describe the pre-migration cluster.
- Confirm the generated Git changes are pushed and the revision Flux will consume
  contains them; keep all three Rook Kustomizations and its Helm releases suspended.
- Validate fresh Miroir/Kopiur and PostgreSQL backups before restoring schedules.
  PostgreSQL reads the original `postgres` archive for this recovery and writes
  new backups/WAL to `postgres-miroir`. Future disaster-recovery manifests must
  select that new archive and a new backup ID.

### Repair the three retained StatefulSets

`repair_controllers.py` handles `downloads/slskd`, `observability/gatus` and
`security/kanidm-default`. They can be Ready using the restored PVCs while their
immutable claim templates still say `ceph-block`. This helper replaces only those
controllers with `miroir-local` templates, using orphan deletion to retain their
Pods and PVCs. It verifies each PVC's UID and PV binding before and after repair.
The StatefulSet controller may roll a Pod during adoption; allow for a brief
application interruption.

First take a full PostgreSQL backup named `postgres-post-miroir` and wait for it
to complete. Preparation checks that it belongs to the recovered PostgreSQL
Cluster and that the cluster archives to `postgres-miroir`:

```sh
python3 misc/ceph-to-miroir/repair_controllers.py prepare
```

This reads the cluster and creates `kubernetes/.miroir-migration/controllers/`
with a plan, three replacement JSON manifests, their diffs, and a backup of the
maintenance state. It makes no cluster changes. If the bundle already exists,
review it rather than regenerating it midway through repair.

Review each `.diff` and replacement `.json`. The intended changes are the claim
template storage class and a controller annotation used to recognize retries.
Helm ownership, Kanidm ownership, Pod configuration and live replica counts are
preserved. Then run the phases individually, checking each result before moving
to the next:

```sh
python3 misc/ceph-to-miroir/repair_controllers.py slskd --execute
python3 misc/ceph-to-miroir/repair_controllers.py gatus --execute
python3 misc/ceph-to-miroir/repair_controllers.py kanidm --execute
python3 misc/ceph-to-miroir/repair_controllers.py adopt-postgres --execute
```

Without `--execute`, these four commands only describe the action. Execution
also requires typing the phase name. The Kanidm phase pauses Kaniop, updates the
parent Kanidm resource's storage class, replaces the StatefulSet, and restores
Kaniop's captured replica count after readiness succeeds. If it fails while
Kaniop is paused, inspect the error and retry the same phase; the operator stays
paused until a successful retry. No PVCs or Pods are explicitly deleted.

Each repair atomically updates only that StatefulSet's UID in the saved
maintenance state. `adopt-postgres` checks the pinned completed backup again and
updates only the saved PostgreSQL Cluster UID; it does not mutate the cluster.
Keep `maintenance-state.before.json` for reference, not as a file to restore
over the new UIDs. The shared maintenance lock prevents concurrent helper runs.
Retries recognize replacements through the captured token and configuration;
unknown replacement controllers or changed PVCs stop the operation.

These phases leave Flux and Rook suspended and do not resume other applications
or schedules. Before resuming, separately verify the Git revision Flux will
consume, fresh application backups and the remaining maintenance actions.
The scripts do not uninstall Rook's remaining Helm releases/CRDs or test Miroir
across a node reboot.

## Failures and retries

Stop at a failed check and inspect the named object and logs. Progress is recorded
in `progress.json`; the maintenance lock prevents concurrent helper invocations.
Completed source deletions can be retried while the original claim UIDs remain
the reviewed inventory. Replacement claims are never accepted as deletion targets.
Existing restore manifests must match the reviewed source before a retry proceeds.

`git` and a completed `ceph-cleanup` refuse repeat execution. A failed smoke test
leaves `miroir-smoke` for inspection; review and remove that disposable namespace
before retrying. Do not edit progress to skip a failed prerequisite, delete pinned
Restore objects while PVCs depend on them, or regenerate the plan after deletion.

## Offline validation and references

```sh
python3 -m unittest discover -s misc/ceph-to-miroir -p 'test_*.py' -v
```

Tests cover inventory changes, missing/failed backups, pinned sources, UID-protected
deletion, disk selection, phase ordering and previews without cluster access.
They do not execute the cutover. New live resources are still subject to the
installed webhooks and controller behavior when you run the phases.

The cleanup sequence follows [Rook's teardown documentation](https://rook.io/docs/rook/latest/Getting-Started/ceph-teardown/).
Restore manifests use [Kopiur's Restore API](https://kopiur.home-operations.com/reference/crds/restore/).
Database recovery follows the [Barman plugin recovery configuration](https://cloudnative-pg.io/plugin-barman-cloud/docs/usage/)
and [CNPG's pinned base-backup recovery](https://github.com/cloudnative-pg/cloudnative-pg/blob/main/docs/src/recovery.md).
