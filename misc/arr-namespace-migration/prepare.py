#!/usr/bin/env python3
"""Read-only cluster checks and local manifests for the Arr namespace cutover."""
import argparse
import copy
import json
from pathlib import Path
import subprocess

APPS = ('radarr', 'sonarr', 'lidarr', 'prowlarr')
ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / 'kubernetes/.arr-migration'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def get(kind, name, namespace):
    result = subprocess.run([
        'kubectl', '--context=admin@phoebe', '--request-timeout=30s',
        '-n', namespace, 'get', kind, name, '-o', 'json', '--ignore-not-found',
    ], check=True, capture_output=True, text=True)
    return json.loads(result.stdout) if result.stdout.strip() else None


def clean(obj, namespace=None):
    return {'apiVersion': obj['apiVersion'], 'kind': obj['kind'],
            'metadata': {'name': obj['metadata']['name'],
                         'namespace': namespace or obj['metadata']['namespace']},
            'spec': copy.deepcopy(obj['spec'])}


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + '\n')
    path.chmod(0o600)


def capture(bundle):
    require(not bundle.exists(), f'{bundle} already exists; keep the original evidence')
    inventory = {}
    files = {}
    for app in APPS:
        require(get('deploy', app, 'downloads') is None, f'downloads/{app} already deployed')
        require(get('pvc', app, 'downloads') is None, f'downloads/{app} PVC already exists')
        deploy = get('deploy', app, 'default')
        require(deploy and deploy['spec'].get('replicas') == 1 and
                deploy.get('status', {}).get('availableReplicas') == 1,
                f'default/{app} is not healthy with one replica')
        image = next(c['image'] for c in deploy['spec']['template']['spec']['containers']
                     if c['name'] == 'app')
        hr = get('helmrelease', app, 'default')
        desired = hr['spec']['values']['controllers'][app]['containers']['app']['image']
        require(image == desired['repository'] + ':' + desired['tag'],
                f'{app}: live HelmRelease and Deployment images differ')
        # No migration should introduce a database schema upgrade/downgrade.
        manifest = (ROOT / f'kubernetes/apps/downloads/{app}/app/helmrelease.yaml').read_text()
        require('tag: ' + desired['tag'] in manifest, f'{app}: staged image differs from live; review pins')
        inventory[app] = {'image': image, 'claims': {}}
        claims = [app] + ([app + '-cache'] if app in ('radarr', 'sonarr') else [])
        for claim in claims:
            pvc = get('pvc', claim, 'default')
            require(pvc and pvc['status']['phase'] == 'Bound', f'{claim}: source PVC not bound')
            require(pvc['spec']['storageClassName'] == 'miroir-local', f'{claim}: unexpected storage class')
            require(get('pvc', claim, 'downloads') is None, f'downloads/{claim} already exists')
            inventory[app]['claims'][claim] = pvc
        for kind, name in [('kustomization', app), ('kustomization', app+'-db'),
                           ('helmrelease', app), ('externalsecret', app),
                           ('externalsecret', app+'-postgres'),
                           ('snapshotschedules.kopiur.home-operations.com', app)]:
            obj = get(kind, name, 'default')
            require(obj is not None, f'Missing default/{kind}/{name}')
            files[f'old/{kind}-{name}.json'] = clean(obj)
            if kind == 'externalsecret':
                files[f'new/{kind}-{name}.json'] = clean(obj, 'downloads')
        for kind in ('databases.postgresql.cnpg.io', 'databaseroles.postgresql.cnpg.io'):
            obj = get(kind, 'postgres-'+app, 'database')
            require(obj is not None, f'Missing {kind}/postgres-{app}')
            inventory[app][kind] = obj['metadata']['uid']
    for path, obj in files.items():
        save(bundle / path, obj)
    save(bundle / 'inventory.json', inventory)
    print(f'Captured {bundle}. No cluster changes and no Secret values collected.')


