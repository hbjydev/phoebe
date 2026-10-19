#!/usr/bin/env python3
"""Review/apply five storage-class corrections before resuming operators."""
import argparse
import fcntl
import json
import subprocess
import sys
from contextlib import contextmanager, nullcontext

from prepare import ROOT, DEFAULT_BUNDLE, get, kubectl, require
from repair_controllers import atomic_json, frozen, guarded_patch, selected_pods
from step import one, poll

OPERATOR = 'victoria-metrics-operator'
WEBHOOK_STATE = DEFAULT_BUNDLE / 'operator-webhook.json'
# Complete registry in the installed v0.75.0 release (internal/manager/manager.go).
CONTROLLERS = '''VMCluster VMAgent VMAnomaly VMAnomalyConfig VMAuth VMSingle
VLAgent VLogs VLSingle VLCluster VTSingle VTAgent VTCluster VMAlertmanager VMAlert
VMUser VMRule VMAlertmanagerConfig VMServiceScrape VMPodScrape VMProbe VMNodeScrape
VMStaticScrape VMScrapeConfig VMDistributed VLDistributed PodMonitor ServiceMonitor
ScrapeConfig AlertmanagerConfig Probe PrometheusRule'''.split()
DISABLE = '--controller.disableReconcileFor=' + ','.join(CONTROLLERS)


def operator_state():
    return one('deployment', OPERATOR, 'observability')


def container(obj):
    containers = obj['spec']['template']['spec']['containers']
    require(len(containers) == 1 and containers[0]['name'] == 'operator', 'Unexpected operator containers')
    require(containers[0]['image'] == 'victoriametrics/operator:v0.75.0', 'Recheck controller flags for this operator version')
    return containers[0]


def check_temporary_mode(obj, saved):
    require(obj['metadata']['uid'] == saved['uid'], 'Webhook operator was replaced')
    args = container(obj)['args']
    require(args in (saved['args'], saved['args'] + [DISABLE]), 'Operator arguments changed outside this repair')
    require(obj['spec']['replicas'] in (0, 1), 'Unexpected webhook operator replica count')
    require(obj['spec']['replicas'] == 0 or args == saved['args'] + [DISABLE],
            'Operator is running with reconciliation enabled; stop for review')


def start_webhook():
    obj = operator_state()
    if not WEBHOOK_STATE.exists():
        args = container(obj)['args']
        require(obj['spec']['replicas'] == 0 and not selected_pods(obj), 'Operator must initially be stopped')
        require('--webhook.enable=true' in args and not any('disableReconcileFor' in a for a in args),
                'Unexpected webhook/reconciliation arguments')
        atomic_json(WEBHOOK_STATE, {'uid': obj['metadata']['uid'], 'args': args})
    saved = json.loads(WEBHOOK_STATE.read_text())
    check_temporary_mode(obj, saved)
    # Also handles a retry after an interrupted temporary start.
    guarded_patch(obj, [{'op': 'replace', 'path': '/spec/replicas', 'value': 0}])
    poll('temporary operator Pods removed', lambda: not selected_pods(obj))
    obj = operator_state()
    check_temporary_mode(obj, saved)
    guarded_patch(obj, [
        {'op': 'replace', 'path': '/spec/template/spec/containers/0/args', 'value': saved['args'] + [DISABLE]},
        {'op': 'replace', 'path': '/spec/replicas', 'value': 1},
    ])
    print(kubectl('rollout', 'status', f'deployment/{OPERATOR}', '-n', 'observability', '--timeout=300s'))

    def endpoint_ready():
        live = operator_state()
        check_temporary_mode(live, saved)
        pods = {p['metadata']['uid'] for p in selected_pods(live)}
        return any(e.get('conditions', {}).get('ready') is True
                   and e.get('targetRef', {}).get('uid') in pods
                   for s in get('endpointslices.discovery.k8s.io', 'observability')
                   if s['metadata'].get('labels', {}).get('kubernetes.io/service-name') == OPERATOR
                   for e in s.get('endpoints', []))
    poll('VictoriaMetrics webhook endpoint ready', endpoint_ready, seconds=300)


def stop_webhook():
    if not WEBHOOK_STATE.exists():
        return
    saved = json.loads(WEBHOOK_STATE.read_text())
    obj = operator_state()
    check_temporary_mode(obj, saved)
    guarded_patch(obj, [{'op': 'replace', 'path': '/spec/replicas', 'value': 0}])
    poll('temporary webhook Pods removed', lambda: not selected_pods(obj))
    obj = operator_state()
    check_temporary_mode(obj, saved)
    guarded_patch(obj, [{'op': 'replace', 'path': '/spec/template/spec/containers/0/args', 'value': saved['args']}])
    current = operator_state()
    require(current['metadata']['uid'] == saved['uid'] and current['spec']['replicas'] == 0
            and container(current)['args'] == saved['args'], 'Temporary operator configuration was not restored')
    WEBHOOK_STATE.unlink()


