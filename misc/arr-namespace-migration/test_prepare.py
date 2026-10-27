import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import prepare


class CaptureTests(unittest.TestCase):
    def test_prowlarr_capture_has_config_without_a_cover_cache(self):
        image = 'ghcr.io/home-operations/prowlarr'
        tag = '2.6.5.5623@sha256:0e2e6e9a2a16683a160ff1c6830d8192231a0502ab0d605b416023b2ca225ff9'

        def get(kind, name, namespace):
            if namespace == 'downloads':
                return None
            obj = {'apiVersion': 'test/v1', 'kind': kind,
                   'metadata': {'name': name, 'namespace': namespace, 'uid': name}, 'spec': {}}
            if kind == 'deploy':
                obj['spec'] = {'replicas': 1, 'template': {'spec': {
                    'containers': [{'name': 'app', 'image': image + ':' + tag}]}}}
                obj['status'] = {'availableReplicas': 1}
            elif kind == 'helmrelease':
                obj['spec'] = {'values': {'controllers': {'prowlarr': {'containers': {
                    'app': {'image': {'repository': image, 'tag': tag}}}}}}}
            elif kind == 'pvc':
                self.assertEqual(name, 'prowlarr', 'Prowlarr has no cover-cache claim')
                obj['spec'] = {'storageClassName': 'miroir-local'}
                obj['status'] = {'phase': 'Bound'}
            return obj

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(prepare, 'APPS', ('prowlarr',)), patch.object(prepare, 'get', side_effect=get):
            bundle = Path(directory) / 'bundle'
            prepare.capture(bundle)
            inventory = json.loads((bundle / 'inventory.json').read_text())
            self.assertEqual(set(inventory['prowlarr']['claims']), {'prowlarr'})
            secret = json.loads((bundle / 'new/externalsecret-prowlarr-postgres.json').read_text())
            self.assertEqual(secret['metadata']['namespace'], 'downloads')

    def test_three_app_bundle_is_rejected_before_cluster_access(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(prepare, 'get') as get:
            bundle = Path(directory)
            (bundle / 'inventory.json').write_text(json.dumps(dict.fromkeys(('radarr', 'sonarr', 'lidarr'), {})))
            with self.assertRaisesRegex(RuntimeError, 'all four apps'):
                prepare.restores(bundle, 'move-1')
            get.assert_not_called()


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {'status': {
            'phase': 'Succeeded', 'stats': {},
            'resolved': {
                'sources': [{'pvc': 'default/radarr', 'sourcePath': '/pvc/radarr'}],
                'repository': {'kind': 'ClusterRepository', 'name': 'hetzner'}},
            'snapshot': {'kopiaSnapshotID': 'exact-backup-id', 'identity': {
                'username': 'default-radarr', 'hostname': 'default', 'sourcePath': '/pvc/radarr'}}}}
        self.pvc = {'spec': {'accessModes': ['ReadWriteOnce'],
                             'resources': {'requests': {'storage': '10Gi'}}}}

    def test_restore_preserves_source_identity_in_destination_namespace(self):
        result = prepare.restore_objects(self.snapshot, self.pvc, 'radarr', 'move-1')
        restore, claim, binder = result['items']
        self.assertEqual(restore['spec']['source']['identity']['hostname'], 'default')
        self.assertEqual(restore['spec']['source']['identity']['snapshotID'], 'exact-backup-id')
        self.assertEqual({x['metadata']['namespace'] for x in result['items']}, {'downloads'})
        self.assertEqual(claim['spec']['dataSourceRef']['name'], restore['metadata']['name'])
        self.assertEqual(restore['spec']['policy']['onMissingSnapshot'], 'Fail')
        self.assertFalse(restore['spec']['options']['ignorePermissionErrors'])
        self.assertTrue(binder['spec']['volumes'][0]['persistentVolumeClaim']['readOnly'])

    def test_rejects_incomplete_wrong_or_lossy_backup(self):
        for mutate in (
            lambda s: s['status'].update(phase='Running'),
            lambda s: s['status']['stats'].update(filesFailed=1),
            lambda s: s['status']['snapshot'].pop('kopiaSnapshotID'),
            lambda s: s['status']['resolved'].update(sources=[{'pvc': 'default/sonarr'}]),
            lambda s: s['status']['resolved']['repository'].update(name='other'),
        ):
            snapshot = copy.deepcopy(self.snapshot)
            mutate(snapshot)
            with self.assertRaises(RuntimeError):
                prepare.restore_objects(snapshot, self.pvc, 'radarr', 'move-1')

    def test_waits_for_pinning_before_selecting_snapshot_id(self):
        self.snapshot['spec'] = {'pin': True}
        with self.assertRaisesRegex(RuntimeError, 'pinning'):
            prepare.restore_objects(self.snapshot, self.pvc, 'radarr', 'move-1')
        self.snapshot['status']['conditions'] = [{'type': 'Pinned', 'status': 'True'}]
        result = prepare.restore_objects(self.snapshot, self.pvc, 'radarr', 'move-1')
        self.assertEqual(result['items'][0]['spec']['source']['identity']['snapshotID'], 'exact-backup-id')


class CredentialTests(unittest.TestCase):
    def objects(self, acknowledged='current', source='downloads', password='same'):
        return [
            {'data': {'password': 'same'}},
            {'data': {'password': password}, 'metadata': {
                'resourceVersion': 'current', 'annotations': {
                    'reflector.v1.k8s.emberstack.com/reflects': f'{source}/radarr-postgres'}}},
            {'status': {'applied': True, 'secretResourceVersion': acknowledged}},
        ]

    def test_stale_applied_true_does_not_pass_password_gate(self):
        with patch.object(prepare, 'get', side_effect=self.objects(acknowledged='old')):
            with self.assertRaisesRegex(RuntimeError, 'not acknowledged'):
                prepare.credentials('downloads')

    def test_wrong_reflector_source_is_rejected(self):
        with patch.object(prepare, 'get', side_effect=self.objects(source='default')):
            with self.assertRaisesRegex(RuntimeError, 'wrong namespace'):
                prepare.credentials('downloads')

    def test_mismatched_password_is_rejected_without_disclosing_it(self):
        with patch.object(prepare, 'get', side_effect=self.objects(password='different')):
            with self.assertRaisesRegex(RuntimeError, '^radarr: database mirror differs$'):
                prepare.credentials('downloads')


if __name__ == '__main__':
    unittest.main()