def restore_objects(snapshot, pvc, app, run):
    status = snapshot.get('status', {})
    require(status.get('phase') in ('Succeeded', 'Unchanged'), f'{app}: backup did not succeed')
    if snapshot.get('spec', {}).get('pin'):
        require(any(c.get('type') == 'Pinned' and c.get('status') == 'True'
                    for c in status.get('conditions', [])),
                f'{app}: wait for pinning to finish before selecting the snapshot ID')
    require(not status.get('stats', {}).get('filesFailed', 0), f'{app}: backup has failed files')
    resolved = status['resolved']
    require(resolved['sources'] == [{'pvc': f'default/{app}', 'sourcePath': f'/pvc/{app}'}],
            f'{app}: unexpected backup source')
    require(resolved['repository'] == {'kind': 'ClusterRepository', 'name': 'hetzner'},
            f'{app}: unexpected repository')
    point = status['snapshot']
    require(point.get('kopiaSnapshotID'), f'{app}: missing snapshot ID')
    name = f'{app}-{run}'
    restore = {'apiVersion': 'kopiur.home-operations.com/v1alpha1', 'kind': 'Restore',
               'metadata': {'name': name, 'namespace': 'downloads'}, 'spec': {
        'source': {'identity': {**point['identity'], 'snapshotID': point['kopiaSnapshotID']}},
        'repository': resolved['repository'], 'target': {'populator': {}},
        'credentialProjection': {'enabled': True}, 'policy': {'onMissingSnapshot': 'Fail'},
        'options': {'ignoreErrors': False, 'ignorePermissionErrors': False,
                    'skipOwners': False, 'skipPermissions': False},
        'failurePolicy': {'backoffLimit': 1, 'activeDeadlineSeconds': 3600},
        # The new filesystem root is root-owned. Restoring its timestamps and
        # ownership needs the same mover permissions as the storage migration.
        'mover': {'privilegedMode': True,
                  'podSecurityContext': {'runAsUser': 0, 'runAsGroup': 0,
                                         'runAsNonRoot': False, 'fsGroup': 0,
                                         'fsGroupChangePolicy': 'OnRootMismatch'},
                  'securityContext': {'runAsUser': 0, 'runAsGroup': 0,
                                      'runAsNonRoot': False, 'privileged': False,
                                      'capabilities': {'drop': ['ALL'],
                                                       'add': ['CHOWN', 'DAC_OVERRIDE', 'FOWNER', 'FSETID']}}}
    }}
    claim = {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
             'metadata': {'name': app, 'namespace': 'downloads'}, 'spec': {
        'accessModes': pvc['spec']['accessModes'], 'storageClassName': 'miroir-local',
        'resources': pvc['spec']['resources'],
        'dataSourceRef': {'apiGroup': 'kopiur.home-operations.com', 'kind': 'Restore', 'name': name}
    }}
    binder = {'apiVersion': 'v1', 'kind': 'Pod',
              'metadata': {'name': name+'-bind', 'namespace': 'downloads'}, 'spec': {
        'automountServiceAccountToken': False, 'restartPolicy': 'Never',
        'securityContext': {'runAsUser': 1000, 'runAsGroup': 1000, 'runAsNonRoot': True,
                            'seccompProfile': {'type': 'RuntimeDefault'}},
        'containers': [{'name': 'hold', 'image': 'registry.k8s.io/pause:3.10',
                        'securityContext': {'allowPrivilegeEscalation': False,
                                            'capabilities': {'drop': ['ALL']}},
                        'resources': {'requests': {'cpu': '1m', 'memory': '8Mi'},
                                      'limits': {'memory': '32Mi'}},
                        'volumeMounts': [{'name': 'data', 'mountPath': '/data', 'readOnly': True}]}],
        'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': app, 'readOnly': True}}]
    }}
    return {'apiVersion': 'v1', 'kind': 'List', 'items': [restore, claim, binder]}