@contextmanager
def webhook_available():
    try:
        start_webhook()
        yield
    finally:
        stop_webhook()

TARGETS = (
    ('grafanas.grafana.integreatly.org', 'grafana', '/spec/persistentVolumeClaim/spec/storageClassName'),
    ('vlsingles.operator.victoriametrics.com', 'victoria-logs', '/spec/storage/storageClassName'),
    ('vmsingles.operator.victoriametrics.com', 'victoria-metrics', '/spec/storage/storageClassName'),
    ('vtsingles.operator.victoriametrics.com', 'victoria-traces', '/spec/storage/storageClassName'),
    ('vlagents.operator.victoriametrics.com', 'logs-agent', '/spec/storage/volumeClaimTemplate/spec/storageClassName'),
)


def correction(obj, path):
    value = obj
    for part in path.strip('/').split('/'):
        value = value[part]
    require(value in ('ceph-block', 'miroir-local'), f'Unexpected storage class: {value}')
    if value == 'miroir-local':
        return []
    return [
        {'op': 'test', 'path': '/metadata/uid', 'value': obj['metadata']['uid']},
        {'op': 'test', 'path': '/metadata/resourceVersion', 'value': obj['metadata']['resourceVersion']},
        {'op': 'test', 'path': path, 'value': 'ceph-block'},
        {'op': 'replace', 'path': path, 'value': 'miroir-local'},
    ]


def operators_stopped():
    state = json.loads((ROOT / 'kubernetes/.maintenance-state.json').read_text())
    require(state['stages'] == ['postgres'], 'Expected only the postgres maintenance stage remaining')
    frozen()
    for name in ('grafana-operator', 'victoria-metrics-operator'):
        obj = one('deployment', name, 'observability')
        saved = state['guards'][f'Deployment/observability/{name}']
        require(obj and obj['metadata']['uid'] == saved['uid'], f'Operator replaced: {name}')
        if name == OPERATOR and WEBHOOK_STATE.exists():
            check_temporary_mode(obj, json.loads(WEBHOOK_STATE.read_text()))
        else:
            require(obj['spec'].get('replicas') == 0 and not selected_pods(obj), f'Operator must remain stopped: {name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    with (ROOT / 'kubernetes/.maintenance-state.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        operators_stopped()
        changes = []
        # Validate the entire list before allowing any patch.
        for kind, name, path in TARGETS:
            obj = one(kind, name, 'observability')
            require(obj and not obj['metadata'].get('deletionTimestamp'), f'Parent missing/deleting: {name}')
            operations = correction(obj, path)
            print(f'{kind}/{name}: {path}: ' + ('ceph-block -> miroir-local' if operations else 'already miroir-local'))
            if operations:
                changes.append((kind, name, path, obj['metadata']['uid'], operations))
        if not args.execute:
            print('Preview only. Execution temporarily starts the VictoriaMetrics webhook with ALL reconciliation '
                  'controllers disabled, validates and patches the fields, then stops it and restores its arguments. '
                  'Grafana and Flux stay stopped; webhook admission remains enabled.')
            return
        if not changes and not WEBHOOK_STATE.exists():
            print('All five parent resources already use Miroir.')
            return
        require(input("Type 'repair-storage' to continue: ") == 'repair-storage', 'Confirmation did not match')
        operators_stopped()
        needs_webhook = WEBHOOK_STATE.exists() or any('victoriametrics.com' in k for k, *_ in changes)
        with webhook_available() if needs_webhook else nullcontext():
            # Validate every correction through admission before applying any.
            # Refresh versions after startup, while retaining the pinned UIDs.
            for dry_run in (True, False):
                for kind, name, path, original_uid, _ in changes:
                    obj = one(kind, name, 'observability')
                    require(obj and obj['metadata']['uid'] == original_uid, f'Parent was replaced: {name}')
                    operations = correction(obj, path)
                    if not operations:
                        continue
                    print(kubectl('patch', kind, name, '-n', 'observability', '--type=json',
                                  '-p', json.dumps(operations), *(['--dry-run=server'] if dry_run else [])))
                    if not dry_run:
                        current = one(kind, name, 'observability')
                        require(current and current['metadata']['uid'] == original_uid and not correction(current, path),
                                f'Correction not observed: {name}')
        print('Parent storage settings corrected. Temporary webhook stopped; original arguments restored. '
              'Operators and Flux remain held for the final restore-postgres step.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError, KeyError) as error:
        print('STOP:', str(error) or repr(error), file=sys.stderr)
        print('After resolving the error, rerun this script; it skips fields already set to miroir-local. '
              'If operator-webhook.json remains in the migration bundle, do not run restore-postgres '
              'until this script has completed cleanup.', file=sys.stderr)
        sys.exit(1)
