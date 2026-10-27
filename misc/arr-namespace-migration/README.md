# Move Radarr, Sonarr, Lidarr and Prowlarr to downloads

Prepared from the live cluster on 2026-10-26; Prowlarr added on 2026-10-27. This is a staged cutover, not a
script to run unattended. Nothing below has been applied to the cluster.
Run commands from the repository root, in one Bash session. Stop at any error.
Do not merge the manifest move before freezing reconciliation in step 2.

The live apps use miroir-local config volumes and PostgreSQL in `database`.
Radarr and Sonarr also have disposable cover-cache claims. Media stays on NFS.
The staged images match the running versions: Radarr 7.0.0.10815, Sonarr
5.0.0.2800, Lidarr 3.2.0.5144 and Prowlarr 2.6.5.5623. Upgrade separately after the migration.
If these versions change before execution, re-check the pins; never downgrade
an application against a database a newer version has already migrated.

The cutover deliberately rotates the four database passwords. The old
ExternalSecrets are removed before their replacements are created, so there
is only one reflection source for each database Secret. No passwords are
printed or saved in the bundle. ExternalSecrets can generate new passwords
on their first reconciliation even when a Secret has been pre-created; see
[ESO lifecycle](https://external-secrets.io/v2.6.0/guides/ownership-deletion-policy/).

## 1. Capture and preflight

```bash
set -euo pipefail
k() { kubectl --context=admin@phoebe "$@"; }
f() { flux --context=admin@phoebe "$@"; }
kp() { kubectl kopiur --context=admin@phoebe "$@"; }
run="arr-move-$(date -u +%Y%m%d%H%M%S)"
bundle="$PWD/kubernetes/.arr-migration/$run"
python3 misc/arr-namespace-migration/prepare.py capture --bundle "$bundle"
printf '%s\n' "$run" > "$bundle/run"
k -n database get backups.postgresql.cnpg.io --sort-by=.metadata.creationTimestamp
k -n downloads get pvc
```

The helper refuses to overwrite an existing bundle or use different live
images. The ignored bundle contains old controller manifests, PVC identities
and later the exact backup evidence, but no Secret values. Keep it through
the rollback window. A read-only preflight capture from preparation is also
available in the parent `.arr-migration` directory, but covers only the original
three apps. It cannot be used for this four-app cutover. The refreshed four-app
capture is in `.arr-migration/preflight-20261027`; take a fresh capture at cutover.
To resume the session, re-run the function definitions
and set `run=$(cat "$bundle/run")`; do not repeat `capture`.

Before stopping services, inspect their connection settings:

* Record Prowlarr URLs in Radarr, Sonarr and Lidarr, including indexer URLs
  managed by Prowlarr sync. At cutover, replace `prowlarr.default.svc` (and its
  cluster-local form) with `prowlarr.downloads.svc`. A short `prowlarr` host
  still works after all four apps move together. External HTTPS URLs stay the same.
* In Prowlarr's application settings, update both its advertised Prowlarr URL
  and each target Arr URL before forcing a full sync after cutover. Check that
  the regenerated indexer URLs point to the new namespace.
* Check download-client hosts use `*.downloads.svc` or their existing external
  hostnames. Check remote path mappings still agree with `/media`.
* Record Jellyseerr, Silo and Prowlarr's current Arr URLs for rollback. They
  should ultimately use `radarr.downloads.svc`, `sonarr.downloads.svc` and
  `lidarr.downloads.svc`, port 80, or the unchanged HTTPS hostnames.
* Confirm the latest PostgreSQL backup completed and WAL archiving is healthy.
  Keep database recovery separate from a namespace rollback: the database
  objects and data are never deleted by this procedure.

## 2. Freeze reconciliation, stop apps, take final backups

Suspend the parent first so it cannot undo child suspension. Other apps keep
running; this pauses the parent manifest reconciliation during the cutover.

```bash
f suspend kustomization flux-system -n flux-system
f suspend kustomization cluster-apps -n flux-system
for app in radarr sonarr lidarr prowlarr; do
  f suspend kustomization "$app" -n default
  f suspend kustomization "$app-db" -n default
  f suspend helmrelease "$app" -n default
  kp -n default suspend schedule "$app"
  k -n default scale deployment "$app" --replicas=0
  k -n default wait pod -l "app.kubernetes.io/name=$app" --for=delete --timeout=5m
done
for app in radarr sonarr lidarr prowlarr; do
  kp -n default snapshot now --policy "$app" --name "$app-$run" \
    --pin --deletion-policy retain --wait --timeout 1h
done
for app in radarr sonarr lidarr prowlarr; do
  k -n default wait "snapshot.kopiur.home-operations.com/$app-$run" \
    --for=condition=Pinned --timeout=10m
done
python3 misc/arr-namespace-migration/prepare.py restores --bundle "$bundle" --run "$run"
```

Wait for any earlier scheduled backup movers to finish too. Do not suspend
the policies or Kopiur itself: the manual backups and restores need them.
The helper checks each final backup succeeded without failed files, has the
expected source and repository, and has an exact Kopia snapshot ID.
Wait for pinning as well as backup success: pinning can replace the snapshot ID.

## 3. Restore config into downloads

```bash
for app in radarr sonarr lidarr prowlarr; do
  k create -f "$bundle/restores/$app.json"
done
# Submit every restore before waiting, so the movers run concurrently.
for app in radarr sonarr lidarr prowlarr; do
  k -n downloads wait "pod/$app-$run-bind" --for=condition=Ready --timeout=60m
  k -n downloads get "restore/$app-$run" -o yaml
done
python3 misc/arr-namespace-migration/prepare.py restored --bundle "$bundle" --run "$run"
```

The binding pods use the pause image and have no shell. Inspect the Restore
status above: it must be completed successfully, without skipped permission
errors, before continuing. The binder forces WaitForFirstConsumer provisioning
without starting the application. Its Ready condition also confirms the
populated PVC can be mounted. Do not run the apps against an incomplete restore.
Restore movers run as root with limited ownership-related capabilities, as in
the earlier storage migration. UID 1000 cannot restore the timestamps on the
new filesystem's root directory. The applications still run as UID 1000.

```bash
for app in radarr sonarr lidarr prowlarr; do
  k -n downloads delete pod "$app-$run-bind" --wait=true
done
```

Keep the original config and cache PVCs in `default`. The new cover-cache PVCs
are created by Flux later; cover art will rebuild.

## 4. Orphan old Flux ownership and hand over credentials

Deletion must orphan the old inventories. In particular, the nested `*-db`
Kustomizations live in `default`, but own Database and DatabaseRole objects
in `database`. Do not delete those database objects.

```bash
for app in radarr sonarr lidarr prowlarr; do
  for name in "$app" "$app-db"; do
    k -n default patch kustomization "$name" --type=merge \
      -p '{"spec":{"prune":false,"deletionPolicy":"Orphan"}}'
    k -n default delete kustomization "$name" --wait=true
  done
  # The old deployment is still scaled to zero; uninstall its service/route.
  k -n default delete helmrelease "$app" --wait=true --timeout=10m
  k -n default wait deployment/"$app" --for=delete --timeout=10m
  k -n default wait service/"$app" --for=delete --timeout=5m
  # This removes the old generated Secret and its auto-reflected database copy.
  k -n default delete externalsecret "$app-postgres" --wait=true
  k -n default wait secret/"$app-postgres" --for=delete --timeout=5m
  k -n database wait secret/"$app-postgres" --for=delete --timeout=5m
  k create -f "$bundle/new/externalsecret-$app-postgres.json"
  k create -f "$bundle/new/externalsecret-$app.json"
  k -n downloads wait externalsecret/"$app-postgres" --for=condition=Ready --timeout=5m
  k -n downloads wait externalsecret/"$app" --for=condition=Ready --timeout=5m
done
python3 misc/arr-namespace-migration/prepare.py credentials
```

If a suspended HelmRelease does not finalize, inspect its events; resume that
release's reconciliation to finish the uninstall. If the reflected Secret is
not removed, stop and inspect Reflector rather than creating a competing source.
The credential check compares Secrets in memory, verifies the reflection
source, and requires CNPG's `secretResourceVersion` to match the current
database Secret. Retry the check after reconciliation if needed; do not start
the apps until all four pass.

## 5. Publish the move, then start the new releases

At this point the old apps and their Flux Kustomizations are gone, the old
volumes are retained, the new volumes are restored, and CNPG has the new
passwords. Commit and push the reviewed changes through the normal repository
workflow. Keep parent reconciliation suspended until the commit is on main.

```bash
f reconcile source git flux-system -n flux-system
k -n flux-system get gitrepository flux-system
# Verify the displayed revision is the migration commit before proceeding.
f resume kustomization cluster-apps -n flux-system
f reconcile kustomization cluster-apps -n flux-system
for app in radarr sonarr lidarr prowlarr; do
  f reconcile kustomization "$app" -n downloads
  k -n downloads wait helmrelease/"$app" --for=condition=Ready --timeout=15m
  k -n downloads rollout status deployment/"$app" --timeout=10m
done
python3 misc/arr-namespace-migration/prepare.py credentials
f resume kustomization flux-system -n flux-system
```

The staged Jellyseerr policy allows both namespaces during the rollback
window. The `apps-to-prowlarr` cluster-wide policy also allows both namespaces
and transfers to the new Prowlarr Kustomization. Silo, download-client and
PostgreSQL policies already allow the required traffic. HTTPS hostnames and NFS paths remain the same.

Update the recorded client URLs. If a client cannot be updated immediately,
temporary aliases preserve the old Service DNS names after the Helm uninstall:

```bash
for app in radarr sonarr lidarr prowlarr; do
  k -n default create service externalname "$app" \
    --external-name="$app.downloads.svc.cluster.local"
done
```

These optional aliases are temporary and not managed by Git. They preserve
DNS names, not old ClusterIPs. Remove them once every client uses the new URL.

## 6. Verify and retain rollback

Check all four UIs: expected libraries, root folders, queue and history in
the media managers; indexers, application connections and sync in Prowlarr.
Test indexers and download clients; verify Prowlarr sync, Jellyseerr requests
and Silo connections. Inspect logs for authentication and import errors.
Do a controlled download/import check and confirm file ownership and paths.

```bash
for app in radarr sonarr lidarr prowlarr; do
  k -n downloads logs deployment/"$app" --tail=100
  kp -n downloads snapshot now --policy "$app" --name "$app-$run-after" \
    --wait --timeout 1h
done
```

Check database ownership and UIDs against the capture:

```bash
python3 misc/arr-namespace-migration/prepare.py verify --bundle "$bundle"
```
Retain the old PVCs, suspended schedules, pinned final backups and local bundle
until these checks pass and a normal backup cycle has succeeded. Cleanup is
a separate action; do not bulk-delete everything labelled with an app name.
Later remove the old API ExternalSecrets, old restore/policy/schedule objects,
old PVCs and temporary aliases after inspecting their ownership and backup
deletion semantics. Remove `default` from Jellyseerr's two namespace selectors
and the `apps-to-prowlarr` selector. Do not delete `apps-to-prowlarr` during
old-resource cleanup: it is one shared cluster-wide object, now owned by
`downloads/prowlarr`. Verify its Flux ownership labels after cutover.

## Rollback

Before step 4, the old releases and credentials still exist. Delete the new
binding pods, resume the old HelmReleases, restore replicas to one, and resume
the old app/db Kustomizations and schedules. Resume the parents only if main
still contains the old layout. Leave the copied PVCs for investigation.

After step 4, roll back with both sets of apps stopped. First suspend
`flux-system` and `cluster-apps` as in step 2; keep parent Flux reconciliation
suspended throughout:

1. Suspend `downloads/{app}` and `{app}-db` Kustomizations and HelmReleases
   if they exist. Scale new deployments to zero and wait for their pods to
   disappear. Suspend new backup schedules. Take new config backups if the
   new instances have accepted changes that need retaining.
2. Set `prune:false` and `deletionPolicy:Orphan` on the new app/db
   Kustomizations and delete them. Delete the new HelmReleases and wait for
   their services/routes to disappear. Keep both sets of PVCs.
3. Delete the new `downloads/{app}-postgres` ExternalSecrets and wait for
   their Secrets and the `database` mirrors to disappear. Recreate the old
   credential ExternalSecrets from the bundle. This rotates passwords again:

   ```bash
   for app in radarr sonarr lidarr prowlarr; do
     k create -f "$bundle/old/externalsecret-$app-postgres.json"
     k -n default wait externalsecret/"$app-postgres" --for=condition=Ready --timeout=5m
   done
   python3 misc/arr-namespace-migration/prepare.py credentials --namespace default
   ```

4. Delete any optional ExternalName aliases in `default` before reinstalling
   the old releases. Apply the saved old HelmReleases (they were captured
   before suspension) to start against the retained old volumes:

   ```bash
   for app in radarr sonarr lidarr prowlarr; do
     k apply -f "$bundle/old/helmrelease-$app.json"
     k -n default wait helmrelease/"$app" --for=condition=Ready --timeout=15m
     k -n default rollout status deployment/"$app" --timeout=10m
   done
   ```

5. Restore client URLs, including Prowlarr's advertised URL and application
   targets; force a full sync and test the old apps. Move the manifests back to
   `default` in Git, preserving the captured image versions; do not restore yesterday's older
   Radarr/Sonarr pins against the upgraded databases. Publish
   that rollback, reconcile the source, then resume the parents and old
   schedules. Verify database resource UIDs and credentials again.

The PostgreSQL data stays current throughout rollback. Old config volumes
represent the cutover point, so post-cutover config changes may need copying
back. Do not restore the entire PostgreSQL cluster just to undo this move.