def restores(bundle, run):
    require(run and all(c.islower() or c.isdigit() or c == '-' for c in run), 'Use a lowercase run ID')
    inventory = json.loads((bundle / 'inventory.json').read_text())
    require(set(inventory) == set(APPS), 'Bundle must include all four apps; take a fresh capture')
    for app in APPS:
        deploy = get('deploy', app, 'default')
        require(deploy and deploy['spec'].get('replicas') == 0 and
                deploy.get('status', {}).get('replicas', 0) == 0, f'{app}: old deployment still running')
        snapshot = get('snapshots.kopiur.home-operations.com', f'{app}-{run}', 'default')
        require(snapshot is not None, f'{app}: missing final snapshot')
        save(bundle / f'backups/{app}.json', snapshot)
        save(bundle / f'restores/{app}.json', restore_objects(
            snapshot, inventory[app]['claims'][app], app, run))
    print('Generated pinned, fail-closed restores and read-only binding pods. No cluster changes.')


def credentials(namespace):
    for app in APPS:
        source = get('secret', app+'-postgres', namespace)
        mirror = get('secret', app+'-postgres', 'database')
        role = get('databaseroles.postgresql.cnpg.io', 'postgres-'+app, 'database')
        require(source and mirror and role, f'{app}: missing credential or role')
        require(source['data'] == mirror['data'], f'{app}: database mirror differs')
        require(mirror['metadata'].get('annotations', {}).get(
            'reflector.v1.k8s.emberstack.com/reflects') == f'{namespace}/{app}-postgres',
            f'{app}: mirror points at the wrong namespace')
        require(role.get('status', {}).get('applied') and
                role['status'].get('secretResourceVersion') == mirror['metadata']['resourceVersion'],
                f'{app}: CNPG has not acknowledged the current password Secret')
        print(f'{app}: mirror matches {namespace}; CNPG acknowledged its resource version')


def restored(bundle, run):
    require(run, 'Specify --run')
    for app in APPS:
        obj = get('restores.kopiur.home-operations.com', f'{app}-{run}', 'downloads')
        require(obj and obj.get('status', {}).get('phase') == 'Completed',
                f'{app}: restore has not completed')
        pvc = get('pvc', app, 'downloads')
        require(pvc and pvc.get('status', {}).get('phase') == 'Bound', f'{app}: PVC not bound')
        expected = json.loads((bundle / f'restores/{app}.json').read_text())['items'][0]
        require(obj['spec']['source'] == expected['spec']['source'], f'{app}: restore source changed')
        print(f'{app}: exact snapshot restored; PVC bound')


def verify(bundle):
    inventory = json.loads((bundle / 'inventory.json').read_text())
    require(set(inventory) == set(APPS), 'Bundle must include all four apps; take a fresh capture')
    credentials('downloads')
    for app in APPS:
        for kind in ('databases.postgresql.cnpg.io', 'databaseroles.postgresql.cnpg.io'):
            obj = get(kind, 'postgres-'+app, 'database')
            require(obj and obj['metadata']['uid'] == inventory[app][kind],
                    f'{app}: database object identity changed')
            require(obj['metadata'].get('labels', {}).get('kustomize.toolkit.fluxcd.io/namespace')
                    == 'downloads', f'{app}: database ownership has not transferred')
        print(f'{app}: database identities retained; ownership moved to downloads')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('capture', 'restores', 'restored', 'credentials', 'verify'))
    parser.add_argument('--bundle', type=Path, default=BUNDLE)
    parser.add_argument('--run')
    parser.add_argument('--namespace', choices=('default', 'downloads'), default='downloads')
    args = parser.parse_args()
    try:
        if args.command == 'capture': capture(args.bundle)
        elif args.command == 'restores': restores(args.bundle, args.run)
        elif args.command == 'restored': restored(args.bundle, args.run)
        elif args.command == 'verify': verify(args.bundle)
        else: credentials(args.namespace)
    except (RuntimeError, KeyError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'STOP: {error}') from None
