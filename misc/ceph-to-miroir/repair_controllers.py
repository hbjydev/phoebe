#!/usr/bin/env python3
"""Prepare and explicitly execute one controller repair at a time after recovery."""
import argparse
import copy
import difflib
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

from prepare import ROOT, DEFAULT_BUNDLE, dump, get, kubectl, require
from step import delete, one, poll

STATE = ROOT / 'kubernetes/.maintenance-state.json'
BUNDLE = DEFAULT_BUNDLE / 'controllers'
MARK = 'migration.home.arpa/controller-repair'
TARGETS = {
    'slskd': ('downloads', 'slskd', 'config-slskd-0'),
    'gatus': ('observability', 'gatus', 'config-gatus-0'),
    'kanidm': ('security', 'kanidm-default', 'kanidm-data-kanidm-default-0'),
}
BACKUP = 'postgres-post-miroir'


def uid(obj):
    return obj['metadata']['uid']


def manifest(obj):
    """Keep ownership and desired configuration; discard server bookkeeping."""
    result = copy.deepcopy({k: obj[k] for k in ('apiVersion', 'kind', 'spec')})
    result['metadata'] = {k: copy.deepcopy(obj['metadata'][k]) for k in
                          ('name', 'namespace', 'labels', 'annotations', 'ownerReferences')
                          if k in obj['metadata']}
    result['metadata'].get('annotations', {}).pop('kubectl.kubernetes.io/last-applied-configuration', None)
    for template in result['spec'].get('volumeClaimTemplates', []):
        template.pop('status', None)
        template['metadata'] = {k: v for k, v in template['metadata'].items()
                                if k in ('name', 'labels', 'annotations')}
    return result


def replacement(obj, token):
    result = manifest(obj)
    spec = result['spec']
    require(spec.get('replicas') == 1 and spec.get('ordinals', {}).get('start', 0) == 0,
            'This repair is scoped to one replica at ordinal zero')
    retention = spec.get('persistentVolumeClaimRetentionPolicy', {})
    require(all(retention.get(k, 'Retain') == 'Retain' for k in ('whenDeleted', 'whenScaled')),
            'PVC retention must be Retain for both deletion and scaling')
    require(len(spec.get('volumeClaimTemplates', [])) == 1, 'Expected exactly one claim template')
    claim = spec['volumeClaimTemplates'][0]['spec']
    require(claim.get('storageClassName') == 'ceph-block', 'Expected the original Ceph claim template')
    claim['storageClassName'] = 'miroir-local'
    result['metadata'].setdefault('annotations', {})[MARK] = token
    return result


def checked_claim(ns, name, pinned=None):
    obj = one('pvc', name, ns)
    require(obj and not obj['metadata'].get('deletionTimestamp'), f'PVC missing/deleting: {ns}/{name}')
    require(obj['spec'].get('storageClassName') == 'miroir-local'
            and obj.get('status', {}).get('phase') == 'Bound', f'PVC is not Bound on Miroir: {ns}/{name}')
    identity = {'uid': uid(obj), 'volume': obj['spec']['volumeName']}
    if pinned is not None:
        require(identity == pinned, f'PVC identity/binding changed: {ns}/{name}')
    pv = one('pv', identity['volume'])
    require(pv and pv['spec'].get('claimRef', {}).get('uid') == identity['uid'], 'PV claim reference differs')
    return identity


def backup_checkpoint(pinned=None):
    pg = one('cluster.postgresql.cnpg.io', 'postgres', 'database')
    backup = one('backup.postgresql.cnpg.io', BACKUP, 'database')
    require(pg and pg['spec']['storage']['storageClass'] == 'miroir-local'
            and pg.get('status', {}).get('readyInstances') == pg['spec']['instances'], 'PostgreSQL is not ready on Miroir')
    require(any(p.get('enabled', True) and p.get('isWALArchiver')
                and p.get('name') == 'barman-cloud.cloudnative-pg.io'
                and p.get('parameters', {}).get('serverName') == 'postgres-miroir'
                for p in pg['spec'].get('plugins', [])), 'Expected the postgres-miroir WAL archive')
    status = (backup or {}).get('status', {})
    require(status.get('phase') == 'completed' and status.get('backupId')
            and status.get('pluginMetadata', {}).get('clusterUID') == uid(pg),
            'Fresh backup is not completed for the current PostgreSQL Cluster')
    evidence = {'clusterUID': uid(pg), 'backupUID': uid(backup), 'backupID': status['backupId']}
    if pinned is not None:
        require(evidence == pinned, 'PostgreSQL/backup identity changed since preparation')
    return evidence


