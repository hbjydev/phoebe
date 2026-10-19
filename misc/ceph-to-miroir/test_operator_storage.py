"""Checks for narrowly scoped, retryable parent-resource corrections."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import repair_operator_storage as repair
from repair_operator_storage import correction


class OperatorStorageTests(unittest.TestCase):
    def test_main_brings_up_webhook_before_validating_or_patching_vm_resources(self):
        objects = {}
        for kind, name, path in repair.TARGETS:
            obj = {'metadata': {'uid': name, 'resourceVersion': '1'}}
            leaf = obj
            parts = path.strip('/').split('/')
            for key in parts[:-1]:
                leaf = leaf.setdefault(key, {})
            leaf[parts[-1]] = 'miroir-local' if name == 'grafana' else 'ceph-block'
            objects[name] = obj
        events = []
        online = False

        def start():
            nonlocal online
            online = True
            events.append('start')

        def stop():
            nonlocal online
            online = False
            events.append('stop')

        def kubectl(*args):
            self.assertTrue(online, 'failed calling webhook: no endpoints available for service')
            events.append('validate' if '--dry-run=server' in args else 'patch')
            if '--dry-run=server' not in args:
                operation = json.loads(args[args.index('-p') + 1])[-1]
                leaf = objects[args[2]]
                parts = operation['path'].strip('/').split('/')
                for part in parts[:-1]:
                    leaf = leaf[part]
                leaf[parts[-1]] = operation['value']
            return 'ok'

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'kubernetes').mkdir()
            with patch.object(repair, 'ROOT', Path(tmp)), \
                    patch.object(repair, 'WEBHOOK_STATE', Path(tmp) / 'webhook.json'), \
                    patch.object(repair, 'operators_stopped'), \
                    patch.object(repair, 'one', side_effect=lambda kind, name, ns: copy.deepcopy(objects[name])), \
                    patch.object(repair, 'start_webhook', side_effect=start), \
                    patch.object(repair, 'stop_webhook', side_effect=stop), \
                    patch.object(repair, 'kubectl', side_effect=kubectl), \
                    patch('builtins.input', return_value='repair-storage'), \
                    patch('sys.argv', ['repair_operator_storage.py', '--execute']), redirect_stdout(io.StringIO()):
                repair.main()
        self.assertEqual(events, ['start'] + ['validate'] * 4 + ['patch'] * 4 + ['stop'])

    def test_temporary_mode_rejects_a_normally_running_operator(self):
        saved = {'uid': 'operator', 'args': ['--webhook.enable=true']}
        obj = {'metadata': {'uid': 'operator'}, 'spec': {'replicas': 1, 'template': {'spec': {
            'containers': [{'name': 'operator', 'image': 'victoriametrics/operator:v0.75.0', 'args': saved['args']}]
        }}}}
        with self.assertRaisesRegex(RuntimeError, 'reconciliation enabled'):
            repair.check_temporary_mode(obj, saved)
        obj['spec']['template']['spec']['containers'][0]['args'] = saved['args'] + [repair.DISABLE]
        repair.check_temporary_mode(obj, saved)

    def test_webhook_is_started_before_patch_and_stopped_after_failure(self):
        events = []
        with patch.object(repair, 'start_webhook', create=True, side_effect=lambda: events.append('start')), \
                patch.object(repair, 'stop_webhook', create=True, side_effect=lambda: events.append('stop')):
            with self.assertRaisesRegex(RuntimeError, 'patch rejected'):
                with repair.webhook_available():
                    events.append('patch')
                    raise RuntimeError('patch rejected')
        self.assertEqual(events, ['start', 'patch', 'stop'])

    def test_patch_guards_identity_and_changes_only_the_storage_class(self):
        obj = {'metadata': {'uid': 'uid', 'resourceVersion': '42'},
               'spec': {'storage': {'storageClassName': 'ceph-block', 'resources': {'requests': {'storage': '50Gi'}}}}}
        before = copy.deepcopy(obj)
        path = '/spec/storage/storageClassName'
        patch = correction(obj, path)
        self.assertEqual(patch[:3], [
            {'op': 'test', 'path': '/metadata/uid', 'value': 'uid'},
            {'op': 'test', 'path': '/metadata/resourceVersion', 'value': '42'},
            {'op': 'test', 'path': path, 'value': 'ceph-block'},
        ])
        self.assertEqual(patch[3:], [{'op': 'replace', 'path': path, 'value': 'miroir-local'}])
        self.assertEqual(obj, before)

    def test_retry_skips_corrected_fields_and_rejects_unexpected_class(self):
        obj = {'spec': {'persistentVolumeClaim': {'spec': {'storageClassName': 'miroir-local'}}}}
        path = '/spec/persistentVolumeClaim/spec/storageClassName'
        self.assertEqual(correction(obj, path), [])
        obj['spec']['persistentVolumeClaim']['spec']['storageClassName'] = 'other'
        with self.assertRaisesRegex(RuntimeError, 'Unexpected storage class'):
            correction(obj, path)
