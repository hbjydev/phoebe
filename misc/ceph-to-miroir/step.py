#!/usr/bin/env python3
"""Run ONE reviewed migration phase. Without --execute, only describe it."""
import argparse
import fcntl
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote
from prepare import ROOT, DEFAULT_BUNDLE, SERIAL, NODE, require, kubectl, get, command, dump, key

DESCRIPTIONS = {
    'git': 'Apply the reviewed local Git patch. Does not reconcile Flux or change the cluster.',
    'retire': 'IRREVERSIBLE: delete old Ceph CSI snapshots, the hibernated CNPG Cluster (orphan dependents), and exactly the 48 approved source PVCs. Keep Ceph/CSI running for deletion.',
    'ceph-cleanup': 'IRREVERSIBLE: delete Ceph pools and use Rook cleanupPolicy to erase the old OSD and /var/lib/rook. Stop remaining Rook controllers after cleanup succeeds.',
    'talos-volume': 'AFTER Ceph cleanup: apply RawVolumeConfig, then wait for r-miroir on the verified disk.',
    'activate': 'Apply MiroirNode, StorageClass and VolumeSnapshotClass. Does not start applications.',
    'smoke': 'Use a disposable namespace to test Miroir writes, expansion and snapshot restoration.',
    'restore': 'Start Kopiur only; restore one selected application PVC with a pinned backup and strict ownership checks.',
    'restore-all': 'Restore all 34 approved application PVCs sequentially. Stop at the first failure; completed claims are verified again on retry.',
    'caches': 'Create seven empty Miroir cache PVCs. Never recreate the five discarded claims.',
    'postgres': 'Create PostgreSQL from the final Barman backup, using Miroir and a fresh WAL archive prefix.',
    'policies': 'Switch the 34 restored applications\' live Kopiur snapshot policies to miroir-snap; keep schedules suspended.',
    'verify': 'Read-only readiness report. Does not resume writers, operators, Flux or schedules.',
}


def one(kind, name, ns=None):
    text = kubectl('get', kind, name, *(['-n', ns] if ns else []), '--ignore-not-found', '-o', 'json')
    return json.loads(text) if text else None


def poll(description, predicate, seconds=600):
    deadline = time.monotonic() + seconds
    while not predicate():
        require(time.monotonic() < deadline, f'Timed out: {description}; inspect state, do not force finalizers')
        print('Waiting:', description, flush=True)
        time.sleep(5)


def patch(kind, name, ns, spec):
    print(kubectl('patch', kind, name, '-n', ns, '--type=merge', '-p', json.dumps(spec)))


def delete(obj, plural, orphan=False):
    """DELETE with an API-enforced UID precondition, never a label-wide delete."""
    meta = obj['metadata']; version = obj['apiVersion']
    base = '/api/v1' if version == 'v1' else '/apis/' + version
    if meta.get('namespace'): base += '/namespaces/' + quote(meta['namespace'], safe='')
    url = base + '/' + plural + '/' + quote(meta['name'], safe='')
    options = {'apiVersion': 'v1', 'kind': 'DeleteOptions',
               'preconditions': {'uid': meta['uid']},
               'propagationPolicy': 'Orphan' if orphan else 'Background'}
    kubectl('delete', '--raw', url, '-f', '-', data=json.dumps(options))
    print('Deleted', obj['kind'], key(obj))


def apply_file(path):
    # Real admission validation immediately before mutation, with webhooks online.
    kubectl('apply', '--dry-run=server', '-f', str(path))
    print(kubectl('apply', '-f', str(path)))


def create(obj):
    ns = obj['metadata'].get('namespace'); name = obj['metadata']['name']
    existing = one(obj['kind'], name, ns)
    if existing:
        def subset(wanted, actual):
            if isinstance(wanted, dict): return isinstance(actual, dict) and all(k in actual and subset(v, actual[k]) for k, v in wanted.items())
            if isinstance(wanted, list): return isinstance(actual, list) and len(wanted) == len(actual) and all(subset(w, a) for w, a in zip(wanted, actual))
            return wanted == actual
        require(subset(obj.get('spec', {}), existing.get('spec', {})), f'Existing object differs from reviewed manifest: {key(obj)}')
        return
    print(kubectl('create', '-f', '-', data=json.dumps(obj)))


