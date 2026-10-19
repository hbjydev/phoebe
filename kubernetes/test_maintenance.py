"""Offline checks for maintenance discovery and staged recovery."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import maintenance as m


def workload(name, namespace="apps", kind="Deployment", replicas=1, labels=None,
             claims=(), owner=None, selector=None):
    obj = {
        "kind": kind,
        "metadata": {"name": name, "namespace": namespace, "uid": f"uid-{name}"},
        "spec": {
            "replicas": replicas,
            "selector": {"matchLabels": {"app": name}},
            "template": {
                "metadata": {"labels": {"app": name, **(labels or {})}},
                "spec": {"containers": [], "volumes": [
                    {"persistentVolumeClaim": {"claimName": claim}} for claim in claims
                ]},
            },
        },
    }
    if owner:
        obj["metadata"]["ownerReferences"] = [{"kind": owner, "name": name}]
    if selector is not None:
        obj["spec"]["template"]["spec"]["nodeSelector"] = selector
    return obj


def fixtures():
    return [
        *(workload(name, ns) for ns, name in m.FLUX),
        workload("litellm-operator", "ai"),
        workload("shared", labels={
            "db.policy.home.arpa/postgres": "allow",
            "db.policy.home.arpa/df-shared": "allow",
        }, replicas=2, claims=("data",)),
        workload("idle", replicas=0, claims=("data",)),
        workload("watcher", kind="DaemonSet", labels={
            "db.policy.home.arpa/postgres": "allow",
        }, selector={"kubernetes.io/os": "linux"}),
        {"kind": "StorageClass", "metadata": {"name": "ceph"},
         "provisioner": "rook-ceph.rbd.csi.ceph.com"},
        {"kind": "PersistentVolumeClaim", "metadata": {"name": "data", "namespace": "apps"},
         "spec": {"storageClassName": "ceph"}},
        {"kind": "Cluster", "metadata": {"name": "postgres", "namespace": "database", "uid": "pg"},
         "spec": {"storage": {"storageClass": "ceph"}, "instances": 2}},
        {"kind": "ScheduledBackup", "metadata": {"name": "backup", "namespace": "database", "uid": "backup"},
         "spec": {}},
    ]


class DiscoveryTests(unittest.TestCase):
    def test_current_claims_templates_and_csi_driver(self):
        items = fixtures()
        items.extend([
            {"kind": "PersistentVolume", "metadata": {"name": "static"},
             "spec": {"csi": {"driver": "rook-ceph.cephfs.csi.ceph.com"}}},
            {"kind": "PersistentVolumeClaim", "metadata": {"name": "static", "namespace": "apps"},
             "spec": {"volumeName": "static"}},
            workload("static-user", claims=("static",)),
            workload("templated", kind="StatefulSet"),
        ])
        items[-1]["spec"]["volumeClaimTemplates"] = [{"spec": {"storageClassName": "ceph"}}]
        targets, _ = m.plan(items, "ceph")
        self.assertIn("Deployment/apps/static-user", targets)
        self.assertIn("StatefulSet/apps/templated", targets)
        self.assertIn("Deployment/apps/idle", targets)
        self.assertIn("Cluster/database/postgres", targets)
        self.assertIn("ScheduledBackup/database/backup", targets)
        self.assertIn("ScheduledBackup/database/backup", m.plan(items, "postgres")[0])

    def test_default_ceph_storage_class(self):
        items = fixtures()
        items[7]["metadata"]["annotations"] = {"storageclass.kubernetes.io/is-default-class": "true"}
        obj = workload("defaulted", kind="StatefulSet")
        obj["spec"]["volumeClaimTemplates"] = [{"spec": {}}]
        targets, _ = m.plan([*items, obj], "ceph")
        self.assertIn(m.key(obj), targets)

    def test_secret_reference_and_unlabelled_livekit(self):
        pg = workload("pg", namespace="database")
        pg["spec"]["template"]["spec"]["containers"] = [{"envFrom": [
            {"secretRef": {"name": "my-postgres"}}
        ]}]
        items = [*fixtures(), pg, workload("livekit", "matrix")]
        self.assertIn(m.key(pg), m.plan(items, "postgres")[0])
        self.assertIn("Deployment/matrix/livekit", m.plan(items, "dragonfly")[0])
        pg["spec"]["template"]["metadata"]["labels"]["cnpg.io/podRole"] = "pooler"
        self.assertNotIn(m.key(pg), m.plan(items, "postgres")[0])

    def test_operator_freezes_and_unknown_owner_abort(self):
        obj = workload("proxy", owner="LiteLLMProxy", labels={
            "db.policy.home.arpa/postgres": "allow",
        })
        _, guards = m.plan([*fixtures(), obj], "postgres")
        self.assertIn("Deployment/ai/litellm-operator", guards)
        obj["metadata"]["ownerReferences"][0]["kind"] = "UnknownOperator"
        with self.assertRaisesRegex(RuntimeError, "Unknown owner"):
            m.plan([*fixtures(), obj], "postgres")

    def test_garage_keeps_webhook_online_and_suspends_parent(self):
        cluster = {"kind": "GarageCluster", "metadata": {
            "name": "garage", "namespace": "garage-system", "uid": "garage"},
            "spec": {}}
        node = {"kind": "GarageNode", "metadata": {
            "name": "garage-node0", "namespace": "garage-system", "uid": "node"},
            "spec": {"clusterRef": {"name": "garage"}}}
        sts = workload("garage-node0", "garage-system", kind="StatefulSet",
                       owner="GarageNode", claims=("data",))
        claim = {"kind": "PersistentVolumeClaim", "metadata": {
            "name": "data", "namespace": "garage-system"},
            "spec": {"storageClassName": "ceph"}}
        items = [*fixtures(), workload("garage-operator", "garage-system"),
                 cluster, node, sts, claim]
        targets, guards = m.plan(items, "ceph")
        self.assertIn(m.key(sts), targets)
        self.assertNotIn("Deployment/garage-system/garage-operator", guards)
        self.assertEqual(guards[m.key(cluster)]["field"], "maintenance")
        self.assertIsNone(guards[m.key(cluster)]["original"])
        with self.assertRaisesRegex(RuntimeError, "GarageCluster"):
            m.plan([i for i in items if i is not cluster], "ceph")

    def test_autoscaler_and_matching_node_abort(self):
        hpa = {"kind": "HorizontalPodAutoscaler", "metadata": {"name": "auto", "namespace": "apps"},
               "spec": {"scaleTargetRef": {"kind": "Deployment", "name": "shared"}}}
        with self.assertRaisesRegex(RuntimeError, "autoscaler"):
            m.plan([*fixtures(), hpa], "postgres")
        node = {"kind": "Node", "metadata": {"name": "node", "labels": {
            "maintenance.home.arpa/disabled": "true",
        }}}
        with self.assertRaisesRegex(RuntimeError, "DaemonSet selector"):
            m.plan([*fixtures(), node], "postgres")


class RecoveryTests(unittest.TestCase):
    def test_overlapping_stages_preserve_inverse_and_restore_in_order(self):
        items = fixtures()
        state = {"stages": [], "resources": {}, "guards": {}}
        calls = []
        def apply(action, restore=False):
            # Every mutation has a durable inverse already on disk.
            self.assertTrue(m.STATE.exists())
            saved = json.loads(m.STATE.read_text())
            self.assertIn(action["uid"], [a["uid"] for section in ("resources", "guards")
                                          for a in saved[section].values()])
            calls.append((action["name"], restore, copy.deepcopy(action["original"])))
            obj = next(i for i in items if i.get("metadata", {}).get("uid") == action["uid"])
            if action["field"] == "replicas":
                obj["spec"]["replicas"] = action["original"] if restore else 0
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(m, "STATE", Path(directory) / "state.json"), \
                patch.object(m, "apply", side_effect=apply), \
                patch.object(m, "wait_stopped"), patch.object(m, "verify_stopped"), \
                patch.object(m, "ready"), patch.object(m, "kubectl"), \
                patch.object(m, "snapshot_requests", return_value=[]), patch.object(m, "take_snapshots"):
            for stage in ("postgres", "dragonfly", "ceph"):
                m.shutdown(state, stage, items)
            self.assertEqual(state["resources"]["Deployment/apps/shared"]["original"], 2)
            calls.clear()
            m.restore(state, "ceph")
            self.assertEqual(calls[0][:2], ("postgres", True))
            self.assertIn(("idle", True, 0), calls)
            self.assertNotIn("shared", [c[0] for c in calls])
            self.assertFalse(any(c[0] == "flux-operator" for c in calls))
            m.restore(state, "dragonfly")
            self.assertNotIn("shared", [c[0] for c in calls])
            m.restore(state, "postgres")
            self.assertIn(("shared", True, 2), calls)
            self.assertIn(("watcher", True, {"kubernetes.io/os": "linux"}), calls)
            self.assertEqual(calls[-1], ("flux-operator", True, 1))
            self.assertFalse(m.STATE.exists())

    def test_failed_restore_keeps_state_for_retry(self):
        state = {"stages": ["postgres"], "resources": {
            "Deployment/apps/shared": {**m.record(fixtures()[4], "replicas", 2), "stages": ["postgres"]},
        }, "guards": {}}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(m, "STATE", Path(directory) / "state.json"), \
                patch.object(m, "apply"), patch.object(m, "ready", side_effect=RuntimeError("not ready")):
            m.save(state)
            with self.assertRaisesRegex(RuntimeError, "not ready"):
                m.restore(state, "postgres")
            self.assertEqual(json.loads(m.STATE.read_text()), state)

    def test_verification_blocks_unmanaged_pods_and_active_backups(self):
        items = fixtures()
        pod = workload("mover", kind="Pod", claims=("data",))
        pod["spec"] = pod["spec"]["template"]["spec"]
        pod["status"] = {"phase": "Running"}
        backup = {"kind": "Backup", "metadata": {"name": "active", "namespace": "database"},
                  "status": {"phase": "running"}}
        items.extend((pod, backup))
        pending = []
        with patch.object(m, "inventory", return_value=items), \
                patch.object(m, "wait_for", side_effect=lambda _, f: pending.extend(f())):
            m.verify_stopped("ceph")
        self.assertIn("Pod/apps/mover", pending)
        self.assertIn("Backup/database/active", pending)
        pod["status"]["phase"] = "Succeeded"
        backup["status"]["phase"] = "completed"
        pending.clear()
        with patch.object(m, "inventory", return_value=items), \
                patch.object(m, "wait_for", side_effect=lambda _, f: pending.extend(f())):
            m.verify_stopped("ceph")
        self.assertEqual(pending, [])

    def test_garage_maintenance_restores_exact_original_and_waits_for_ack(self):
        cluster = {"kind": "GarageCluster", "metadata": {
            "name": "garage", "namespace": "garage-system", "uid": "garage"},
            "spec": {"maintenance": {"suspended": True}}}
        for original in (None, {"suspended": False}, {"suspended": True}):
            action = m.record(cluster, "maintenance", original)
            with patch.object(m, "kubectl", return_value=json.dumps(cluster)) as kubectl:
                m.apply(action, restore=True)
                payload = json.loads(kubectl.call_args.args[-1])
                if original is None:
                    self.assertEqual(payload, [{"op": "remove", "path": "/spec/maintenance"}])
                else:
                    self.assertEqual(payload[0]["value"], original)
        node = {"kind": "GarageNode", "metadata": {
            "name": "node", "namespace": "garage-system", "generation": 2},
            "spec": {"clusterRef": {"name": "garage"}}, "status": {}}
        def get(*args):
            return json.dumps({"items": [node] if args[1].startswith("garagenodes") else []})
        def wait(_, predicate):
            self.assertEqual(predicate(), ["GarageNode/garage-system/node"])
            node["status"]["conditions"] = [{"type": "Suspended", "status": "True",
                                               "observedGeneration": 2}]
            self.assertEqual(predicate(), [])
        with patch.object(m, "kubectl", side_effect=get), patch.object(m, "wait_for", side_effect=wait):
            m.wait_stopped([action])

    def test_legacy_garage_state_cannot_stop_webhook_again(self):
        with patch.object(m, "apply") as apply:
            with self.assertRaisesRegex(RuntimeError, "admission webhook"):
                m.shutdown({"guards": {"Deployment/garage-system/garage-operator": {}}},
                           "ceph", fixtures())
            apply.assert_not_called()

    def test_uid_replacement_rejected_before_mutation(self):
        action = m.record(fixtures()[4], "replicas", 2)
        obj = fixtures()[4]
        obj["metadata"]["uid"] = "new-uid"
        with patch.object(m, "kubectl", return_value=json.dumps(obj)) as kubectl:
            with self.assertRaisesRegex(RuntimeError, "was replaced"):
                m.apply(action, restore=True)
        self.assertEqual(kubectl.call_count, 1)


class SnapshotTests(unittest.TestCase):
    def snapshot_fixtures(self):
        items = fixtures()
        claim = next(i for i in items if i["kind"] == "PersistentVolumeClaim")
        claim["spec"]["volumeName"] = "volume"
        claim["status"] = {"phase": "Bound"}
        items.extend([
            {"kind": "PersistentVolume", "metadata": {"name": "volume"},
             "spec": {"csi": {"driver": "rook-ceph.rbd.csi.ceph.com"}}},
            {"kind": "VolumeSnapshotClass", "metadata": {"name": "snapshot-class"},
             "driver": "rook-ceph.rbd.csi.ceph.com"},
            {"kind": "SnapshotPolicy", "metadata": {"name": "shared", "namespace": "apps"},
             "spec": {"sources": [{"pvc": {"name": "data"}}]}},
        ])
        return items

    def test_all_ceph_claims_and_policies_get_deterministic_requests(self):
        items = self.snapshot_fixtures()
        requests = m.snapshot_requests(items, "session")
        self.assertEqual([i["kind"] for i in requests], ["VolumeSnapshot", "Snapshot"])
        self.assertEqual(requests, m.snapshot_requests(items, "session"))
        self.assertEqual(requests[0]["spec"]["source"], {"persistentVolumeClaimName": "data"})
        self.assertEqual(requests[1]["spec"]["tags"]["reason"], "pre-maintenance")
        policy = items[-1]
        policy["metadata"].update({"name": "home-assistant", "namespace": "default"})
        request = m.snapshot_requests(items, "session")[-1]
        self.assertEqual(request["spec"]["mover"]["securityContext"]["runAsUser"], 0)

    def test_unbound_claim_and_ambiguous_class_fail_before_shutdown(self):
        items = self.snapshot_fixtures()
        items[-2]["metadata"]["name"] = "first"
        items.append({**items[-2], "metadata": {"name": "second"}})
        with self.assertRaisesRegex(RuntimeError, "unambiguous"):
            m.snapshot_requests(items, "session")
        items.pop()
        next(i for i in items if i["kind"] == "PersistentVolumeClaim")["status"]["phase"] = "Pending"
        with self.assertRaisesRegex(RuntimeError, "unbound"):
            m.snapshot_requests(items, "session")

    def test_retry_reuses_requests_and_requires_ready_snapshots(self):
        requests = m.snapshot_requests(self.snapshot_fixtures(), "session")
        state = {"snapshots": {"run": "session", "requests": requests, "complete": False}}
        existing = []
        def create(*args, **kwargs):
            obj = copy.deepcopy(kwargs["manifest"])
            obj["status"] = {"readyToUse": False} if obj["kind"] == "VolumeSnapshot" else {"phase": "Running"}
            existing.append(obj)
        def wait(description, predicate, **kwargs):
            pending = predicate()
            if "maintenance snapshots" in description:
                self.assertEqual(len(pending), 2)
                for obj in existing:
                    obj["status"] = {"readyToUse": True} if obj["kind"] == "VolumeSnapshot" else {"phase": "Succeeded"}
                self.assertEqual(predicate(), [])
            else:
                self.assertEqual(pending, [])
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(m, "STATE", Path(directory) / "state.json"), \
                patch.object(m, "snapshot_inventory", side_effect=lambda: existing), \
                patch.object(m, "kubectl", side_effect=create) as kubectl, \
                patch.object(m, "wait_for", side_effect=wait):
            m.take_snapshots(state)
            self.assertEqual(kubectl.call_count, 2)
            self.assertTrue(json.loads(m.STATE.read_text())["snapshots"]["complete"])
            with patch.object(m, "wait_for", side_effect=lambda _, f, **kw: self.assertEqual(f(), [])):
                m.take_snapshots(state)
            self.assertEqual(kubectl.call_count, 2)

    def test_failed_csi_or_partial_backup_aborts(self):
        requests = m.snapshot_requests(self.snapshot_fixtures(), "session")
        state = {"snapshots": {"run": "session", "requests": requests, "complete": False}}
        for status in ({"phase": "Failed"}, {"phase": "Succeeded", "stats": {"filesFailed": 1}}):
            existing = copy.deepcopy(requests)
            existing[0]["status"] = {"readyToUse": True}
            existing[1]["status"] = status
            with patch.object(m, "snapshot_inventory", return_value=existing), \
                    patch.object(m, "wait_for", side_effect=lambda _, f, **kw: f()):
                with self.assertRaisesRegex(RuntimeError, "failed or contains unreadable"):
                    m.take_snapshots(state)
            self.assertFalse(state["snapshots"]["complete"])
        existing[0]["status"] = {"error": {"message": "CSI failure"}}
        with patch.object(m, "snapshot_inventory", return_value=existing), \
                patch.object(m, "wait_for", side_effect=lambda _, f, **kw: f()):
            with self.assertRaisesRegex(RuntimeError, "CSI failure"):
                m.take_snapshots(state)

    def test_snapshot_failure_keeps_kopiur_alive_and_retry_preserves_run(self):
        items = [*fixtures(), workload("kopiur-controller", "kopiur-system")]
        state = {"stages": [], "resources": {}, "guards": {}}
        events = []
        def snapshot(state):
            self.assertTrue(m.STATE.exists())
            self.assertIn("hibernation", events)
            self.assertNotIn("kopiur-controller", events)
            raise RuntimeError("snapshot failed")
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(m, "STATE", Path(directory) / "state.json"), \
                patch.object(m, "snapshot_requests", return_value=[{"saved": "request"}]), \
                patch.object(m, "apply", side_effect=lambda a: events.append(
                    "hibernation" if a["field"] == "hibernation" else a["name"])), \
                patch.object(m, "wait_stopped"), patch.object(m, "verify_stopped"), \
                patch.object(m, "kubectl"), patch.object(m, "take_snapshots", side_effect=snapshot):
            with self.assertRaisesRegex(RuntimeError, "snapshot failed"):
                m.shutdown(state, "ceph", items)
            saved = json.loads(m.STATE.read_text())
            self.assertEqual(saved["snapshots"], state["snapshots"])
            self.assertNotIn("kopiur-controller", events)
            events.clear()
            with patch.object(m, "take_snapshots", side_effect=lambda _: events.append("snapshot")):
                m.shutdown(state, "ceph", items)
            self.assertLess(events.index("hibernation"), events.index("snapshot"))
            self.assertLess(events.index("snapshot"), events.index("kopiur-controller"))
            self.assertEqual(saved["snapshots"], state["snapshots"])

    def test_schedule_suspension_uses_nested_field_and_restores_absence(self):
        schedule = {"kind": "SnapshotSchedule", "metadata": {
            "name": "nightly", "namespace": "apps", "uid": "schedule"},
            "spec": {"schedule": {"cron": "0 0 * * *"}}}
        action = m.record(schedule, "schedule.suspend", None)
        for restore, expected in ((False, True), (True, None)):
            with patch.object(m, "kubectl", return_value=json.dumps(schedule)) as kubectl:
                m.apply(action, restore=restore)
            payload = json.loads(kubectl.call_args.args[-1])
            self.assertEqual(payload, {"spec": {"schedule": {"suspend": expected}}})


if __name__ == "__main__":
    unittest.main()
