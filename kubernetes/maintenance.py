"""Discover, quiesce, and restore Phoebe's persistent-storage consumers."""

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


STATE = Path(__file__).with_name(".maintenance-state.json")
TIMEOUT = 600
SNAPSHOT_TIMEOUT = 3600
RESOURCES = (
    "deployment,statefulset,daemonset,cronjob,job,pod,pvc,pv,storageclass,"
    "cluster.postgresql.cnpg.io,dragonfly,scheduledbackup,backup.postgresql.cnpg.io,hpa,node,"
    "snapshotpolicy,snapshotschedule,volumesnapshotclass,"
    "garageclusters.v1beta2.garage.rajsingh.info,garagenodes.garage.rajsingh.info"
)
FLUX = (
    ("flux-system", "flux-operator"),
    ("flux-system", "kustomize-controller"),
    ("flux-system", "helm-controller"),
)
# Operators observed in the cluster. Unknown owners abort planning rather than
# assuming that a scaled workload will stay down.
OPERATORS = {
    "LiteLLMProxy": ("ai", "litellm-operator"),
    "InferenceService": ("ai", "llmkube-controller-manager"),
    "Kanidm": ("security", "kaniop"),
    "Grafana": ("observability", "grafana-operator"),
    "VMSingle": ("observability", "victoria-metrics-operator"),
    "VLSingle": ("observability", "victoria-metrics-operator"),
    "VTSingle": ("observability", "victoria-metrics-operator"),
    "VMAgent": ("observability", "victoria-metrics-operator"),
    "VLAgent": ("observability", "victoria-metrics-operator"),
    "OpenTelemetryCollector": ("observability", "opentelemetry-operator"),
}
# LiveKit's Redis configuration is in a Secret, not its Pod labels/env.
EXTRA_DRAGONFLY = {("matrix", "livekit"), ("matrix", "livekit-jwt-service")}
CEPH_WRITERS = {
    ("observability", "vmagent-metrics-agent"),
    ("observability", "vlagent-logs-agent"),
    ("observability", "otel-collector-collector"),
}
# The live IfNotPresent policy predates the root mover configuration already
# specified in default/home-assistant/ks.yaml. Pin that intended context on the
# maintenance invocation; the writer Pods are gone when Kopiur starts its run.
MAINTENANCE_MOVERS = {
    ("default", "home-assistant"): {
        "privilegedMode": True,
        "podSecurityContext": {"fsGroup": 0},
        "securityContext": {"runAsUser": 0, "runAsGroup": 0,
                            "runAsNonRoot": False, "privileged": True},
    },
}


def kubectl(*args, capture=True, manifest=None):
    timeout = "0" if args[0] in ("wait", "rollout") else "30s"
    result = subprocess.run(
        ["kubectl", f"--request-timeout={timeout}", *args],
        check=True, text=True, stdout=subprocess.PIPE if capture else None,
        input=json.dumps(manifest) if manifest is not None else None,
    )
    return result.stdout.strip() if capture else None


def inventory():
    return json.loads(kubectl("get", RESOURCES, "-A", "-o", "json"))["items"]


def key(obj):
    m = obj["metadata"]
    return f"{obj['kind']}/{m.get('namespace', '')}/{m['name']}"


def identity(obj):
    m = obj["metadata"]
    return m.get("namespace", ""), m["name"]


def pod_template(obj):
    spec = obj["spec"]
    if obj["kind"] == "Pod":
        return obj
    if obj["kind"] == "CronJob":
        spec = spec["jobTemplate"]["spec"]
    return spec.get("template", {})


def ceph_claims(items):
    classes = {
        i["metadata"]["name"] for i in items
        if i["kind"] == "StorageClass" and "ceph" in i.get("provisioner", "")
    }
    if any(i["kind"] == "StorageClass" and i["metadata"]["name"] in classes
           and i["metadata"].get("annotations", {}).get(
               "storageclass.kubernetes.io/is-default-class") == "true" for i in items):
        classes.add(None)
    volumes = {
        i["metadata"]["name"] for i in items
        if i["kind"] == "PersistentVolume"
        and "ceph" in i["spec"].get("csi", {}).get("driver", "")
    }
    claims = {
        identity(i) for i in items if i["kind"] == "PersistentVolumeClaim"
        and (i["spec"].get("storageClassName") in classes
             or i["spec"].get("volumeName") in volumes)
    }
    return classes, claims