def stream_json(text):
    result = []; decoder = json.JSONDecoder()
    while text.strip():
        text = text.lstrip(); obj, end = decoder.raw_decode(text); result.append(obj); text = text[end:]
    return result


def talos(*args):
    return command('talosctl', '--talosconfig', str(ROOT/'talos/talosconfig'), '-n', '10.70.0.186', *args)


def disk():
    disks = stream_json(talos('get', 'disks', '-o', 'json'))
    matches = [d for d in disks if d['spec'].get('serial') == SERIAL]
    require(len(matches) == 1, 'Expected exactly one disk with the approved serial')
    d = matches[0]; require(d['spec']['size'] == 1000204886016 and not d['spec'].get('readonly'), 'Unexpected disk size or read-only disk')
    # Independently reject a disk that backs a Talos system volume.
    for v in stream_json(talos('get', 'volumestatus', '-o', 'json')):
        if v['metadata']['id'] in ('STATE', 'EPHEMERAL', 'BOOT', 'META', 'EFI'):
            location = v['spec'].get('location', '')
            require(not location.startswith(d['spec']['dev_path']), 'Selected disk contains a Talos system volume')
    return d


def no_pending_volume():
    configs = stream_json(talos('get', 'volumeconfigs', '-o', 'json'))
    require(not any(v['metadata']['id'] == 'r-miroir' for v in configs),
            'Remove the pending Miroir RawVolumeConfig before retiring Ceph; otherwise provisioning could race cleanup')


