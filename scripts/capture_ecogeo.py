#!/usr/bin/env python3
"""Capture raw API responses from the Ecoforest Ecogeo for use as test fixtures.

Usage:
    python3 capture_ecogeo.py HOST USERNAME PASSWORD
    python3 capture_ecogeo.py https://192.168.1.100 admin secret

Output: ecogeo_fixture.json  (safe to commit – no credentials or IP addresses)
"""

import sys
import json
import urllib.request
import urllib.parse
import ssl
import base64

HOST = sys.argv[1] if len(sys.argv) > 1 else input("Host (e.g. https://192.168.1.100): ")
USER = sys.argv[2] if len(sys.argv) > 2 else input("Username: ")
PASSWORD = sys.argv[3] if len(sys.argv) > 3 else input("Password: ")

credentials = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

ENDPOINT = "/recepcion_datos_4.cgi"


def fetch(op, extra=None):
    params = {"idOperacion": op}
    if extra:
        params.update(extra)
    body = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        f"{HOST}{ENDPOINT}",
        data=body,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
        return resp.read().decode(errors="replace")


print("Connecting …")

ops = {
    "detect":  fetch(2001, {"dir": 1, "num": 1}),  # protocol detection probe
    "op2148":  fetch(2148),                          # status / temps / pressures
    "op2149":  fetch(2149),                          # power
    "op2150":  fetch(2150),                          # outdoor stop temps, room-terminal zones
    "op2151":  fetch(2151),                          # buffer / zone / DHW temps
    "op1079":  fetch(1079),                          # alarm
    "op2137":  fetch(2137),                          # daily energy counters
    "op2140":  fetch(2140),                          # monthly energy counters
}

# Sanitise: strip the host and credentials from the fixture (they're not in
# the response bodies, but be explicit about it).
fixture = {
    "description": "Captured Ecoforest Ecogeo responses – host and credentials removed",
    "responses": ops,
}

out = "ecogeo_fixture.json"
with open(out, "w") as f:
    json.dump(fixture, f, indent=2)

print(f"Saved to {out}")
for key, text in ops.items():
    lines = text.splitlines()
    print(f"  {key:8s}: {len(lines)} lines, first={lines[0]!r}")