def selected_pods(obj):
    selector = obj['spec']['selector']
    require(not selector.get('matchExpressions'), 'Unexpected selector expressions')
    labels = selector['matchLabels']
    return [p for p in get('pods', obj['metadata']['namespace'])
            if all(p['metadata'].get('labels', {}).get(k) == v for k, v in labels.items())]


def frozen():
    for name in ('flux-operator', 'helm-controller', 'kustomize-controller'):
        deployment = one('deployment', name, 'flux-system')
        require(deployment and deployment['spec'].get('replicas') == 0
                and not selected_pods(deployment), f'Flux controller must remain stopped: {name}')
    for kind in ('kustomization.kustomize.toolkit.fluxcd.io', 'helmrelease.helm.toolkit.fluxcd.io'):
        for name in ('rook-ceph', 'ceph-csi-drivers', 'rook-ceph-cluster'):
            obj = one(kind, name, 'rook-ceph')
            require(obj and obj['spec'].get('suspend') is True, f'Rook must remain suspended: {kind}/{name}')


def atomic_json(path, value):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as handle:
        json.dump(value, handle, indent=2)
        handle.write('\n')
        temporary = handle.name
    Path(temporary).replace(path)


def update_uid(state, key, old, new):
    result = copy.deepcopy(state)
    action = result['resources'][key]
    require(action['uid'] in (old, new), f'Saved maintenance UID changed: {key}')
    action['uid'] = new
    return result


def adopt(key, old, new):
    # Caller holds the same lock as maintenance.py. Preserve every other field.
    state = json.loads(STATE.read_text())
    atomic_json(STATE, update_uid(state, key, old, new))
    print('Saved maintenance UID:', key, new)


def guarded_patch(obj, changes):
    operations = [
        {'op': 'test', 'path': '/metadata/uid', 'value': uid(obj)},
        {'op': 'test', 'path': '/metadata/resourceVersion', 'value': obj['metadata']['resourceVersion']},
        *changes,
    ]
    print(kubectl('patch', obj['kind'], obj['metadata']['name'], '-n', obj['metadata']['namespace'],
                  '--type=json', '-p', json.dumps(operations)))