def dependencies(obj, classes, claims):
    ns, name = identity(obj)
    template = pod_template(obj)
    labels = template.get("metadata", {}).get("labels", {})
    spec = template.get("spec", {})
    # References catch missing labels without reading Secret values.
    config = json.dumps(spec).lower()
    postgres = labels.get("db.policy.home.arpa/postgres") == "allow" or (
        labels.get("cnpg.io/podRole") not in ("instance", "pooler")
        and "postgres" in config
    )
    dragonfly = any(
        k.startswith("db.policy.home.arpa/df-") and v == "allow"
        for k, v in labels.items()
    ) or "dragonfly.database.svc" in config or (ns, name) in EXTRA_DRAGONFLY
    # Standalone Pods of explicit supplemental workloads have generated names.
    dragonfly |= obj["kind"] == "Pod" and ns == "matrix" and any(
        name.startswith(n + "-") for _, n in EXTRA_DRAGONFLY
    )
    ceph = any(
        (ns, v.get("persistentVolumeClaim", {}).get("claimName")) in claims
        for v in spec.get("volumes", [])
    ) or any(
        v["spec"].get("storageClassName") in classes
        for v in obj["spec"].get("volumeClaimTemplates", [])
    )
    return {g for g, found in (
        ("postgres", postgres), ("dragonfly", dragonfly), ("ceph", ceph)
    ) if found}


def record(obj, field, original):
    return {
        "kind": obj["kind"], "namespace": obj["metadata"].get("namespace", ""),
        "name": obj["metadata"]["name"], "uid": obj["metadata"]["uid"],
        "field": field, "original": original, "stages": [],
    }


def plan(items, stage):
    classes, claims = ceph_claims(items)
    targets, guards = {}, {}
    deployments = {identity(i): i for i in items if i["kind"] == "Deployment"}
    if any(i["kind"] == "Node" and i["metadata"].get("labels", {}).get(
        "maintenance.home.arpa/disabled") == "true" for i in items):
        raise RuntimeError("A node matches the maintenance DaemonSet selector")

    def guard(location):
        if location not in deployments:
            raise RuntimeError(f"Required reconciliation controller is missing: {location}")
        obj = deployments[location]
        guards[key(obj)] = record(obj, "replicas", obj["spec"].get("replicas", 1))

    for location in FLUX:
        guard(location)
    for obj in items:
        kind = obj["kind"]
        ns, name = identity(obj)
        if kind not in ("Deployment", "StatefulSet", "DaemonSet", "CronJob"):
            continue
        deps = dependencies(obj, classes, claims)
        selected = stage in deps
        if stage == "ceph":
            selected |= "postgres" in deps or (ns, name) in CEPH_WRITERS
            selected |= ns == "kopiur-system"
        if not selected or ns == "rook-ceph":
            continue
        for owner in obj["metadata"].get("ownerReferences", []):
            if owner["kind"] == "GarageNode":
                # The operator also serves fail-closed PVC admission webhooks.
                # Keep it running; suspend the parent before stopping writers.
                node = next((i for i in items if i["kind"] == "GarageNode"
                             and identity(i) == (ns, owner["name"])), None)
                if node is None:
                    raise RuntimeError(f"Missing GarageNode owner for {key(obj)}")
                ref = node["spec"]["clusterRef"]
                cluster = next((i for i in items if i["kind"] == "GarageCluster"
                                and identity(i) == (ref.get("namespace") or ns, ref["name"])), None)
                if cluster is None:
                    raise RuntimeError(f"Missing GarageCluster for {key(node)}")
                guards[key(cluster)] = record(cluster, "maintenance", cluster["spec"].get("maintenance"))
                continue
            if owner["kind"] not in OPERATORS:
                raise RuntimeError(f"Unknown owner {owner['kind']} for {key(obj)}")
            guard(OPERATORS[owner["kind"]])
        if kind == "DaemonSet":
            action = record(obj, "nodeSelector", pod_template(obj)["spec"].get("nodeSelector"))
        elif kind == "CronJob":
            action = record(obj, "suspend", obj["spec"].get("suspend"))
        else:
            action = record(obj, "replicas", obj["spec"].get("replicas", 1))
        targets[key(obj)] = action
    if stage == "ceph":
        for obj in items:
            if obj["kind"] == "Cluster" and (
                obj["spec"].get("storage", {}).get("storageClass") in classes
                or any(ns == identity(obj)[0] and name.startswith(identity(obj)[1] + "-")
                       for ns, name in claims)
            ):
                targets[key(obj)] = record(
                    obj, "hibernation",
                    obj["metadata"].get("annotations", {}).get("cnpg.io/hibernation"),
                )
    if stage in ("postgres", "ceph"):
        for obj in items:
            if obj["kind"] == "ScheduledBackup":
                targets[key(obj)] = record(obj, "suspend", obj["spec"].get("suspend"))
    if stage == "ceph":
        for obj in items:
            if obj["kind"] == "SnapshotSchedule":
                targets[key(obj)] = record(obj, "schedule.suspend", obj["spec"]["schedule"].get("suspend"))
    for obj in items:
        if obj["kind"] == "HorizontalPodAutoscaler":
            ref = obj["spec"]["scaleTargetRef"]
            target = f"{ref['kind']}/{identity(obj)[0]}/{ref['name']}"
            if target in targets or target in guards:
                raise RuntimeError(f"Suspend autoscaler {key(obj)} before maintenance")
    # LLmKube's operator itself mounts the model cache: stop it as a guard,
    # and restore it only after the other consumers have been restored.
    for name in guards:
        targets.pop(name, None)
    return targets, guards


