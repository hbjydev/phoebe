#!/usr/bin/env python3
"""Read the quiesced cluster and generate a local, reviewable migration bundle."""
import argparse
import copy
import difflib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUNDLE = ROOT / 'kubernetes/.miroir-migration'
NODE = 'phoebe-k-ctrl-01'
SERIAL = '25044DD0CC34'
PG_BACKUP = 'postgres-pre-miroir-20261019153144'
PG_BACKUP_ID = '20261019T153149'
CACHES = set('''ai/llmkube-model-cache default/home-assistant-cache default/jellyseerr-cache
 default/radarr-cache default/sonarr-cache media/jellyfin-cache selfhosted/immich-machine-learning'''.split())
DISCARD = set('''ai/openclaw-misc observability/gatus
 observability/prometheus-kube-prometheus-stack-db-prometheus-kube-prometheus-stack-0
 observability/alertmanager-kube-prometheus-stack-db-alertmanager-kube-prometheus-stack-0
 selfhosted/redis-data-nextcloud-redis-master-0'''.split())
DATABASE = {'database/postgres-2', 'database/postgres-3'}

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def command(*args, data=None):
    return subprocess.check_output(args, input=data, text=True).strip()

def kubectl(*args, data=None):
    timeout = '0' if args[0] in ('wait', 'rollout') else '30s'
    return command('kubectl', '--context=admin@phoebe', '--request-timeout='+timeout, *args, data=data)

def get(kind, namespace=None):
    return json.loads(kubectl('get', kind, *(['-n', namespace] if namespace else ['-A']), '-o', 'json'))['items']

def key(obj):
    return obj['metadata'].get('namespace', '') + '/' + obj['metadata']['name']

def clean(obj):
    return {'apiVersion': obj['apiVersion'], 'kind': obj['kind'],
            'metadata': {k: obj['metadata'][k] for k in ('name', 'namespace') if k in obj['metadata']},
            'spec': copy.deepcopy(obj['spec'])}

def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')
    path.chmod(0o600)

def pod_for(claim, name):
    return {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {
        'name': name, 'namespace': claim['metadata']['namespace'],
        'labels': {'migration.home.arpa/purpose': 'miroir-binding'}}, 'spec': {
        'automountServiceAccountToken': False, 'restartPolicy': 'Never',
        'nodeSelector': {'kubernetes.io/hostname': NODE},
        'securityContext': {'runAsUser': 65532, 'runAsGroup': 65532, 'runAsNonRoot': True,
                            'seccompProfile': {'type': 'RuntimeDefault'}},
        'containers': [{'name': 'hold', 'image': 'registry.k8s.io/pause:3.10',
            'securityContext': {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True,
                                'capabilities': {'drop': ['ALL']}},
            'resources': {'requests': {'cpu': '1m', 'memory': '8Mi'}, 'limits': {'memory': '32Mi'}},
            'volumeMounts': [{'name': 'data', 'mountPath': '/restore-data', 'readOnly': True}]}],
        'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': claim['metadata']['name'], 'readOnly': True}}]}}