def prepare_bundle():
    require(not BUNDLE.exists(), f'Bundle already exists: {BUNDLE}; review it, do not regenerate mid-repair')
    frozen()
    state = json.loads(STATE.read_text())
    plan = {'token': str(uuid.uuid4()), 'postgres': backup_checkpoint(), 'targets': {}}
    plan['postgres']['oldUID'] = state['resources']['Cluster/database/postgres']['uid']
    operator = one('deployment', 'kaniop', 'security')
    parent = one('kanidm.kaniop.rs', 'kanidm', 'security')
    require(operator and parent, 'Kaniop operator/parent missing')
    require(uid(operator) == state['guards']['Deployment/security/kaniop']['uid'], 'Kaniop operator UID changed')
    plan['operator'] = {'uid': uid(operator), 'replicas': operator['spec']['replicas']}
    plan['parentUID'] = uid(parent)
    require(parent['spec']['storage']['volumeClaimTemplate']['spec']['storageClassName']
            in ('ceph-block', 'miroir-local'), 'Unexpected Kanidm storage configuration')
    files = {}
    for short, (ns, name, claim) in TARGETS.items():
        obj = one('statefulset', name, ns)
        require(obj and not obj['metadata'].get('deletionTimestamp'), f'StatefulSet missing/deleting: {short}')
        key = f'StatefulSet/{ns}/{name}'
        require(uid(obj) == state['resources'][key]['uid'], f'StatefulSet UID differs from maintenance state: {short}')
        require(obj.get('status', {}).get('readyReplicas') == 1, f'StatefulSet not ready: {short}')
        require(obj['spec']['volumeClaimTemplates'][0]['metadata']['name'] + '-' + name + '-0' == claim,
                'Unexpected PVC template/name')
        owners = obj['metadata'].get('ownerReferences', [])
        require((not owners if short != 'kanidm' else len(owners) == 1 and owners[0]['uid'] == uid(parent)),
                'Unexpected StatefulSet owner')
        before = manifest(obj)
        after = replacement(obj, plan['token'])
        plan['targets'][short] = {'oldUID': uid(obj), 'claim': checked_claim(ns, claim)}
        files[short + '.before.json'] = before
        files[short + '.json'] = after
    BUNDLE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=BUNDLE.parent) as tmp:
        directory = Path(tmp) / 'controllers'
        directory.mkdir(mode=0o700)
        for name, value in {**files, 'plan.json': plan, 'maintenance-state.before.json': state}.items():
            dump(directory / name, value)
        for short in TARGETS:
            before = (json.dumps(files[short + '.before.json'], indent=2) + '\n').splitlines(keepends=True)
            after = (json.dumps(files[short + '.json'], indent=2) + '\n').splitlines(keepends=True)
            (directory / (short + '.diff')).write_text(''.join(difflib.unified_diff(before, after, 'live', 'replacement')))
        directory.rename(BUNDLE)
    print('Prepared local review bundle:', BUNDLE)
    print('No cluster resources or maintenance state were changed.')


def ready(obj, ns, name):
    current = one('statefulset', name, ns)
    require(current and uid(current) == uid(obj), 'Replacement StatefulSet disappeared/changed')
    pods = selected_pods(current)
    return (current.get('status', {}).get('observedGeneration', 0) >= current['metadata']['generation']
            and current.get('status', {}).get('readyReplicas') == 1 and len(pods) == 1
            and not pods[0]['metadata'].get('deletionTimestamp')
            and any(o.get('controller') and o['uid'] == uid(current) for o in pods[0]['metadata'].get('ownerReferences', []))
            and any(c['type'] == 'Ready' and c['status'] == 'True' for c in pods[0].get('status', {}).get('conditions', [])))


