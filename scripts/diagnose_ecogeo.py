#!/usr/bin/env python3
"""Diagnostic script for Ecoforest Ecogeo heat pump API responses."""

import sys
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


def h(val):
    """Decode hex string: returns (float/10, int, raw)."""
    try:
        raw = int(val.strip(), 16)
        signed = raw if raw <= 32768 else raw - 65536
        return signed / 10.0, signed, val.strip()
    except Exception:
        return None, None, val.strip()


def call_op(op):
    """Call an operation and return lines with error lines stripped."""
    body = urllib.parse.urlencode({"idOperacion": op}).encode()
    req = urllib.request.Request(
        f"{HOST}{ENDPOINT}",
        data=body,
        headers={"Authorization": f"Basic {credentials}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
        text = resp.read().decode(errors="replace")
    lines = [l for l in text.split('\n') if 'error' not in l]
    return lines  # last element is '0' (terminator)


def show_op(op, labels):
    print(f"\n=== Op {op} ===")
    try:
        lines = call_op(op)
        if len(lines) > 3:
            vals = lines[:-1]  # drop terminator
        else:
            vals = lines[0].split('&') if lines else []
        for i, (label, fmt) in enumerate(labels):
            if i >= len(vals):
                break
            f, iv, raw = h(vals[i])
            if fmt == 'temp':
                print(f"  [{i}] {label}: {f}°C (raw {raw})")
            elif fmt == 'pres':
                print(f"  [{i}] {label}: {f} bar (raw {raw})")
            elif fmt == 'pow':
                print(f"  [{i}] {label}: {iv} (raw {raw})")
            elif fmt == 'flag':
                print(f"  [{i}] {label}: {iv} (raw {raw})")
            else:
                print(f"  [{i}] {label}: raw={raw}  float={f}  int={iv}")
        if len(vals) > len(labels):
            print(f"  ... {len(vals)-len(labels)} more unlabelled values")
    except Exception as e:
        print(f"  ERROR: {e}")


def show_named_op(op, keys):
    """Show a named-field op (KEY=HEX per line) in kWh."""
    print(f"\n=== Op {op} ===")
    try:
        body = urllib.parse.urlencode({"idOperacion": op}).encode()
        req = urllib.request.Request(
            f"{HOST}{ENDPOINT}", data=body,
            headers={"Authorization": f"Basic {credentials}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            text = resp.read().decode(errors="replace")
        lines = [l.strip() for l in text.split('\n') if '=' in l and 'error' not in l]
        kv = {}
        for line in lines:
            k, _, v = line.partition('=')
            kv[k] = v
        for key, label in keys:
            raw = kv.get(key, '????')
            f, iv, _ = h(raw)
            kwh = iv / 10.0 if iv is not None else None
            print(f"  {key} {label}: {kwh} kWh (raw {raw})")
    except Exception as e:
        print(f"  ERROR: {e}")


print(f"Connecting to {HOST} ...")

show_op(2148, [
    ("language/model",          'flag'),   # a[0]
    ("year",                    'flag'),   # a[1]
    ("month",                   'flag'),   # a[2]
    ("day",                     'flag'),   # a[3]
    ("hour",                    'flag'),   # a[4]
    ("minute",                  'flag'),   # a[5]
    ("on/off icon",             'flag'),   # a[6]
    ("alarm icon",              'flag'),   # a[7]
    ("summer/winter",           'flag'),   # a[8]
    ("mode icon",               'flag'),   # a[9]
    ("auto mode",               'flag'),   # a[10]
    ("surplus ctrl",            'flag'),   # a[11]
    ("tariff",                  'flag'),   # a[12]
    ("night mode",              'flag'),   # a[13]
    ("SG signal",               'flag'),   # a[14]
    ("consumption ctrl",        'flag'),   # a[15]
    ("?16",                     'flag'),   # a[16]
    ("?17",                     'flag'),   # a[17]
    ("production pressure",     'pres'),   # a[18] pcc
    ("Production Return (TRC)", 'temp'),   # a[19] trc
    ("brine pressure",          'pres'),   # a[20] pcp
    ("outdoor temp",            'temp'),   # a[21] tem
    ("Production Supply (TIC)", 'temp'),   # a[22] tic
    ("Brine Supply (TIP)",      'temp'),   # a[23] tip
    ("Brine Return (TRP)",      'temp'),   # a[24] trp
    ("DHW flag",                'flag'),   # a[25]
    ("heating flag",            'flag'),   # a[26]
    ("cooling flag",            'flag'),   # a[27]
    ("passive cool flag",       'flag'),   # a[28]
    ("pool flag",               'flag'),   # a[29]
])

show_op(2149, [
    ("power unit (1=W 2=kW)",  'flag'),   # a[0] pu
    ("heating power",          'pow'),    # a[1] hui
    ("cooling power",          'pow'),    # a[2] coui
    ("electric consumption",   'pow'),    # a[3] weci
    ("active cool demand",     'flag'),   # a[4]
    ("anti-freeze demand",     'flag'),   # a[5]
    ("DHW demand",             'flag'),   # a[6]
    ("heating demand",         'flag'),   # a[7]
    ("legionella demand",      'flag'),   # a[8]
    ("passive cool demand",    'flag'),   # a[9]
    ("pool demand",            'flag'),   # a[10]
])

show_op(2150, [
    ("?0",                     'flag'),   # a[0]
    ("outdoor temp (mirror)",  'temp'),   # a[1]
    ("?2",                     'flag'),   # a[2]
    ("?3",                     'flag'),   # a[3]
    ("DHW tank temp",          'temp'),   # a[4]
    ("?5",                     'flag'),   # a[5]
    ("?6",                     'flag'),   # a[6]
    ("?7",                     'flag'),   # a[7]
    ("?8",                     'flag'),   # a[8]
    ("zone1 setpoint",         'temp'),   # a[9]  tsz1
    ("zone2 setpoint",         'temp'),   # a[10] tsz2
    ("zone3 setpoint",         'temp'),   # a[11] tsz3
    ("zone4 setpoint",         'temp'),   # a[12] tsz4
    ("zone5 setpoint",         'temp'),   # a[13] tsz5
    ("zone1 actual temp",      'temp'),   # a[14] ttz1
    ("zone2 actual temp",      'temp'),   # a[15] ttz2
    ("zone3 actual temp",      'temp'),   # a[16] ttz3
    ("zone4 actual temp",      'temp'),   # a[17] ttz4
    ("zone5 actual temp",      'temp'),   # a[18] ttz5
])

show_op(2151, [
    ("zone1 heat setpoint",    'temp'),   # a[0] hdtsg1
    ("zone2 heat setpoint",    'temp'),
    ("zone3 heat setpoint",    'temp'),
    ("zone4 heat setpoint",    'temp'),
    ("zone5 heat setpoint",    'temp'),
    ("zone1 real temp",        'temp'),   # a[5] ti1
    ("zone2 real temp",        'temp'),
    ("zone3 real temp",        'temp'),
    ("zone4 real temp",        'temp'),
    ("zone5 real temp",        'temp'),
    ("zone1 valve %",          'flag'),   # a[10] rvz1
    ("zone2 valve %",          'flag'),
    ("zone3 valve %",          'flag'),
    ("zone4 valve %",          'flag'),
    ("zone5 valve %",          'flag'),
    ("zone1 cool setpoint",    'temp'),   # a[15] cdtsg1
    ("zone2 cool setpoint",    'temp'),
    ("zone3 cool setpoint",    'temp'),
    ("zone4 cool setpoint",    'temp'),
    ("zone5 cool setpoint",    'temp'),
    ("heat buffer tank T",     'temp'),   # a[20] ticiner
    ("heat buffer setpoint",   'temp'),   # a[21] hbtsp
    ("heat buffer offset",     'temp'),   # a[22] oic
    ("cool buffer tank T",     'temp'),   # a[23] tif
    ("cool buffer setpoint",   'temp'),   # a[24] cbtsp
    ("cool buffer offset",     'temp'),   # a[25] oif
    ("DHW setpoint",           'temp'),   # a[26] dsm
    ("DHW dT start",           'temp'),   # a[27] ao
    ("DHW temp",               'temp'),   # a[28] dt
])

# Alarm status
print("\n=== Op 1079 (alarms) ===")
try:
    body = urllib.parse.urlencode({"idOperacion": 1079}).encode()
    req = urllib.request.Request(
        f"{HOST}{ENDPOINT}", data=body,
        headers={"Authorization": f"Basic {credentials}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
        print(f"  Raw: {repr(resp.read().decode(errors='replace'))}")
except Exception as e:
    print(f"  ERROR: {e}")

show_named_op(2137, [
    ("DE",    "Electricity consumed today"),
    ("DH",    "Heating energy today"),
    ("DAC",   "Active cooling energy today"),
    ("DPC",   "Passive cooling energy today"),
    ("DAU",   "ACS/DHW energy today"),
    ("DP",    "Pool energy today"),
    ("DIEH",  "IEH energy today"),
    ("DBEH",  "Backup electric heater today"),
    ("DCI",   "Cooling iEH today"),
])

show_named_op(2140, [
    ("ME",    "Electricity consumed (month)"),
    ("MH",    "Heating energy (month)"),
    ("MAC",   "Active cooling energy (month)"),
    ("MPC",   "Passive cooling energy (month)"),
    ("MAU",   "ACS/DHW energy (month)"),
    ("MP",    "Pool energy (month)"),
    ("MIEH",  "IEH energy (month)"),
    ("MBEH",  "Backup electric heater (month)"),
    ("MCI",   "Cooling iEH (month)"),
])