def save(state):
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n")
    os.chmod(temporary, 0o600)
    temporary.replace(STATE)


def resource(action):
    # Cluster is ambiguous with other installed CRDs.
    kind = {
        "Cluster": "cluster.postgresql.cnpg.io",
        "SnapshotSchedule": "snapshotschedules.kopiur.home-operations.com",
        "GarageCluster": "garageclusters.v1beta2.garage.rajsingh.info",
    }.get(action["kind"], action["kind"])
    return f"{kind}/{action['name']}"


def apply(action, restore=False):
    ref = resource(action)
    ns = action["namespace"]
    current = json.loads(kubectl("get", ref, "-n", ns, "-o", "json"))
    if current["metadata"]["uid"] != action["uid"]:
        raise RuntimeError(f"{ref} was replaced; saved state needs manual review")
    field = action["field"]
    value = action["original"] if restore else 0
    if field == "hibernation":
        annotation = ("cnpg.io/hibernation-" if restore and value is None
                      else f"cnpg.io/hibernation={value if restore else 'on'}")
        kubectl("annotate", ref, "-n", ns, annotation, "--overwrite", capture=False)
    elif field == "maintenance":
        value = action["original"] if restore else {
            **(current["spec"].get("maintenance") or {}), "suspended": True,
        }
        if restore and value is None:
            if "maintenance" not in current["spec"]:
                return
            patch = [{"op": "remove", "path": "/spec/maintenance"}]
        else:
            patch = [{"op": "add", "path": "/spec/maintenance", "value": value}]
        kubectl("patch", ref, "-n", ns, "--type=json", "-p", json.dumps(patch), capture=False)
    elif field == "nodeSelector":
        # A JSON patch replaces the whole selector, preserving its original
        # absence and avoiding merge-patch keys lingering on recovery.
        original = pod_template(current)["spec"].get("nodeSelector", {})
        value = action["original"] if restore else {
            **original, "maintenance.home.arpa/disabled": "true",
        }
        kubectl("patch", ref, "-n", ns, "--type=json", "-p", json.dumps([
            {"op": "add", "path": "/spec/template/spec/nodeSelector", "value": value}
        ]), capture=False)
    else:
        if field in ("suspend", "schedule.suspend") and not restore:
            value = True
        spec = {"schedule": {"suspend": value}} if field == "schedule.suspend" else {field: value}
        kubectl("patch", ref, "-n", ns, "--type=merge", "-p",
                json.dumps({"spec": spec}), capture=False)


def wait_for(description, predicate, timeout=TIMEOUT):
    deadline = time.monotonic() + timeout
    while True:
        pending = predicate()
        if not pending:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Timed out {description}: {', '.join(pending)}")
        print(f"Waiting {description}: {', '.join(pending)}", flush=True)
        time.sleep(5)


def active(obj):
    return obj.get("status", {}).get("phase") not in ("Succeeded", "Failed")


