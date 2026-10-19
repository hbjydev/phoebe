"""Offline tests: no kubectl, Talos, or remote services are used."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import prepare
import step

sys.path.insert(0, str(prepare.ROOT / 'kubernetes'))
import maintenance


def fixture():
    sources = ['observability/config-gatus-0', 'garage-system/garage-meta']
    sources += ['apps/data-'+str(n) for n in range(32)]
    claims = []
    for name in sorted(set(sources) | prepare.CACHES | prepare.DISCARD | prepare.DATABASE):
        ns, pvc = name.split('/')
        claims.append({'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
                       'metadata': {'namespace': ns, 'name': pvc, 'uid': 'old-'+pvc},
                       'spec': {'storageClassName': 'ceph-block', 'volumeName': 'pv-'+pvc,
                                'accessModes': ['ReadWriteOnce'], 'resources': {'requests': {'storage': '5Gi'}}}})
    backups = []
    for source in sources:
        ns, name = source.split('/')
        backups.append({'kind': 'Snapshot', 'metadata': {'namespace': ns, 'name': 'final-'+name},
                        'spec': {'policyRef': {'name': name}},
                        'status': {'phase': 'Succeeded', 'stats': {'filesFailed': 0},
                                   'resolved': {'sources': [{'pvc': source}], 'repository': {'kind': 'ClusterRepository', 'name': 'hetzner'}},
                                   'snapshot': {'kopiaSnapshotID': 'pinned-'+name,
                                                'identity': {'username': ns+'-'+name, 'hostname': ns, 'sourcePath': '/pvc/'+name}}}})
    state = {'snapshots': {'complete': True, 'requests': backups}}
    return claims, backups, state


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.claims, self.backups, self.state = fixture()

    def test_every_claim_is_accounted_for_and_backups_pinned(self):
        rows, objects = prepare.build(self.claims, self.backups, self.state)
        self.assertEqual(len(rows), 48)
        self.assertEqual({d: sum(r['disposition'] == d for r in rows) for d in ('restore', 'cache', 'discard', 'postgres')},
                         {'restore': 34, 'cache': 7, 'discard': 5, 'postgres': 2})
        self.assertIn('observability/config-gatus-0', objects)
        self.assertNotIn('observability/gatus', objects)
        for row in rows:
            if row['disposition'] != 'restore': continue
            parts = objects[row['claim']]
            spec = parts['restore']['spec']
            self.assertEqual(spec['source']['identity']['snapshotID'], row['backupID'])
            self.assertEqual(spec['policy']['onMissingSnapshot'], 'Fail')
            self.assertFalse(spec['options']['skipOwners'])
            self.assertFalse(spec['options']['ignorePermissionErrors'])
            self.assertNotIn('volumeName', parts['pvc']['spec'])
            self.assertEqual(parts['pvc']['spec']['dataSourceRef']['name'], row['restore'])
            self.assertTrue(parts['binder']['spec']['volumes'][0]['persistentVolumeClaim']['readOnly'])

    def test_changed_inventory_is_rejected(self):
        for change in ('extra', 'missing', 'replacement-source'):
            with self.subTest(change=change):
                claims = copy.deepcopy(self.claims)
                if change == 'extra':
                    extra = copy.deepcopy(claims[0]); extra['metadata']['name'] = 'unknown'; claims.append(extra)
                elif change == 'missing': claims.pop()
                else: claims[0]['metadata']['name'] = 'renamed'
                with self.assertRaises(RuntimeError): prepare.build(claims, self.backups, self.state)

    def test_bad_backups_are_rejected(self):
        for change in ('missing', 'failed', 'file-error', 'no-id', 'repository', 'duplicate-source'):
            with self.subTest(change=change):
                backups = copy.deepcopy(self.backups)
                if change == 'missing': backups.pop()
                elif change == 'failed': backups[0]['status']['phase'] = 'Failed'
                elif change == 'file-error': backups[0]['status']['stats']['filesFailed'] = 1
                elif change == 'no-id': del backups[0]['status']['snapshot']['kopiaSnapshotID']
                elif change == 'repository': backups[0]['status']['resolved']['repository']['name'] = 'other'
                else: backups[0]['status']['resolved']['sources'] = backups[1]['status']['resolved']['sources']
                with self.assertRaises(RuntimeError): prepare.build(self.claims, backups, self.state)

    def test_incomplete_shutdown_is_rejected(self):
        self.state['snapshots']['complete'] = False
        with self.assertRaises(RuntimeError): prepare.build(self.claims, self.backups, self.state)

    def test_claim_keeps_helm_ownership_but_not_binding_or_owner_uid(self):
        old = self.claims[0]
        old['metadata'].update(labels={'app.kubernetes.io/managed-by': 'Helm'},
                               annotations={'meta.helm.sh/release-name': 'example', 'pv.kubernetes.io/bind-completed': 'yes'},
                               ownerReferences=[{'uid': 'old-owner'}])
        new = prepare.new_claim(old)
        self.assertEqual(new['metadata']['annotations'], {'meta.helm.sh/release-name': 'example'})
        self.assertEqual(new['metadata']['labels'], old['metadata']['labels'])
        self.assertNotIn('ownerReferences', new['metadata'])

    def test_git_patch_covers_default_class_policies_recovery_and_freeze(self):
        # Use pre-cutover fixtures: the user's working tree may already have
        # the generated patch applied while the migration is in progress.
        files = {
            'kubernetes/apps/database/postgres/cluster/cluster.yaml':
                'metadata:\n  name: postgres\n  annotations:\n    cnpg.io/skipEmptyWalArchiveCheck: enabled\n'
                f'spec:\n  bootstrap:\n    recovery:\n      backup:\n        name: {prepare.PG_BACKUP}\n'
                '  plugins:\n    - name: barman-cloud.cloudnative-pg.io\n      parameters:\n        barmanObjectName: &store barman-hetzner\n',
            'kubernetes/apps/miroir-system/miroir/config/storageclass.yaml': 'metadata:\n  name: miroir-local\n',
            'kubernetes/apps/miroir-system/miroir/config/kustomization.yaml': 'resources: []\n',
            'kubernetes/components/kopiur/snapshotpolicy.yaml': 'spec:\n  volumeSnapshotClassName: "${KOPIUR_SNAPSHOTCLASS:=csi-ceph-blockpool}"\n',
            'kubernetes/apps/rook-ceph/rook-ceph/ks.yaml': '\n---\nspec:\n  interval: 1h\n' * 3,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, value in files.items():
                path = root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(value)
            with patch.object(prepare, 'ROOT', root): diff = prepare.git_patch()
        self.assertIn('+    storageclass.kubernetes.io/is-default-class: "true"', diff)
        self.assertIn('+        serverName: postgres-miroir', diff)
        self.assertIn('+        backupID: '+prepare.PG_BACKUP_ID, diff)
        self.assertIn('+      source: backup', diff)
        self.assertEqual(diff.count('+  suspend: true'), 3)
        self.assertIn('${KOPIUR_SNAPSHOTCLASS:=miroir-snap}', diff)


class PrepareTests(unittest.TestCase):
    def run_prepare(self, out, *, missing_backup=False, source_server='postgres'):
        claims, backups, state = fixture()
        state.update(context='admin@phoebe', server='https://example.test', stages=['ceph'])
        state['snapshots']['run'] = 'test-run'
        (out.parent/'kubernetes').mkdir(exist_ok=True)
        (out.parent/'kubernetes/.maintenance-state.json').write_text(json.dumps(state))
        pg = {'apiVersion': 'postgresql.cnpg.io/v1', 'kind': 'Cluster',
              'metadata': {'name': 'postgres', 'namespace': 'database', 'uid': 'pg-original',
                           'annotations': {'cnpg.io/hibernation': 'on'}},
              'spec': {'storage': {'storageClass': 'ceph-block'},
                       'managed': {'roles': [{'name': 'app-role'}]},
                       'plugins': [{'name': 'barman-cloud.cloudnative-pg.io', 'parameters': {'barmanObjectName': 'barman-hetzner'}}],
                       # Live cluster uses "source"; Git currently uses "backup".
                       'externalClusters': [{'name': 'source', 'plugin': {'name': 'barman-cloud.cloudnative-pg.io',
                                            'parameters': {'barmanObjectName': 'barman-hetzner', 'serverName': source_server}}}]}}
        objects = {
            'deployment': [{'metadata': {'name': n}, 'spec': {'replicas': 0}} for n in ('flux-operator', 'kustomize-controller', 'helm-controller')],
            'pvc': claims, 'snapshots.kopiur.home-operations.com': backups,
            'clusters.postgresql.cnpg.io': [pg],
            'backups.postgresql.cnpg.io': [] if missing_backup else [{'metadata': {'name': prepare.PG_BACKUP}, 'status': {'phase': 'completed', 'backupId': prepare.PG_BACKUP_ID}}],
            'cephcluster': [{'metadata': {'name': 'rook-ceph', 'uid': 'ceph-original'}, 'spec': {'storage': {}}}],
            'node': [{'metadata': {'name': prepare.NODE}}],
            'job': [], 'cephfilesystem': [], 'cephobjectstore': [], 'cephblockpool': [],
            'namespace': [{'metadata': {'name': n, 'annotations': {'kopiur.home-operations.com/privileged-movers': 'true'}}} for n in {c['metadata']['namespace'] for c in claims}],
        }
        with patch.object(prepare, 'ROOT', out.parent), patch.object(prepare, 'get', side_effect=lambda kind, ns=None: objects[kind]), patch.object(prepare, 'kubectl', return_value=state['server']), patch.object(prepare, 'git_patch', return_value='reviewed diff'), patch.object(maintenance, 'verify_stopped'), patch.object(maintenance, 'kubectl'):
            prepare.prepare(out)

    def test_live_recovery_source_alias_does_not_produce_empty_stop(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            out = Path(tmp)/'bundle'
            try:
                self.run_prepare(out)
            except Exception as error:
                self.fail(f'STOP: {error}')
            pg = json.loads((out/'postgres.json').read_text())
            source_name = pg['spec']['bootstrap']['recovery']['source']
            source = next(x for x in pg['spec']['externalClusters'] if x['name'] == source_name)
            self.assertEqual(source['plugin']['parameters']['serverName'], 'postgres')
            self.assertEqual(pg['spec']['managed']['roles'], [{'name': 'app-role'}])

    def test_missing_backup_has_actionable_error_and_no_partial_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'bundle'
            with self.assertRaisesRegex(RuntimeError, prepare.PG_BACKUP):
                self.run_prepare(out, missing_backup=True)
            self.assertFalse(out.exists())

    def test_wrong_recovery_archive_leaves_no_partial_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'bundle'
            with self.assertRaisesRegex(RuntimeError, 'recovery'):
                self.run_prepare(out, source_server='wrong-archive')
            self.assertFalse(out.exists())


class PlexExceptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        state = {'context': 'admin@phoebe', 'snapshots': {'run': 'run', 'complete': True},
                 'guards': {}, 'resources': {}}
        for name in ('plex', 'other'):
            state['resources']['Deployment/media/'+name] = {'kind': 'Deployment', 'namespace': 'media',
                'name': name, 'uid': 'deployment-'+name, 'field': 'replicas'}
        (self.root/'kubernetes').mkdir()
        (self.root/'kubernetes/.maintenance-state.json').write_text(json.dumps(state))
        self.migration = step.Migration.__new__(step.Migration)
        self.migration.allow_plex = True
        self.migration.plan = {'context': 'admin@phoebe', 'run': 'run', 'server': 'https://example.test',
            'claims': [{'claim': 'media/plex', 'disposition': 'restore', 'restore': 'plex-point', 'backupID': 'pinned'}]}
        self.migration.progress = {'smoke': True, 'restore:media/plex': True}
        self.plex = {'metadata': {'uid': 'deployment-plex'}, 'spec': {'replicas': 1,
            'template': {'spec': {'volumes': [{'persistentVolumeClaim': {'claimName': 'plex'}}]}}}}
        self.other = {'metadata': {'uid': 'deployment-other'}, 'spec': {'replicas': 0}}
        self.flux = {'spec': {'replicas': 0}}
        self.pvc = {'metadata': {'uid': 'restored-pvc'}, 'spec': {'storageClassName': 'miroir-local',
            'dataSourceRef': {'apiGroup': 'kopiur.home-operations.com', 'kind': 'Restore', 'name': 'plex-point'}},
            'status': {'phase': 'Bound'}}
        self.restore = {'status': {'phase': 'Completed', 'resolved': {'kopiaSnapshotID': 'pinned'},
            'claims': {'plex': {'uid': 'restored-pvc', 'phase': 'Populated', 'resolved': {'kopiaSnapshotID': 'pinned'}}}}}
        self.addCleanup(patch.stopall)
        patch.object(step, 'ROOT', self.root).start()
        patch.object(step, 'kubectl', return_value='https://example.test').start()
        patch.object(step, 'one', side_effect=self.one).start()

    def one(self, kind, name, ns=None):
        if ns == 'flux-system': return self.flux
        if kind == 'pvc': return self.pvc
        if kind == 'restores.kopiur.home-operations.com': return self.restore
        if name == 'plex': return self.plex
        if name == 'other': return self.other
        raise AssertionError((kind, name, ns))

    def test_completed_plex_is_allowed_only_with_explicit_flag_and_phase(self):
        self.migration.frozen(allow_plex=True)
        with self.assertRaisesRegex(RuntimeError, 'Writer running: plex'): self.migration.frozen()
        self.migration.allow_plex = False
        with self.assertRaisesRegex(RuntimeError, 'Writer running: plex'): self.migration.frozen(allow_plex=True)

    def test_other_writer_and_flux_still_block(self):
        self.other['spec']['replicas'] = 1
        with self.assertRaisesRegex(RuntimeError, 'Writer running: other'): self.migration.frozen(allow_plex=True)
        self.other['spec']['replicas'] = 0; self.flux['spec']['replicas'] = 1
        with self.assertRaisesRegex(RuntimeError, 'Flux controller'): self.migration.frozen(allow_plex=True)

    def test_replaced_deployment_or_extra_claim_blocks(self):
        self.plex['metadata']['uid'] = 'replacement'
        with self.assertRaisesRegex(RuntimeError, 'Workload replaced'): self.migration.frozen(allow_plex=True)
        self.plex['metadata']['uid'] = 'deployment-plex'
        self.plex['spec']['template']['spec']['volumes'].append({'persistentVolumeClaim': {'claimName': 'other'}})
        with self.assertRaisesRegex(RuntimeError, 'exactly the restored'): self.migration.frozen(allow_plex=True)

    def test_incomplete_or_replaced_restore_blocks(self):
        self.migration.progress['restore:media/plex'] = False
        with self.assertRaisesRegex(RuntimeError, 'Complete phase'): self.migration.frozen(allow_plex=True)
        self.migration.progress['restore:media/plex'] = True
        original = copy.deepcopy(self.restore)
        for change in ('phase', 'snapshot', 'claim-uid', 'claim-phase', 'claim-snapshot'):
            with self.subTest(change=change):
                self.restore = copy.deepcopy(original)
                status = self.restore['status']; claim = status['claims']['plex']
                if change == 'phase': status['phase'] = 'Running'
                elif change == 'snapshot': status['resolved']['kopiaSnapshotID'] = 'wrong'
                elif change == 'claim-uid': claim['uid'] = 'old-pvc'
                elif change == 'claim-phase': claim['phase'] = 'Populating'
                else: claim['resolved']['kopiaSnapshotID'] = 'wrong'
                with self.assertRaisesRegex(RuntimeError, 'not complete'): self.migration.frozen(allow_plex=True)

    def test_wrong_storage_or_source_blocks(self):
        self.pvc['spec']['storageClassName'] = 'ceph-block'
        with self.assertRaisesRegex(RuntimeError, 'not Bound on Miroir'): self.migration.frozen(allow_plex=True)
        self.pvc['spec']['storageClassName'] = 'miroir-local'
        self.pvc['spec']['dataSourceRef']['name'] = 'another-restore'
        with self.assertRaisesRegex(RuntimeError, 'different restore source'): self.migration.frozen(allow_plex=True)

    def test_restore_all_skips_plex_without_mover_or_binding_pod(self):
        with patch.object(step, 'create') as create, patch.object(step, 'delete') as delete, patch.object(self.migration, 'start_kopiur') as start, redirect_stdout(io.StringIO()):
            self.migration.restore_all()
            create.assert_not_called(); delete.assert_not_called(); start.assert_not_called()

    def test_flag_rejected_for_destructive_phases_before_bundle_access(self):
        for phase in ('retire', 'ceph-cleanup', 'talos-volume', 'activate', 'smoke'):
            with self.subTest(phase=phase), patch('sys.argv', ['step.py', phase, '--allow-plex', '--execute']), patch.object(step, 'Migration') as migration, patch('sys.stderr', new=io.StringIO()):
                with self.assertRaises(SystemExit): step.main()
                migration.assert_not_called()


class StepTests(unittest.TestCase):
    def test_cleanup_job_checks_labels_node_and_terminal_status(self):
        job = {'metadata': {'name': 'cluster-cleanup-job-phoebe-k-ctrl-01',
                            'labels': {'app': 'rook-ceph-cleanup', 'rook_cluster': 'rook-ceph'}},
               'spec': {'template': {'spec': {'nodeSelector': {'kubernetes.io/hostname': prepare.NODE}}}},
               'status': {'succeeded': 1}}
        self.assertFalse(step.cleanup_jobs_finished([]))
        self.assertFalse(step.cleanup_jobs_finished([job]))
        job['status']['conditions'] = [{'type': 'Complete', 'status': 'True'}]
        self.assertTrue(step.cleanup_jobs_finished([job]))
        for label in ('app', 'rook_cluster'):
            other = copy.deepcopy(job); other['metadata']['labels'][label] = 'unrelated'
            self.assertFalse(step.cleanup_jobs_finished([other]))
        other = copy.deepcopy(job)
        other['spec']['template']['spec']['nodeSelector']['kubernetes.io/hostname'] = 'another-node'
        with self.assertRaisesRegex(RuntimeError, 'unexpected node'): step.cleanup_jobs_finished([other])
        for condition in ('Failed', 'FailureTarget'):
            other = copy.deepcopy(job)
            other['status']['conditions'] = [{'type': condition, 'status': 'True'}]
            with self.assertRaisesRegex(RuntimeError, 'failed'): step.cleanup_jobs_finished([other])

    def test_cleanup_accepts_completed_rook_job_with_cluster_cleanup_name(self):
        job = {'metadata': {'name': 'cluster-cleanup-job-phoebe-k-ctrl-01',
                            'labels': {'app': 'rook-ceph-cleanup', 'rook-ceph-cleanup': 'true', 'rook_cluster': 'rook-ceph'}},
               'spec': {'template': {'spec': {'nodeSelector': {'kubernetes.io/hostname': prepare.NODE}}}},
               'status': {'succeeded': 1, 'conditions': [{'type': 'Complete', 'status': 'True'}]}}
        migration = step.Migration.__new__(step.Migration)
        migration.progress = {'retire': True, 'cleanup-started': True}
        objects = {'node': [{'metadata': {'name': prepare.NODE}}], 'job': [job]}
        def check_poll(description, predicate, *args):
            self.assertTrue(predicate(), description)
        with patch.object(migration, 'frozen'), patch.object(migration, 'done') as done, patch.object(step, 'disk'), patch.object(step, 'no_pending_volume'), patch.object(step, 'one', return_value=None), patch.object(step, 'get', side_effect=lambda kind, ns=None: objects.get(kind, [])), patch.object(step, 'poll', side_effect=check_poll), patch.object(step, 'patch') as mutation, patch.object(step, 'delete') as delete:
            migration.ceph_cleanup()
            done.assert_called_once_with('ceph-cleanup')
            mutation.assert_not_called(); delete.assert_not_called()

    def test_every_preview_avoids_cluster_and_bundle_access(self):
        for phase in step.DESCRIPTIONS:
            with self.subTest(phase=phase), patch('sys.argv', ['step.py', phase]), patch.object(step, 'Migration') as migration, patch.object(step, 'kubectl') as kube, redirect_stdout(io.StringIO()):
                step.main()
                migration.assert_not_called(); kube.assert_not_called()

    def test_delete_has_api_uid_precondition(self):
        obj = {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': 'data', 'namespace': 'apps', 'uid': 'original'}}
        with patch.object(step, 'kubectl') as kube, redirect_stdout(io.StringIO()):
            step.delete(obj, 'persistentvolumeclaims')
        args = kube.call_args
        self.assertEqual(args.args, ('delete', '--raw', '/api/v1/namespaces/apps/persistentvolumeclaims/data', '-f', '-'))
        self.assertEqual(json.loads(args.kwargs['data'])['preconditions'], {'uid': 'original'})

    def test_create_accepts_defaults_but_rejects_different_backup(self):
        obj = {'kind': 'Restore', 'metadata': {'namespace': 'apps', 'name': 'restore'},
               'spec': {'source': {'identity': {'snapshotID': 'pinned'}}, 'list': [{'name': 'x'}]}}
        actual = copy.deepcopy(obj); actual['spec']['list'][0]['default'] = True
        with patch.object(step, 'one', return_value=actual), patch.object(step, 'kubectl') as kube:
            step.create(obj); kube.assert_not_called()
            actual['spec']['source']['identity']['snapshotID'] = 'other'
            with self.assertRaises(RuntimeError): step.create(obj)
            kube.assert_not_called()

    def test_talos_volume_cannot_run_before_cleanup(self):
        migration = step.Migration.__new__(step.Migration); migration.progress = {'retire': True}
        with patch.object(step, 'talos') as talos, patch.object(step, 'disk') as disk:
            with self.assertRaisesRegex(RuntimeError, 'ceph-cleanup'): migration.talos_volume()
            talos.assert_not_called(); disk.assert_not_called()

    def test_miroir_cannot_start_before_talos_volume(self):
        migration = step.Migration.__new__(step.Migration); migration.progress = {'ceph-cleanup': True}
        with patch.object(step, 'apply_file') as apply:
            with self.assertRaisesRegex(RuntimeError, 'talos-volume'): migration.activate()
            apply.assert_not_called()

    def test_pending_talos_volume_blocks_retirement_before_any_delete(self):
        migration = step.Migration.__new__(step.Migration); migration.progress = {'git': True}
        pending = {'metadata': {'id': 'r-miroir'}}
        with patch.object(migration, 'frozen'), patch.object(step, 'disk'), patch.object(step, 'talos', return_value=json.dumps(pending)), patch.object(step, 'delete') as delete:
            with self.assertRaisesRegex(RuntimeError, 'pending Miroir'): migration.retire()
            delete.assert_not_called()

    def test_disk_selection_rejects_os_disk(self):
        disk = {'metadata': {'id': 'nvme0n1'}, 'spec': {'serial': prepare.SERIAL, 'size': 1000204886016, 'dev_path': '/dev/nvme0n1'}}
        volume = {'metadata': {'id': 'STATE'}, 'spec': {'location': '/dev/nvme0n1p3'}}
        with patch.object(step, 'talos', side_effect=[json.dumps(disk), json.dumps(volume)]):
            with self.assertRaisesRegex(RuntimeError, 'system volume'): step.disk()

    def test_disk_selection_uses_serial_and_parses_talos_stream(self):
        disk = {'metadata': {'id': 'nvme7n1'}, 'spec': {'serial': prepare.SERIAL, 'size': 1000204886016, 'dev_path': '/dev/nvme7n1'}}
        other = {'spec': {'serial': 'OS-DISK'}}
        with patch.object(step, 'talos', side_effect=[json.dumps(other)+'\n'+json.dumps(disk), '']):
            self.assertEqual(step.disk()['spec']['dev_path'], '/dev/nvme7n1')

    def test_completed_cleanup_cannot_be_run_again(self):
        migration = step.Migration.__new__(step.Migration)
        migration.progress = {'retire': True, 'ceph-cleanup': True}
        with patch.object(migration, 'frozen'), patch.object(step, 'disk'), patch.object(step, 'get') as get:
            with self.assertRaisesRegex(RuntimeError, 'already completed'): migration.ceph_cleanup()
            get.assert_not_called()


if __name__ == '__main__':
    unittest.main()
