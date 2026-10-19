"""Offline checks for the destructive controller boundary and local UID adoption."""
import copy
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import repair_controllers as repair


def statefulset():
    return {
        'apiVersion': 'apps/v1', 'kind': 'StatefulSet',
        'metadata': {'name': 'slskd', 'namespace': 'downloads', 'uid': 'old',
                     'resourceVersion': '10', 'generation': 2,
                     'labels': {'app.kubernetes.io/managed-by': 'Helm'},
                     'annotations': {'meta.helm.sh/release-name': 'slskd'},
                     'ownerReferences': [{'uid': 'parent', 'kind': 'Example'}]},
        'spec': {'replicas': 1, 'selector': {'matchLabels': {'app': 'slskd'}},
                 'template': {'metadata': {'labels': {'app': 'slskd'}}, 'spec': {'containers': []}},
                 'persistentVolumeClaimRetentionPolicy': {'whenDeleted': 'Retain', 'whenScaled': 'Retain'},
                 'volumeClaimTemplates': [{'metadata': {'name': 'config', 'creationTimestamp': None},
                                          'spec': {'storageClassName': 'ceph-block'},
                                          'status': {'phase': 'Pending'}}]},
        'status': {'readyReplicas': 1},
    }


class RepairTests(unittest.TestCase):
    def test_replacement_preserves_helm_parent_and_pod_configuration(self):
        old = statefulset()
        new = repair.replacement(old, 'token')
        self.assertEqual(new['metadata']['ownerReferences'], old['metadata']['ownerReferences'])
        self.assertEqual(new['metadata']['labels'], old['metadata']['labels'])
        self.assertEqual(new['metadata']['annotations']['meta.helm.sh/release-name'], 'slskd')
        self.assertNotIn('uid', new['metadata'])
        self.assertNotIn('status', new)
        template = new['spec']['volumeClaimTemplates'][0]
        self.assertNotIn('status', template)
        self.assertNotIn('creationTimestamp', template['metadata'])
        self.assertEqual(template['spec']['storageClassName'], 'miroir-local')
        self.assertEqual(new['spec']['template'], old['spec']['template'])
        self.assertEqual(old['spec']['volumeClaimTemplates'][0]['spec']['storageClassName'], 'ceph-block')

    def test_delete_retention_and_unexpected_topology_rejected(self):
        for field in ('whenDeleted', 'whenScaled', 'replicas', 'ordinal'):
            obj = statefulset()
            if field in ('whenDeleted', 'whenScaled'):
                obj['spec']['persistentVolumeClaimRetentionPolicy'][field] = 'Delete'
            elif field == 'replicas':
                obj['spec']['replicas'] = 2
            else:
                obj['spec']['ordinals'] = {'start': 1}
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                repair.replacement(obj, 'token')

    def test_uid_adoption_preserves_all_other_maintenance_fields(self):
        state = {'stages': ['postgres', 'ceph'], 'guards': {'example': {'original': 1}},
                 'resources': {'target': {'uid': 'old', 'stages': ['ceph'], 'original': None}}}
        result = repair.update_uid(state, 'target', 'old', 'new')
        expected = copy.deepcopy(state)
        expected['resources']['target']['uid'] = 'new'
        self.assertEqual(result, expected)
        self.assertEqual(state['resources']['target']['uid'], 'old')
        self.assertEqual(repair.update_uid(result, 'target', 'old', 'new'), result)
        with self.assertRaises(RuntimeError):
            repair.update_uid(result, 'target', 'old', 'unrelated')

    def test_preview_does_not_read_or_write_cluster(self):
        with patch('sys.argv', ['repair_controllers.py', 'kanidm']), patch.object(repair, 'kubectl') as kube, \
                patch.object(repair, 'one') as read, redirect_stdout(io.StringIO()):
            repair.main()
        kube.assert_not_called()
        read.assert_not_called()

    def test_changed_pvc_identity_is_rejected(self):
        pvc = {'metadata': {'uid': 'new'}, 'spec': {'storageClassName': 'miroir-local', 'volumeName': 'pv'},
               'status': {'phase': 'Bound'}}
        with patch.object(repair, 'one', return_value=pvc), self.assertRaisesRegex(RuntimeError, 'identity/binding'):
            repair.checked_claim('ns', 'pvc', {'uid': 'original', 'volume': 'pv'})

    def test_backup_from_another_cluster_is_rejected(self):
        pg = {'metadata': {'uid': 'current'}, 'spec': {'storage': {'storageClass': 'miroir-local'}, 'instances': 2,
              'plugins': [{'name': 'barman-cloud.cloudnative-pg.io', 'isWALArchiver': True,
                           'parameters': {'serverName': 'postgres-miroir'}}]}, 'status': {'readyInstances': 2}}
        backup = {'metadata': {'uid': 'backup'}, 'status': {'phase': 'completed', 'backupId': 'id',
                                                          'pluginMetadata': {'clusterUID': 'old'}}}
        with patch.object(repair, 'one', side_effect=[pg, backup]), self.assertRaisesRegex(RuntimeError, 'current PostgreSQL'):
            repair.backup_checkpoint()

    def test_only_controller_is_orphan_deleted_and_retry_does_not_recreate(self):
        for retry in (False, True):
            with self.subTest(retry=retry), tempfile.TemporaryDirectory() as tmp:
                bundle = Path(tmp)
                old = statefulset()
                desired = repair.replacement(old, 'token')
                new = copy.deepcopy(desired)
                new['metadata'].update(uid='new', generation=1)
                (bundle / 'slskd.before.json').write_text(json.dumps(repair.manifest(old)))
                (bundle / 'slskd.json').write_text(json.dumps(desired))
                state = bundle / 'state.json'
                state.write_text(json.dumps({'resources': {'StatefulSet/downloads/slskd': {'uid': 'old'}}}))
                plan = {'token': 'token', 'postgres': {}, 'targets': {'slskd': {'oldUID': 'old', 'claim': {}}}}
                current = new if retry else old
                reads = [current, current] if retry else [old, old, new]
                with patch.object(repair, 'BUNDLE', bundle), patch.object(repair, 'STATE', state), \
                        patch.object(repair, 'one', side_effect=reads), patch.object(repair, 'frozen'), \
                        patch.object(repair, 'backup_checkpoint'), patch.object(repair, 'checked_claim'), \
                        patch.object(repair, 'poll'), patch.object(repair, 'adopt') as adopt, \
                        patch.object(repair, 'delete') as delete, patch.object(repair, 'kubectl') as kube, \
                        redirect_stdout(io.StringIO()):
                    repair.repair('slskd', plan)
                if retry:
                    delete.assert_not_called()
                    kube.assert_not_called()
                else:
                    delete.assert_called_once_with(old, 'statefulsets', orphan=True)
                    kube.assert_called_once_with('create', '-f', '-', data=json.dumps(desired))
                adopt.assert_called_once_with('StatefulSet/downloads/slskd', 'old', 'new')

    def test_foreign_replacement_is_not_deleted_or_adopted(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp)
            old = statefulset()
            desired = repair.replacement(old, 'token')
            (bundle / 'slskd.before.json').write_text(json.dumps(repair.manifest(old)))
            (bundle / 'slskd.json').write_text(json.dumps(desired))
            foreign = copy.deepcopy(old)
            foreign['metadata']['uid'] = 'foreign'
            plan = {'token': 'token', 'postgres': {}, 'targets': {'slskd': {'oldUID': 'old', 'claim': {}}}}
            with patch.object(repair, 'BUNDLE', bundle), patch.object(repair, 'one', return_value=foreign), \
                    patch.object(repair, 'frozen'), patch.object(repair, 'backup_checkpoint'), \
                    patch.object(repair, 'checked_claim'), patch.object(repair, 'delete') as delete, \
                    patch.object(repair, 'adopt') as adopt, self.assertRaisesRegex(RuntimeError, 'unrecognized'):
                repair.repair('slskd', plan)
            delete.assert_not_called()
            adopt.assert_not_called()


if __name__ == '__main__':
    unittest.main()
