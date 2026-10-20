#!/usr/bin/env python3
"""Fake curl executable for the uploader's UniFi API tests."""

import json
import os
from pathlib import Path
import sys


args = sys.argv[1:]
scenario = os.environ["SCENARIO"]
root = Path(os.environ["FIXTURE"])
url = next(a for a in args if a.startswith("https://"))
method = args[args.index("-X") + 1] if "-X" in args else "GET"
path = url.removeprefix("https://10.70.0.1")
with (root / "calls").open("a") as f:
    f.write(method + " " + path + "\n")


def respond(body, status=200):
    if status >= 400 and any(a in args for a in ("--fail", "--fail-with-body", "-f")):
        print("curl: HTTP " + str(status), file=sys.stderr)
        sys.exit(22)
    print(json.dumps(body))
    sys.exit(0)


cert = {
    "id": "cdacd8c3-58b8-4574-8129-daa89c5c7420",
    "fingerprint": "AA:BB:CC",
    "active": scenario == "existing" or (root / "activated").exists(),
}

if path == "/api/auth/login":
    if scenario == "login_error":
        respond({"message": "Unauthorized"}, 401)
    headers = "HTTP/1.1 200 OK\r\nSet-Cookie: TOKEN=fake; Path=/\r\nX-CSRF-Token: fake\r\n\r\n"
    if scenario == "missing_csrf":
        headers = headers.replace("X-CSRF-Token: fake\r\n", "")
    if "--dump-header" in args:
        Path(args[args.index("--dump-header") + 1]).write_bytes(headers.encode())
    if "-i" in args:
        print(headers)
    if "--data-binary" in args:
        payload = json.load(sys.stdin)
        assert payload == {"username": 'user"quoted', "password": 'pass\\word'}
    respond({})

if path == "/api/userCertificates" and method == "GET":
    if scenario == "list_error":
        respond({"message": "Forbidden"}, 403)
    if scenario == "bad_list":
        respond({"unexpected": []})
    needs_upload = scenario in ("new", "upload_error", "missing_id", "invalid_id")
    if needs_upload and not (root / "uploaded").exists():
        respond([])
    respond([cert])

if path == "/api/userCertificates" and method == "POST":
    if scenario in ("existing", "inactive", "upload_error"):
        respond({"code": "USER_CERTIFICATE_DUPLICATE"}, 400)
    if scenario == "missing_id":
        respond({})
    if scenario == "invalid_id":
        respond({"id": "not-a-uuid"})
    payload = json.load(sys.stdin)
    assert payload["cert"] == "fixture certificate\n"
    assert payload["key"] == "fixture key\n"
    (root / "uploaded").touch()
    respond(cert)

if method == "PUT":
    if scenario == "activation_error":
        respond({"message": "Forbidden"}, 403)
    if scenario != "activation_noop":
        (root / "activated").touch()
    respond({})

raise AssertionError((method, path))