def snapshot_requests(items, run):
    """Build every request before stopping workloads; fail on missing coverage."""
    _, claims = ceph_claims(items)
    volumes = {i["metadata"]["name"]: i for i in items if i["kind"] == "PersistentVolume"}
    requests = []

    def request(kind, namespace, source, spec):
        suffix = hashlib.sha256(f"{kind}/{namespace}/{source}".encode()).hexdigest()[:12]
        requests.append({
            "apiVersion": ("snapshot.storage.k8s.io/v1" if kind == "VolumeSnapshot"
                           else "kopiur.home-operations.com/v1alpha1"),
            "kind": kind,
            "metadata": {"namespace": namespace, "name": f"maintenance-{run}-{suffix}",
                         "labels": {"maintenance.home.arpa/run": run}},
            "spec": spec,
        })

    for obj in items:
        ns, name = identity(obj)
        if obj["kind"] == "PersistentVolumeClaim" and (ns, name) in claims:
            if obj.get("status", {}).get("phase") != "Bound":
                raise RuntimeError(f"Cannot snapshot unbound Ceph PVC {ns}/{name}")
            driver = volumes.get(obj["spec"].get("volumeName"), {}).get("spec", {}).get("csi", {}).get("driver")
            classes = [i for i in items if i["kind"] == "VolumeSnapshotClass" and i.get("driver") == driver]
            defaults = [i for i in classes if i["metadata"].get("annotations", {}).get(
                "snapshot.storage.kubernetes.io/is-default-class") == "true"]
            selected = defaults if defaults else classes
            if len(selected) != 1:
                raise RuntimeError(f"No unambiguous VolumeSnapshotClass for {ns}/{name} ({driver})")
            request("VolumeSnapshot", ns, name, {
                "volumeSnapshotClassName": selected[0]["metadata"]["name"],
                "source": {"persistentVolumeClaimName": name},
            })
        elif obj["kind"] == "SnapshotPolicy":
            if obj["spec"].get("suspend"):
                raise RuntimeError(f"SnapshotPolicy {ns}/{name} is suspended")
            spec = {
                "policyRef": {"name": name},
                "deletionPolicy": obj["spec"].get("defaultDeletionPolicy", "Delete"),
                "tags": {"reason": "pre-maintenance", "maintenance-run": run},
            }
            if (ns, name) in MAINTENANCE_MOVERS:
                spec["mover"] = MAINTENANCE_MOVERS[(ns, name)]
            request("Snapshot", ns, name, spec)
    if not requests:
        raise RuntimeError("No Ceph PVCs or Kopiur policies found to snapshot")
    return requests


def snapshot_inventory():
    return json.loads(kubectl("get", "volumesnapshot,snapshots.kopiur.home-operations.com",
                              "-A", "-o", "json"))["items"]


def take_snapshots(state):
    requests = state["snapshots"]["requests"]
    existing = {key(i): i for i in snapshot_inventory()}
    for manifest in requests:
        obj = existing.get(key(manifest))
        if obj is None:
            kubectl("create", "-f", "-", manifest=manifest, capture=False)
        elif obj["metadata"].get("labels", {}).get("maintenance.home.arpa/run") != state["snapshots"]["run"]:
            raise RuntimeError(f"Snapshot name collision: {key(manifest)}")

    def pending():
        current = {key(i): i for i in snapshot_inventory()}
        remaining = []
        for manifest in requests:
            name = key(manifest)
            obj = current.get(name, {})
            status = obj.get("status", {})
            if manifest["kind"] == "VolumeSnapshot":
                if status.get("error"):
                    raise RuntimeError(f"{name} failed: {status['error'].get('message', 'snapshot error')}")
                complete = status.get("readyToUse") is True
            else:
                if status.get("phase") in ("Failed", "Deleting") or status.get("stats", {}).get("filesFailed", 0):
                    raise RuntimeError(f"{name} failed or contains unreadable files; inspect its status")
                complete = status.get("phase") in ("Succeeded", "Unchanged")
            if not complete:
                remaining.append(name)
        return remaining

    wait_for("for maintenance snapshots and backups to complete", pending, timeout=SNAPSHOT_TIMEOUT)
    # A run already queued before schedule suspension can still start late.
    wait_for("for other Kopiur snapshot operations to finish", lambda: [
        key(i) for i in snapshot_inventory() if i["kind"] == "Snapshot"
        and i.get("status", {}).get("phase") not in ("Succeeded", "Unchanged", "Failed", "Discovered")
    ], timeout=SNAPSHOT_TIMEOUT)
    state["snapshots"]["complete"] = True
    save(state)
    print(f"Maintenance snapshot run verified: {state['snapshots']['run']}")