def build(claims, snapshots, state):
    """Fail unless every original claim has exactly one approved disposition."""
    require(state.get('snapshots', {}).get('complete'), 'Maintenance backups are not complete')
    rows = {key(c): c for c in claims}
    require(len(rows) == len(claims), 'Duplicate PVC identities')
    wanted = {(r['metadata']['namespace'], r['metadata']['name']) for r in state['snapshots']['requests'] if r['kind'] == 'Snapshot'}
    backups = [s for s in snapshots if (s['metadata']['namespace'], s['metadata']['name']) in wanted]
    require(len(backups) == len(wanted) == 34, 'Expected all 34 final backup requests')
    restored = {}
    objects = {}
    for backup in backups:
        status = backup.get('status', {})
        require(status.get('phase') in ('Succeeded', 'Unchanged') and not status.get('stats', {}).get('filesFailed', 0), f'Incomplete backup: {key(backup)}')
        sources = status['resolved']['sources']
        require(len(sources) == 1, f'Multiple source backup requires manual mapping: {key(backup)}')
        source = sources[0]['pvc']
        require(source in rows and source not in restored, f'Unknown or duplicate backup source: {source}')
        point = status['snapshot']; require(point.get('kopiaSnapshotID'), f'Missing backup ID: {source}')
        repository = status['resolved']['repository']
        require(repository == {'kind': 'ClusterRepository', 'name': 'hetzner'}, f'Unexpected repository: {source}')
        old = rows[source]; require(old['spec'].get('volumeMode', 'Filesystem') == 'Filesystem', f'Block PVC: {source}')
        ns, name = source.split('/')
        restore_name = 'miroir-' + backup['spec']['policyRef']['name'] + '-20261019'
        restore = {'apiVersion': 'kopiur.home-operations.com/v1alpha1', 'kind': 'Restore',
            'metadata': {'name': restore_name, 'namespace': ns}, 'spec': {
            'source': {'identity': {**point['identity'], 'snapshotID': point['kopiaSnapshotID']}},
            'repository': repository, 'target': {'populator': {}},
            'credentialProjection': {'enabled': True}, 'policy': {'onMissingSnapshot': 'Fail'},
            'options': {'ignoreErrors': False, 'ignorePermissionErrors': False,
                        'skipOwners': False, 'skipPermissions': False, 'parallel': 32},
            'failurePolicy': {'backoffLimit': 1, 'activeDeadlineSeconds': 14400},
            'mover': {'privilegedMode': True,
                'podSecurityContext': {'runAsUser': 0, 'runAsGroup': 0, 'runAsNonRoot': False,
                                      'fsGroup': 0, 'fsGroupChangePolicy': 'OnRootMismatch'},
                'securityContext': {'runAsUser': 0, 'runAsGroup': 0, 'runAsNonRoot': False,
                    'privileged': False, 'capabilities': {'drop': ['ALL'], 'add': ['CHOWN', 'DAC_OVERRIDE', 'FOWNER', 'FSETID']}}}}}
        pvc = new_claim(old)
        pvc['spec']['dataSourceRef'] = {'apiGroup': 'kopiur.home-operations.com', 'kind': 'Restore', 'name': restore_name}
        binder = pod_for(pvc, restore_name + '-bind')
        objects[source] = {'restore': restore, 'pvc': pvc, 'binder': binder}
        restored[source] = {'backupID': point['kopiaSnapshotID'], 'identity': point['identity'],
                            'backupRequest': key(backup), 'restore': restore_name}
    groups = [set(restored), CACHES, DISCARD, DATABASE]
    require(sum(map(len, groups)) == len(set.union(*groups)), 'Disposition groups overlap')
    require(set(rows) == set.union(*groups), f'PVC inventory changed: {sorted(set(rows) ^ set.union(*groups))}')
    inventory = []
    for name, old in sorted(rows.items()):
        disposition = ('restore' if name in restored else 'cache' if name in CACHES else
                       'discard' if name in DISCARD else 'postgres')
        inventory.append({'claim': name, 'uid': old['metadata']['uid'], 'pv': old['spec']['volumeName'],
                          'capacity': old['spec']['resources']['requests']['storage'],
                          'disposition': disposition, **restored.get(name, {})})
        if disposition == 'cache': objects[name] = {'pvc': new_claim(old)}
    return inventory, objects

def new_claim(old):
    metadata = {'name': old['metadata']['name'], 'namespace': old['metadata']['namespace']}
    # Preserve declarative ownership, but never binding/provisioner annotations
    # or ownerReferences pointing to controllers that may be replaced.
    if old['metadata'].get('labels'):
        metadata['labels'] = copy.deepcopy(old['metadata']['labels'])
    annotations = {k: v for k, v in old['metadata'].get('annotations', {}).items()
                   if k.startswith('meta.helm.sh/')}
    if annotations: metadata['annotations'] = annotations
    return {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
        'metadata': metadata,
        'spec': {'accessModes': old['spec']['accessModes'], 'volumeMode': 'Filesystem',
                 'resources': {'requests': {'storage': old['spec']['resources']['requests']['storage']}},
                 'storageClassName': 'miroir-local'}}