def repair(short, plan):
    ns, name, claim = TARGETS[short]
    pin = plan['targets'][short]
    before = json.loads((BUNDLE / (short + '.before.json')).read_text())
    desired = json.loads((BUNDLE / (short + '.json')).read_text())
    # Only the storage class and our retry marker may differ from the capture.
    require(desired == replacement(before, plan['token']), 'Reviewed manifest has changes outside this repair')
    frozen()
    backup_checkpoint({k: v for k, v in plan['postgres'].items() if k != 'oldUID'})
    checked_claim(ns, claim, pin['claim'])
    obj = one('statefulset', name, ns)
    if obj:
        require(not obj['metadata'].get('deletionTimestamp') or uid(obj) == pin['oldUID'],
                'Replacement is being deleted; stop for review')
        if uid(obj) == pin['oldUID']:
            require(manifest(obj) == before, 'Original StatefulSet configuration changed; stop for review')
        else:
            require(obj['metadata'].get('annotations', {}).get(MARK) == plan['token']
                    and manifest(obj) == desired, 'An unrecognized replacement exists; stop for review')
    saved = json.loads(STATE.read_text())['resources'][f'StatefulSet/{ns}/{name}']['uid']
    require(saved in (pin['oldUID'], uid(obj) if obj else pin['oldUID']), 'Saved maintenance UID changed')
    if short == 'kanidm':
        operator = one('deployment', 'kaniop', 'security')
        require(operator and uid(operator) == plan['operator']['uid'], 'Kaniop operator changed')
        require(operator['spec']['replicas'] in (0, plan['operator']['replicas']), 'Kaniop replicas changed')
        guarded_patch(operator, [{'op': 'replace', 'path': '/spec/replicas', 'value': 0}])
        poll('Kaniop operator Pods removed', lambda: not selected_pods(operator))
        parent = one('kanidm.kaniop.rs', 'kanidm', 'security')
        require(parent and uid(parent) == plan['parentUID'], 'Kanidm parent changed')
        require(parent['spec']['storage']['volumeClaimTemplate']['spec']['storageClassName']
                in ('ceph-block', 'miroir-local'), 'Kanidm parent storage changed')
        guarded_patch(parent, [{'op': 'replace', 'path': '/spec/storage/volumeClaimTemplate/spec/storageClassName',
                                'value': 'miroir-local'}])
    obj = one('statefulset', name, ns)
    if obj and uid(obj) == pin['oldUID']:
        require(manifest(obj) == before, 'Original StatefulSet configuration changed; stop for review')
        delete(obj, 'statefulsets', orphan=True)
        poll('old StatefulSet removed (Pods and PVCs retained)', lambda: one('statefulset', name, ns) is None)
        obj = None
    if obj is None:
        # Verify orphaning finished before adoption; never delete a Pod or PVC.
        poll('Pods orphaned from the old StatefulSet', lambda: all(
            not any(o.get('uid') == pin['oldUID'] for o in p['metadata'].get('ownerReferences', []))
            for p in selected_pods(desired)))
        checked_claim(ns, claim, pin['claim'])
        print(kubectl('create', '-f', '-', data=json.dumps(desired)))
        obj = one('statefulset', name, ns)
    require(obj and obj['metadata'].get('annotations', {}).get(MARK) == plan['token'],
            'An unrecognized replacement exists; stop for review')
    require(manifest(obj) == desired, 'Replacement configuration differs from the reviewed manifest')
    adopt(f'StatefulSet/{ns}/{name}', pin['oldUID'], uid(obj))
    poll('replacement StatefulSet ready and Pod adopted', lambda: ready(obj, ns, name))
    checked_claim(ns, claim, pin['claim'])
    if short == 'kanidm':
        operator = one('deployment', 'kaniop', 'security')
        require(operator and uid(operator) == plan['operator']['uid'], 'Kaniop operator changed')
        guarded_patch(operator, [{'op': 'replace', 'path': '/spec/replicas', 'value': plan['operator']['replicas']}])
        if plan['operator']['replicas']:
            print(kubectl('rollout', 'status', 'deployment/kaniop', '-n', 'security', '--timeout=300s'))
    print('Repaired', short, 'with the original restored PVC and binding preserved.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('prepare', *TARGETS, 'adopt-postgres'))
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.phase == 'prepare':
        require(not args.execute, 'prepare only reads the cluster and writes a new local review bundle')
    elif not args.execute:
        print('Preview only. Add --execute and confirm after reviewing', BUNDLE)
        print('Update the saved PostgreSQL UID only.' if args.phase == 'adopt-postgres' else
              f'Orphan-recreate {args.phase} with miroir-local, retain Pods/PVCs, update its saved UID.'
              + (' Pause Kaniop, fix its parent storage class, and restore its captured replica count on success.'
                 if args.phase == 'kanidm' else ''))
        return
    elif input(f"Type '{args.phase}' to continue: ") != args.phase:
        raise RuntimeError('Confirmation did not match')
    with STATE.with_name('.maintenance-state.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.phase == 'prepare':
            prepare_bundle()
            return
        plan = json.loads((BUNDLE / 'plan.json').read_text())
        if args.phase == 'adopt-postgres':
            backup_checkpoint({k: v for k, v in plan['postgres'].items() if k != 'oldUID'})
            adopt('Cluster/database/postgres', plan['postgres']['oldUID'], plan['postgres']['clusterUID'])
        else:
            repair(args.phase, plan)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print('STOP:', str(error) or repr(error), file=sys.stderr)
        print('If the Kanidm repair stopped after pausing Kaniop, it remains paused. Inspect the error and retry '
              'the same phase; do not regenerate the bundle or restore the old maintenance-state backup.', file=sys.stderr)
        sys.exit(1)