def wait_stopped(actions):
    def pending():
        pods = json.loads(kubectl("get", "pod", "-A", "-o", "json"))["items"]
        remaining = []
        for action in actions:
            if action["field"] == "maintenance":
                nodes = json.loads(kubectl("get", "garagenodes.garage.rajsingh.info",
                                           "-n", action["namespace"], "-o", "json"))["items"]
                for node in nodes:
                    if node["spec"]["clusterRef"]["name"] != action["name"]:
                        continue
                    suspended = any(c["type"] == "Suspended" and c["status"] == "True"
                                    and c.get("observedGeneration") == node["metadata"]["generation"]
                                    for c in node.get("status", {}).get("conditions", []))
                    if not suspended:
                        remaining.append(key(node))
                continue
            if action["field"] not in ("replicas", "nodeSelector"):
                continue
            obj = json.loads(kubectl("get", resource(action), "-n", action["namespace"], "-o", "json"))
            selector = obj["spec"]["selector"]
            def matches(pod):
                labels = pod["metadata"].get("labels", {})
                if not all(labels.get(k) == v for k, v in selector.get("matchLabels", {}).items()):
                    return False
                for expr in selector.get("matchExpressions", []):
                    value = labels.get(expr["key"])
                    op = expr["operator"]
                    if (op == "In" and value not in expr["values"]
                        or op == "NotIn" and value in expr["values"]
                        or op == "Exists" and value is None
                        or op == "DoesNotExist" and value is not None):
                        return False
                return True
            remaining.extend(key(p) for p in pods if active(p)
                             and identity(p)[0] == action["namespace"] and matches(p))
        return remaining
    wait_for("for workload Pods to terminate", pending)


def verify_stopped(stage):
    def pending():
        items = inventory()
        classes, claims = ceph_claims(items)
        remaining = [key(i) for i in items if i["kind"] == "Pod" and active(i)
                and identity(i)[0] != "rook-ceph"
                and (stage in dependencies(i, classes, claims)
                     or stage == "ceph" and "postgres" in dependencies(i, classes, claims))]
        if stage in ("postgres", "ceph"):
            remaining.extend(key(i) for i in items if i["kind"] == "Backup"
                             and i.get("status", {}).get("phase") not in ("completed", "failed"))
        return remaining
    # Also catches active Jobs, backup movers and unmanaged Pods. Let them
    # finish; never delete a backup or restore operation to pass verification.
    wait_for(f"for all {stage} consumers to stop", pending)


def ready(action):
    if action["field"] == "hibernation":
        if action["original"] != "on":
            obj = json.loads(kubectl("get", resource(action), "-n", action["namespace"], "-o", "json"))
            kubectl("wait", resource(action), "-n", action["namespace"],
                    f"--for=jsonpath={{.status.readyInstances}}={obj['spec']['instances']}",
                    "--timeout=10m", capture=False)
    elif action["field"] == "replicas" and action["original"] == 0:
        return
    elif action["field"] in ("replicas", "nodeSelector"):
        if action["kind"] == "StatefulSet":
            obj = json.loads(kubectl("get", resource(action), "-n", action["namespace"], "-o", "json"))
            if obj["spec"].get("updateStrategy", {}).get("type") == "OnDelete":
                # OnDelete deliberately permits old Pod revisions. Wait for the
                # restored replica count, not a rollout that requires Pod deletion.
                def pending():
                    current = json.loads(kubectl("get", resource(action), "-n", action["namespace"], "-o", "json"))
                    if current["metadata"]["uid"] != action["uid"]:
                        raise RuntimeError(f"{resource(action)} was replaced while waiting for readiness")
                    status = current.get("status", {})
                    desired = action["original"]
                    if (not current["metadata"].get("deletionTimestamp")
                            and current["spec"].get("replicas", 1) == desired
                            and status.get("observedGeneration", 0) >= current["metadata"]["generation"]
                            and status.get("replicas", 0) == desired
                            and status.get("readyReplicas", 0) == desired):
                        return []
                    return [resource(action)]
                wait_for(f"for {resource(action)} replicas to become ready", pending)
                return
        kubectl("rollout", "status", resource(action), "-n", action["namespace"],
                "--timeout=10m", capture=False)