def git_patch():
    changes = []
    for directory in ('kubernetes/apps', 'kubernetes/components'):
        for path in sorted((ROOT / directory).rglob('*.yaml')):
            if '/apps/rook-ceph/' in str(path): continue
            old = path.read_text(); new = old.replace('csi-ceph-blockpool', 'miroir-snap').replace('ceph-block', 'miroir-local')
            if path.as_posix().endswith('/miroir/config/kustomization.yaml'):
                new = new.replace('resources: []', 'resources:\n  - ./storageclass.yaml\n  - ./volumesnapshotclass.yaml\n  - ./miroirnode.yaml')
            if path.as_posix().endswith('/miroir/config/storageclass.yaml'):
                new = new.replace('  name: miroir-local\n', '  name: miroir-local\n  annotations:\n    storageclass.kubernetes.io/is-default-class: "true"\n')
            if path.as_posix().endswith('/database/postgres/cluster/cluster.yaml'):
                new = new.replace('  annotations:\n    cnpg.io/skipEmptyWalArchiveCheck: enabled\n', '')
                old_bootstrap = f'      backup:\n        name: {PG_BACKUP}'
                require(old_bootstrap in new, 'PostgreSQL bootstrap changed; review patch generation')
                new = new.replace(old_bootstrap, f'      source: backup\n      recoveryTarget:\n        backupID: {PG_BACKUP_ID}')
                new = new.replace('        barmanObjectName: &store barman-hetzner\n',
                                  '        barmanObjectName: &store barman-hetzner\n        serverName: postgres-miroir\n')
            if new != old:
                rel = path.relative_to(ROOT).as_posix()
                changes.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile='a/'+rel, tofile='b/'+rel))
    # Keep Ceph reconciliation disabled when Flux is eventually resumed.
    path = ROOT / 'kubernetes/apps/rook-ceph/rook-ceph/ks.yaml'
    old = path.read_text(); new = old.replace('\nspec:\n', '\nspec:\n  suspend: true\n')
    rel = path.relative_to(ROOT).as_posix()
    changes.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile='a/'+rel, tofile='b/'+rel))
    return ''.join(changes)

