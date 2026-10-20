"""Run the deployed Bash script with a fake UniFi HTTP boundary."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


APP = Path(__file__).resolve().parents[1] / "app"
CERT_ID = "cdacd8c3-58b8-4574-8129-daa89c5c7420"


class UploadTests(unittest.TestCase):
    def run_script(self, scenario):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tls.crt").write_text("fixture certificate\n")
            (root / "tls.key").write_text("fixture key\n")
            for name, contents in {
                "curl": Path(__file__).with_name("fake_curl.py").read_text(),
                "dnf": "#!/bin/sh\nexit 0\n",
                "openssl": "#!/bin/sh\necho 'sha1 Fingerprint=AA:BB:CC'\n",
            }.items():
                executable = root / name
                executable.write_text(contents)
                executable.chmod(0o755)
            result = subprocess.run(
                ["bash", str(APP / "upload.sh")], text=True, capture_output=True,
                env={**os.environ, "PATH": tmp + os.pathsep + os.environ["PATH"],
                     "FIXTURE": tmp, "CERT_DIR": tmp, "SCENARIO": scenario,
                     "UNIFI_USERNAME": 'user"quoted', "UNIFI_PASSWORD": 'pass\\word'},
            )
            calls = (root / "calls").read_text().splitlines()
        return result, calls

    def test_active_duplicate_is_noop(self):
        result, calls = self.run_script("existing")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("POST /api/userCertificates", calls)
        self.assertFalse(any(c.startswith("PUT") for c in calls))

    def test_existing_inactive_certificate_is_activated(self):
        result, calls = self.run_script("inactive")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("POST /api/userCertificates", calls)
        self.assertIn(f"PUT /api/userCertificates/{CERT_ID}/status", calls)

    def test_new_certificate_is_uploaded_and_verified(self):
        result, calls = self.run_script("new")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("POST /api/userCertificates", calls)
        self.assertIn(f"PUT /api/userCertificates/{CERT_ID}/status", calls)
        self.assertEqual(calls[-1], "GET /api/userCertificates")

    def test_failures_do_not_report_success(self):
        before_activation = (
            "login_error", "missing_csrf", "list_error", "bad_list",
            "upload_error", "missing_id", "invalid_id",
        )
        during_activation = ("activation_error", "activation_noop")
        for scenario in before_activation + during_activation:
            with self.subTest(scenario=scenario):
                result, calls = self.run_script(scenario)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("[INFO ] Complete", result.stdout + result.stderr)
                self.assertFalse(any("/null/" in call for call in calls))
                if scenario in before_activation:
                    self.assertFalse(any(c.startswith("PUT") for c in calls))


if __name__ == "__main__":
    unittest.main()