def shutdown(state, stage, items):
    if "Deployment/garage-system/garage-operator" in state["guards"]:
        raise RuntimeError("Saved maintenance state stopped Garage's admission webhook; "
                           "recover it with GarageCluster maintenance suspension before retrying")
    targets, guards = plan(items, stage)
    if stage == "ceph" and "snapshots" not in state:
        run = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
        state["snapshots"] = {"run": run, "requests": snapshot_requests(items, run), "complete": False}
    for section, new in (("resources", targets), ("guards", guards)):
        for name, action in new.items():
            saved = state[section].setdefault(name, action)
            if stage not in saved["stages"]:
                saved["stages"].append(stage)
    if stage not in state["stages"]:
        state["stages"].append(stage)
    save(state)  # Persist the complete inverse before the first mutation.
    for action in state["guards"].values():
        apply(action)
        wait_stopped([action])
    actions = [a for a in state["resources"].values() if stage in a["stages"]]
    deferred = [a for a in actions if stage == "ceph" and a["namespace"] == "kopiur-system"]
    consumers = [a for a in actions if a not in deferred]
    # Backups stop being scheduled before their producers and stores stop.
    for action in sorted(consumers, key=lambda a: not a["field"].endswith("suspend")):
        if action["field"] != "hibernation":
            apply(action)
    wait_stopped(consumers)
    if stage == "ceph":
        verify_stopped("postgres")
    for action in consumers:
        if action["field"] == "hibernation":
            apply(action)
            kubectl("wait", resource(action), "-n", action["namespace"],
                    "--for=jsonpath={.status.conditions[?(@.type==\"cnpg.io/hibernation\")].status}=True",
                    "--timeout=10m", capture=False)
    if stage == "ceph":
        take_snapshots(state)
        # Keep Kopiur alive through capture, off-site upload, and mover cleanup.
        verify_stopped("ceph")
        for action in deferred:
            apply(action)
        wait_stopped(deferred)
    verify_stopped(stage)
    print(f"{stage} shutdown verified. Saved recovery state: {STATE}")


def restore(state, stage):
    if stage not in state["stages"]:
        print(f"No saved {stage} maintenance stage to restore.")
        return
    if (STATE.parent / '.miroir-migration/operator-webhook.json').exists():
        raise RuntimeError('Temporary VictoriaMetrics webhook cleanup is incomplete; rerun '
                           'misc/ceph-to-miroir/repair_operator_storage.py --execute before restoring workloads')
    actions = [a for a in state["resources"].values() if a["stages"] == [stage]]
    # PostgreSQL first; ordinary consumers next; writers and schedules last.
    def order(action):
        if action["field"] == "hibernation":
            return 0
        if action["field"].endswith("suspend") or (action["namespace"], action["name"]) in CEPH_WRITERS:
            return 2
        return 1
    for action in sorted(actions, key=order):
        apply(action, restore=True)
        ready(action)
    # Guards remain frozen until all overlapping stages have been restored.
    if state["stages"] == [stage]:
        for action in reversed(list(state["guards"].values())):
            apply(action, restore=True)
            ready(action)
    for name, action in list(state["resources"].items()):
        if stage in action["stages"]:
            action["stages"].remove(stage)
        if not action["stages"]:
            del state["resources"][name]
    state["stages"].remove(stage)
    if stage == "ceph":
        state.pop("snapshots", None)
    if not state["stages"]:
        STATE.unlink()
    else:
        save(state)
    print(f"{stage} restored. Still held down by stages: {state['stages']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "shutdown", "restore"))
    parser.add_argument("stage", choices=("postgres", "dragonfly", "ceph"))
    args = parser.parse_args()
    context = kubectl("config", "current-context")
    if context != "admin@phoebe":
        raise RuntimeError(f"Expected admin@phoebe, got {context}")
    server = kubectl("config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}")
    if args.action == "plan":
        items = inventory()
        targets, guards = plan(items, args.stage)
        for label, actions in (("Freeze reconciliation", guards), ("Stop consumers", targets)):
            print(label + ":")
            for name in sorted(actions):
                print(f"  {name} ({actions[name]['field']})")
        if args.stage == "ceph":
            print("Snapshot after quiescing, before stopping Kopiur:")
            for manifest in snapshot_requests(items, "preview"):
                source = manifest["spec"].get("source", {}).get("persistentVolumeClaimName")
                source = source or manifest["spec"]["policyRef"]["name"]
                print(f"  {manifest['kind']}/{manifest['metadata']['namespace']}/{source}")
        return
    with STATE.with_suffix(".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(STATE.read_text()) if STATE.exists() else {
            "context": context, "server": server, "stages": [], "resources": {}, "guards": {},
        }
        if state["context"] != context or state["server"] != server:
            raise RuntimeError("Recovery state belongs to another cluster")
        if args.action == "shutdown":
            shutdown(state, args.stage, inventory())
        else:
            restore(state, args.stage)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, BlockingIOError) as error:
        sys.exit(str(error))