def prepare(out):
    require(not out.exists(), f'{out} already exists; retain it and choose a new --bundle directory')
    state = json.loads((ROOT / 'kubernetes/.maintenance-state.json').read_text())
    require(state['context'] == 'admin@phoebe' and 'ceph' in state['stages'], 'Wrong maintenance state')
    require(kubectl('config', 'view', '--minify', '-o', 'jsonpath={.clusters[0].cluster.server}') == state['server'], 'Kubernetes server differs from maintenance state')
    flux = {obj['metadata']['name']: obj for obj in get('deployment', 'flux-system')}
    for name in ('flux-operator', 'kustomize-controller', 'helm-controller'):
        require(name in flux and flux[name]['spec'].get('replicas') == 0, 'Flux must remain frozen')
    sys.path.insert(0, str(ROOT / 'kubernetes')); import maintenance
    # The maintenance module normally uses the current context. Pin it here too.
    maintenance.kubectl = lambda *args, **kwargs: kubectl(*args)
    maintenance.verify_stopped('ceph')
    all_claims = get('pvc'); claims = [x for x in all_claims if x['spec'].get('storageClassName') == 'ceph-block']
    snapshots = get('snapshots.kopiur.home-operations.com')
    inventory, objects = build(claims, snapshots, state)
    cluster = get('clusters.postgresql.cnpg.io', 'database')
    require(len(cluster) == 1 and cluster[0]['metadata']['name'] == 'postgres', 'Unexpected PostgreSQL clusters')
    require(cluster[0]['metadata'].get('annotations', {}).get('cnpg.io/hibernation') == 'on', 'PostgreSQL must be hibernated')
    backup_name = PG_BACKUP
    backup = next((x for x in get('backups.postgresql.cnpg.io', 'database') if x['metadata']['name'] == backup_name), None)
    require(backup is not None, f'Missing final PostgreSQL Backup database/{backup_name}; verify it exists before preparing')
    require(backup['status'].get('phase') == 'completed' and backup['status'].get('backupId') == PG_BACKUP_ID, 'Final PostgreSQL backup incomplete/changed')
    ceph = get('cephcluster', 'rook-ceph')
    require(len(ceph) == 1 and ceph[0]['metadata']['name'] == 'rook-ceph', 'Unexpected Ceph clusters')
    require({n['metadata']['name'] for n in get('node')} == {NODE}, 'Node inventory changed; review disk cleanup scope')
    require(not any(j['metadata']['name'].startswith('rook-ceph-cleanup') for j in get('job', 'rook-ceph')), 'Old Rook cleanup jobs exist; inspect before preparing')
    require(not get('cephfilesystem', 'rook-ceph') and not get('cephobjectstore', 'rook-ceph'), 'Unexpected Ceph filesystems/object stores')
    pools = get('cephblockpool', 'rook-ceph')
    namespaces = {x['metadata']['name']: x for x in get('namespace')}
    for name in objects:
        require(namespaces[name.split('/')[0]]['metadata'].get('annotations', {}).get('kopiur.home-operations.com/privileged-movers') == 'true', f'Root mover not permitted: {name}')
    plan = {'context': 'admin@phoebe', 'server': state['server'], 'run': state['snapshots']['run'],
            'node': NODE, 'serial': SERIAL, 'claims': inventory, 'postgresUID': cluster[0]['metadata']['uid'],
            'postgresBackup': backup_name, 'postgresBackupID': backup['status']['backupId'],
            'cephUID': ceph[0]['metadata']['uid'], 'cephStorage': ceph[0]['spec']['storage'],
            'cephPools': {p['metadata']['name']: p['metadata']['uid'] for p in pools}}
    # Capture all managed roles/cert references from the live, fully rendered cluster.
    pg = clean(cluster[0]); pg['spec']['storage']['storageClass'] = 'miroir-local'
    pg['spec']['bootstrap'] = {'recovery': {'source': 'backup', 'recoveryTarget': {'backupID': PG_BACKUP_ID}}}
    sources = pg['spec'].get('externalClusters', [])
    matches = [x for x in sources
               if x.get('plugin', {}).get('name') == 'barman-cloud.cloudnative-pg.io'
               and x['plugin'].get('parameters', {}).get('barmanObjectName') == 'barman-hetzner'
               and x['plugin'].get('parameters', {}).get('serverName') == 'postgres']
    require(len(matches) == 1,
            'Expected exactly one PostgreSQL recovery source using barman-hetzner/serverName=postgres; '
            f'found {len(matches)} (externalClusters aliases: {[x.get("name") for x in sources]})')
    source = matches[0]
    require(not any(x is not source and x.get('name') == 'backup' for x in sources),
            'PostgreSQL recovery alias backup is already used by a different source')
    # Flux is frozen, so the live alias may differ from the edited Git manifest.
    # Normalize just this alias to match the generated Git patch.
    source['name'] = 'backup'
    # Recovery reads the old backup; new WALs use a fresh archive prefix.
    for plugin in pg['spec'].get('plugins', []):
        if plugin['name'] == 'barman-cloud.cloudnative-pg.io':
            plugin.setdefault('parameters', {})['serverName'] = 'postgres-miroir'
    proposed_patch = git_patch()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f'.{out.name}-preparing-', dir=out.parent) as temp:
        staging = Path(temp)
        dump(staging/'plan.json', plan); dump(staging/'maintenance-state.json', state)
        dump(staging/'postgres-backup-evidence.json', backup)
        dump(staging/'postgres.json', pg)
        dump(staging/'backup-evidence.json', [s for s in snapshots if any(r.get('backupRequest') == key(s) for r in inventory)])
        for name, parts in objects.items():
            for part, obj in parts.items(): dump(staging/'claims'/name/(part+'.json'), obj)
        (staging/'git-changes.patch').write_text(proposed_patch)
        # Publish only a complete bundle, on the same filesystem.
        require(not out.exists(), f'{out} appeared during preparation; refusing to replace it')
        staging.rename(out)
    # These objects stay evidence, not an apply-able List (status is essential).
    print(f'Prepared {out}: 34 restores, 7 empty caches, 5 discarded claims, CNPG recovery.')
    print('Review plan.json, claims/, postgres.json and git-changes.patch. No cluster objects were changed.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=DEFAULT_BUNDLE)
    args = parser.parse_args()
    try: prepare(args.bundle.resolve())
    except (RuntimeError, subprocess.CalledProcessError, KeyError, StopIteration) as error:
        sys.exit(f'STOP: {str(error) or type(error).__name__}')