class Migration:
    def __init__(self, bundle):
        self.bundle = bundle
        self.plan = json.loads((bundle/'plan.json').read_text())
        self.progress_path = bundle/'progress.json'
        self.progress = json.loads(self.progress_path.read_text()) if self.progress_path.exists() else {}

    def done(self, phase):
        self.progress[phase] = True; dump(self.progress_path, self.progress)

    def needs(self, *phases):
        for phase in phases: require(self.progress.get(phase), f'Complete phase {phase} first')

    def frozen(self):
        state = json.loads((ROOT/'kubernetes/.maintenance-state.json').read_text())
        require(state['context'] == self.plan['context'] == 'admin@phoebe', 'Wrong context')
        require(state['snapshots']['run'] == self.plan['run'] and state['snapshots']['complete'], 'Maintenance run changed')
        require(kubectl('config', 'view', '--minify', '-o', 'jsonpath={.clusters[0].cluster.server}') == self.plan['server'], 'Kubernetes API server changed')
        for name in ('flux-operator', 'kustomize-controller', 'helm-controller'):
            obj = one('deployment', name, 'flux-system')
            require(obj and obj['spec'].get('replicas') == 0, f'Flux controller {name} is not frozen')
        for action in state['resources'].values():
            if action['namespace'] == 'kopiur-system' or action['field'] == 'hibernation': continue
            obj = one(action['kind'], action['name'], action['namespace'])
            require(obj and obj['metadata']['uid'] == action['uid'], f'Workload replaced/missing: {action["name"]}')
            field = action['field']
            if field == 'replicas': require(obj['spec'].get('replicas') == 0, f'Writer running: {action["name"]}')
            elif field == 'nodeSelector': require(obj['spec']['template']['spec'].get('nodeSelector', {}).get('maintenance.home.arpa/disabled') == 'true', f'DaemonSet enabled: {action["name"]}')
            elif field == 'suspend': require(obj['spec'].get('suspend') is True, 'Schedule resumed')
            elif field == 'schedule.suspend': require(obj['spec']['schedule'].get('suspend') is True, 'Kopiur schedule resumed')
        for action in state['guards'].values():
            if action['namespace'] == 'flux-system': continue
            obj = one(action['kind'], action['name'], action['namespace'])
            require(obj and obj['metadata']['uid'] == action['uid'], 'Reconciliation guard replaced')
            if action['field'] == 'maintenance': require(obj['spec'].get('maintenance', {}).get('suspended') is True, 'Garage reconciliation resumed')
            else: require(obj['spec'].get('replicas') == 0, f'Operator enabled: {action["name"]}')
        return state

    def git(self):
        require(not self.progress.get('git'), 'Git phase already completed; inspect the local diff')
        patch_file = self.bundle/'git-changes.patch'
        command('git', '-C', str(ROOT), 'apply', '--check', str(patch_file))
        command('git', '-C', str(ROOT), 'apply', str(patch_file))
        self.done('git')
        print('Local files edited. Review/commit/push these changes before eventually resuming Flux.')

    def retire(self):
        self.needs('git')
        state = self.frozen()
        disk(); no_pending_volume()
        sys.path.insert(0, str(ROOT/'kubernetes')); import maintenance
        maintenance.kubectl = lambda *args, **kwargs: kubectl(*args)
        maintenance.verify_stopped('ceph')
        # Refuse stale or replaced source claims before deleting anything.
        approved = {r['claim']: r for r in self.plan['claims']}
        for pvc in get('pvc'):
            if pvc['spec'].get('storageClassName') == 'ceph-block':
                require(key(pvc) in approved and pvc['metadata']['uid'] == approved[key(pvc)]['uid'], f'Unknown/replaced Ceph PVC: {key(pvc)}')
        live = {key(s): s for s in get('snapshots.kopiur.home-operations.com')}
        for row in self.plan['claims']:
            if row['disposition'] != 'restore': continue
            s = live[row['backupRequest']]['status']
            require(s.get('phase') in ('Succeeded', 'Unchanged') and not s.get('stats', {}).get('filesFailed', 0), 'Backup no longer successful')
            require(s['snapshot']['kopiaSnapshotID'] == row['backupID'], 'Backup ID changed')
        backup = one('backups.postgresql.cnpg.io', self.plan['postgresBackup'], 'database')
        require(backup and backup['status'].get('backupId') == self.plan['postgresBackupID'] and backup['status'].get('phase') == 'completed', 'Final database backup missing')
        cluster = one('clusters.postgresql.cnpg.io', 'postgres', 'database')
        if cluster:
            require(cluster['metadata']['uid'] == self.plan['postgresUID'], 'PostgreSQL has already been replaced')
            require(cluster['metadata'].get('annotations', {}).get('cnpg.io/hibernation') == 'on', 'Database not hibernated')
            delete(cluster, 'clusters', orphan=True)
            poll('old PostgreSQL Cluster deletion', lambda: one('clusters.postgresql.cnpg.io', 'postgres', 'database') is None)
        # Only CSI snapshots are deleted; external Kopiur backups stay intact.
        for snap in get('volumesnapshot'):
            if snap['spec'].get('volumeSnapshotClassName') == 'csi-ceph-blockpool': delete(snap, 'volumesnapshots')
        poll('Ceph CSI snapshots and contents deleted', lambda: not any(
            s['spec'].get('driver') == 'rook-ceph.rbd.csi.ceph.com' for s in get('volumesnapshotcontent')))
        for row in self.plan['claims']:
            ns, name = row['claim'].split('/'); pvc = one('pvc', name, ns)
            if not pvc: continue
            require(pvc['metadata']['uid'] == row['uid'], f'PVC was replaced: {row["claim"]}')
            require(pvc['spec'].get('storageClassName') == 'ceph-block', 'Refusing to delete a non-Ceph PVC')
            delete(pvc, 'persistentvolumeclaims')
        old_pvs = {r['pv'] for r in self.plan['claims']}
        poll('old PVCs and PVs deleted by Ceph CSI', lambda: not any(key(p) in approved for p in get('pvc')) and not any(p['metadata']['name'] in old_pvs for p in get('pv')), 1800)
        self.done('retire')

    def ceph_cleanup(self):
        self.needs('retire'); self.frozen(); disk()
        require(not self.progress.get('ceph-cleanup'), 'Ceph cleanup already completed; proceed to talos-volume')
        require({n['metadata']['name'] for n in get('node')} == {NODE}, 'Node inventory changed')
        require(not any(p['spec'].get('storageClassName') == 'ceph-block' for p in get('pvc')), 'Ceph claims remain')
        require(not any('ceph' in p['spec'].get('csi', {}).get('driver', '') for p in get('pv')), 'Ceph PVs remain')
        no_pending_volume()
        cluster = one('cephcluster', 'rook-ceph', 'rook-ceph')
        # Persist this before deletion so retries cannot mistake an unrelated
        # historical cleanup Job for successful cleanup of this cluster.
        if not self.progress.get('cleanup-started'):
            require(cluster and cluster['metadata']['uid'] == self.plan['cephUID'], 'Original CephCluster missing/replaced')
            require(not any(j['metadata']['name'].startswith('rook-ceph-cleanup') for j in get('job', 'rook-ceph')), 'Unexpected pre-existing cleanup jobs')
            self.done('cleanup-started')
        if cluster:
            require(cluster['metadata']['uid'] == self.plan['cephUID'], 'CephCluster replaced')
            storage = cluster['spec']['storage']
            require(storage == self.plan['cephStorage'], 'Ceph storage configuration changed')
            require(SERIAL in storage.get('devicePathFilter', '') and not storage.get('useAllDevices'), 'Ceph disk selection differs from the reviewed single-disk setup')
            require(not get('cephfilesystem', 'rook-ceph') and not get('cephobjectstore', 'rook-ceph'), 'Unexpected Ceph filesystem/object store')
            pools = get('cephblockpool', 'rook-ceph')
            for pool in pools:
                require(self.plan['cephPools'].get(pool['metadata']['name']) == pool['metadata']['uid'], 'Ceph pool replaced/added')
            for pool in pools: delete(pool, 'cephblockpools')
            poll('Ceph pools deleted', lambda: not get('cephblockpool', 'rook-ceph'), 1800)
            patch('cephcluster', 'rook-ceph', 'rook-ceph', {'spec': {'cleanupPolicy': {'confirmation': 'yes-really-destroy-data'}}})
            delete(cluster, 'cephclusters')
        poll('CephCluster deleted', lambda: one('cephcluster', 'rook-ceph', 'rook-ceph') is None, 1800)
        def cleanup_finished():
            jobs = [j for j in get('job', 'rook-ceph') if j['metadata']['name'].startswith('rook-ceph-cleanup')]
            require(not any(any(c['type'] == 'Failed' and c['status'] == 'True' for c in j.get('status', {}).get('conditions', [])) for j in jobs), 'Rook cleanup job failed')
            return bool(jobs) and all(j.get('status', {}).get('succeeded', 0) >= 1 for j in jobs)
        poll('Rook disk/host-path cleanup jobs succeeded', cleanup_finished, 1800)
        # Prevent the old Helm releases/controllers from returning with Flux.
        for kind in ('kustomization', 'helmrelease'):
            for x in get(kind, 'rook-ceph'): patch(kind, x['metadata']['name'], 'rook-ceph', {'spec': {'suspend': True}})
        for name in ('rook-ceph-operator', 'ceph-csi-controller-manager'):
            if one('deployment', name, 'rook-ceph'):
                patch('deployment', name, 'rook-ceph', {'spec': {'replicas': 0}})
                poll(name+' stopped', lambda: not any(p.get('status', {}).get('phase') not in ('Succeeded', 'Failed') and p['metadata']['name'].startswith(name+'-') for p in get('pod', 'rook-ceph')))
        for dep in get('deployment', 'rook-ceph'): patch('deployment', dep['metadata']['name'], 'rook-ceph', {'spec': {'replicas': 0}})
        for ds in get('daemonset', 'rook-ceph'): patch('daemonset', ds['metadata']['name'], 'rook-ceph', {'spec': {'template': {'spec': {'nodeSelector': {'maintenance.home.arpa/disabled': 'true'}}}}})
        poll('all Ceph Pods stopped', lambda: not any(p.get('status', {}).get('phase') not in ('Succeeded', 'Failed') for p in get('pod', 'rook-ceph')))
        sc = one('storageclass', 'ceph-block')
        if sc: delete(sc, 'storageclasses')
        self.done('ceph-cleanup')

    def talos_volume(self):
        self.needs('ceph-cleanup'); self.frozen(); d = disk()
        require(one('cephcluster', 'rook-ceph', 'rook-ceph') is None, 'CephCluster still exists')
        require(not any(p.get('status', {}).get('phase') not in ('Succeeded', 'Failed') for p in get('pod', 'rook-ceph')), 'Ceph Pods still active')
        path = ROOT/'talos/node/phoebe-k-ctrl-01/04-miroir.yaml'
        require(SERIAL in path.read_text(), 'RawVolumeConfig disk selector changed')
        print(talos('patch', 'machineconfig', '--mode=no-reboot', '--patch', '@'+str(path)))
        def ready():
            volumes = stream_json(talos('get', 'volumestatus', '-o', 'json'))
            v = next((v for v in volumes if v['metadata']['id'] == 'r-miroir'), None)
            if not v or v['spec'].get('phase', '').lower() != 'ready': return False
            require(v['spec'].get('location', '').startswith(d['spec']['dev_path']+'p'), 'Miroir partition is on the wrong disk')
            return True
        poll('Talos r-miroir ready', ready, 600); self.done('talos-volume')

    def activate(self):
        self.needs('talos-volume'); self.frozen()
        for name in ('storageclass', 'volumesnapshotclass', 'miroirnode'):
            apply_file(ROOT/f'kubernetes/apps/miroir-system/miroir/config/{name}.yaml')
        self.done('activate')

    def start_kopiur(self):
        state = self.frozen()
        for name in ('kopiur-webhook', 'kopiur-controller'):
            action = state['resources']['Deployment/kopiur-system/'+name]
            require(action['original'] > 0, f'Kopiur was already disabled: {name}')
            patch('deployment', name, 'kopiur-system', {'spec': {'replicas': action['original']}})
            kubectl('rollout', 'status', 'deployment/'+name, '-n', 'kopiur-system', '--timeout=5m')

    def restore(self, claim):
        self.needs('smoke'); self.frozen()
        row = next((r for r in self.plan['claims'] if r['claim'] == claim), None)
        require(row and row['disposition'] == 'restore', 'Choose one of the 34 restore claims from plan.json')
        ns, name = claim.split('/'); current = one('pvc', name, ns)
        require(not current or current['spec'].get('storageClassName') == 'miroir-local', 'Old PVC still exists')
        self.start_kopiur()
        for part in ('restore', 'pvc', 'binder'):
            create(json.loads((self.bundle/'claims'/claim/(part+'.json')).read_text()))
        def complete():
            restore = one('restores.kopiur.home-operations.com', row['restore'], ns)
            status = restore.get('status', {})
            require(status.get('phase') != 'Failed', f'Restore failed: {claim}; inspect status.failure')
            if status.get('phase') != 'Completed': return False
            require(status['resolved']['kopiaSnapshotID'] == row['backupID'], 'Wrong restore point')
            return one('pvc', name, ns).get('status', {}).get('phase') == 'Bound'
        poll('restore '+claim, complete, 15000)
        binder = one('pod', row['restore']+'-bind', ns)
        if binder:
            delete(binder, 'pods')
            poll('binding Pod removed', lambda: one('pod', row['restore']+'-bind', ns) is None)
        self.done('restore:'+claim)

    def restore_all(self):
        for row in self.plan['claims']:
            if row['disposition'] == 'restore': self.restore(row['claim'])

    def caches(self):
        self.needs('smoke'); self.frozen()
        for row in self.plan['claims']:
            if row['disposition'] == 'cache': create(json.loads((self.bundle/'claims'/row['claim']/'pvc.json').read_text()))
        self.done('caches')

    def postgres(self):
        self.needs('smoke'); self.frozen()
        old = one('clusters.postgresql.cnpg.io', 'postgres', 'database')
        require(not old or old['metadata']['uid'] != self.plan['postgresUID'], 'Old Cluster still exists')
        backup = one('backups.postgresql.cnpg.io', self.plan['postgresBackup'], 'database')
        require(backup and backup.get('status', {}).get('phase') == 'completed' and backup['status'].get('backupId') == self.plan['postgresBackupID'], 'Final Backup missing/changed; do not create an empty cluster')
        create(json.loads((self.bundle/'postgres.json').read_text()))
        def ready():
            x = one('clusters.postgresql.cnpg.io', 'postgres', 'database')
            return x.get('status', {}).get('readyInstances') == x['spec']['instances']
        poll('PostgreSQL recovery', ready, 7200); self.done('postgres')

    def smoke(self):
        self.needs('activate'); self.frozen()
        require(one('namespace', 'miroir-smoke') is None, 'miroir-smoke already exists: inspect/delete the previous test before retrying')
        create({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': 'miroir-smoke'}})
        def pvc(name, source=None):
            obj = {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': name, 'namespace': 'miroir-smoke'},
                'spec': {'storageClassName': 'miroir-local', 'accessModes': ['ReadWriteOnce'], 'resources': {'requests': {'storage': '1Gi'}}}}
            if source: obj['spec']['dataSource'] = {'apiGroup': 'snapshot.storage.k8s.io', 'kind': 'VolumeSnapshot', 'name': source}
            return obj
        def pod(name, claim, write):
            return {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': 'miroir-smoke'}, 'spec': {
                'restartPolicy': 'Never', 'automountServiceAccountToken': False, 'nodeSelector': {'kubernetes.io/hostname': NODE},
                'securityContext': {'runAsUser': 1000, 'runAsGroup': 1000, 'runAsNonRoot': True, 'fsGroup': 1000},
                'containers': [{'name': 'check', 'image': 'busybox:1.37.0', 'command': ['sh', '-ec', ('echo miroir-migration > /data/marker; sync; ' if write else '')+'sleep 86400'],
                    'securityContext': {'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']}},
                    'resources': {'requests': {'cpu': '1m', 'memory': '8Mi'}, 'limits': {'memory': '32Mi'}},
                    'volumeMounts': [{'name': 'data', 'mountPath': '/data'}]}],
                'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': claim}}]}}
        create(pvc('source')); create(pod('writer', 'source', True))
        kubectl('wait', 'pod/writer', '-n', 'miroir-smoke', '--for=condition=Ready', '--timeout=10m')
        require(kubectl('exec', '-n', 'miroir-smoke', 'writer', '--', 'cat', '/data/marker') == 'miroir-migration', 'Write/read test failed')
        patch('pvc', 'source', 'miroir-smoke', {'spec': {'resources': {'requests': {'storage': '2Gi'}}}})
        kubectl('wait', 'pvc/source', '-n', 'miroir-smoke', '--for=jsonpath={.status.capacity.storage}=2Gi', '--timeout=10m')
        create({'apiVersion': 'snapshot.storage.k8s.io/v1', 'kind': 'VolumeSnapshot', 'metadata': {'name': 'point', 'namespace': 'miroir-smoke'},
                'spec': {'volumeSnapshotClassName': 'miroir-snap', 'source': {'persistentVolumeClaimName': 'source'}}})
        kubectl('wait', 'volumesnapshot/point', '-n', 'miroir-smoke', '--for=jsonpath={.status.readyToUse}=true', '--timeout=10m')
        clone = pvc('clone', 'point'); clone['spec']['resources']['requests']['storage'] = '2Gi'
        create(clone); create(pod('reader', 'clone', False))
        kubectl('wait', 'pod/reader', '-n', 'miroir-smoke', '--for=condition=Ready', '--timeout=10m')
        require(kubectl('exec', '-n', 'miroir-smoke', 'reader', '--', 'cat', '/data/marker') == 'miroir-migration', 'Snapshot restore did not preserve data')
        delete(one('namespace', 'miroir-smoke'), 'namespaces')
        poll('smoke-test cleanup', lambda: one('namespace', 'miroir-smoke') is None)
        poll('smoke-test PV deletion', lambda: not any(p['spec'].get('claimRef', {}).get('namespace') == 'miroir-smoke' for p in get('pv')))
        self.done('smoke')

    def policies(self):
        self.needs('postgres', 'caches', *('restore:'+r['claim'] for r in self.plan['claims'] if r['disposition'] == 'restore'))
        self.frozen()
        # IfNotPresent policies will not pick up the class change from Git.
        # Check all of them before patching any of them.
        policies = []
        for evidence in json.loads((self.bundle/'backup-evidence.json').read_text()):
            ns = evidence['metadata']['namespace']; name = evidence['spec']['policyRef']['name']
            obj = one('snapshotpolicy', name, ns)
            require(obj and obj['spec'].get('volumeSnapshotClassName') in ('csi-ceph-blockpool', 'miroir-snap'), 'Missing/unexpected snapshot policy: '+ns+'/'+name)
            policies.append((ns, name))
        for ns, name in policies:
            patch('snapshotpolicy', name, ns, {'spec': {'volumeSnapshotClassName': 'miroir-snap'}})
        self.done('policies')

    def verify(self):
        self.needs('policies')
        self.frozen()
        for row in self.plan['claims']:
            ns, name = row['claim'].split('/')
            if row['disposition'] == 'postgres': continue
            pvc = one('pvc', name, ns)
            if row['disposition'] == 'discard': require(pvc is None, 'Discarded claim returned: '+row['claim']); continue
            require(pvc and pvc['spec'].get('storageClassName') == 'miroir-local', 'Miroir claim missing: '+row['claim'])
            if row['disposition'] == 'restore':
                r = one('restores.kopiur.home-operations.com', row['restore'], ns)
                require(r and r.get('status', {}).get('phase') == 'Completed' and r['status']['resolved']['kopiaSnapshotID'] == row['backupID'] and pvc.get('status', {}).get('phase') == 'Bound', 'Restore incomplete: '+row['claim'])
        pg = one('clusters.postgresql.cnpg.io', 'postgres', 'database')
        require(pg and pg['spec']['storage']['storageClass'] == 'miroir-local' and pg.get('status', {}).get('readyInstances') == pg['spec']['instances'], 'PostgreSQL not recovered')
        for evidence in json.loads((self.bundle/'backup-evidence.json').read_text()):
            obj = one('snapshotpolicy', evidence['spec']['policyRef']['name'], evidence['metadata']['namespace'])
            require(obj and obj['spec'].get('volumeSnapshotClassName') == 'miroir-snap', 'Snapshot policy still targets Ceph')
        print('Storage recovery verified. Application validation and resuming operators/Flux remain separate review steps. Read README.md before resuming; do not run restore-ceph unchanged.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=DESCRIPTIONS)
    parser.add_argument('--bundle', type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument('--claim', help='namespace/PVC for the restore phase')
    parser.add_argument('--execute', action='store_true', help='Run the selected phase after typed confirmation')
    args = parser.parse_args()
    print(DESCRIPTIONS[args.phase])
    if not args.execute:
        print('Preview only. Review the script and bundle; add --execute to run this phase.'); return
    migration = Migration(args.bundle.resolve())
    if args.phase != 'verify':
        phrase = 'DISCARD CEPH '+SERIAL if args.phase in ('retire', 'ceph-cleanup') else args.phase
        require(input(f'Type {phrase!r} to continue: ') == phrase, 'Cancelled')
    with (ROOT/'kubernetes/.maintenance-state.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.phase == 'restore': migration.restore(args.claim)
        else: getattr(migration, args.phase.replace('-', '_'))()

if __name__ == '__main__':
    try: main()
    except (RuntimeError, subprocess.CalledProcessError, KeyError, StopIteration, BlockingIOError) as error:
        sys.exit(f'STOP: {error}')
