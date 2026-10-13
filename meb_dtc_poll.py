#!/usr/bin/env python3
"""
MEB DC-DC DTC poller
Reads DTCs every 2s and displays an updating list with English descriptions.
Requires meb_sim.py running in another terminal.
"""

import can
import time
import sys
import os
import json

CHANNEL = "can0"
BITRATE = 500_000
DATA_BITRATE = 2_000_000

REQ_ID = 0x17FC00B9
RESP_ID = 0x17FE00B9

# Load DTC descriptions from JSON file
DTC_DESC = {}
try:
    with open("DTCDOP_VAGUDS_EV_DCDC10030111EA907190B_001.json") as f:
        data = json.load(f)
        for d in data:
            DTC_DESC[d["code"]] = f"{d['dtc']} {d['l_dsc']}"
except Exception as e:
    print(f"Warning: could not load DTC JSON: {e}")

def send(bus, payload):
    msg = can.Message(
        arbitration_id=REQ_ID,
        data=payload,
        is_extended_id=True,
        is_fd=True,
        bitrate_switch=True,
    )
    bus.send(msg)

def recv_until(bus, timeout=0.5):
    end = time.time() + timeout
    while time.time() < end:
        msg = bus.recv(timeout=0.05)
        if msg and msg.arbitration_id == RESP_ID:
            return list(msg.data)
    return None

def read_dtcs(bus):
    """Read DTCs with 19 02 09 and return list of (code, status) tuples."""
    send(bus, [0x03, 0x19, 0x02, 0x09, 0x00, 0x00, 0x00, 0x00])
    resp = recv_until(bus, 0.5)
    if not resp:
        return None

    payload = resp[1:] if (resp[0] & 0xF0) == 0x00 else resp
    if len(payload) > 2 and payload[0] == 0x7F and payload[2] == 0x78:
        resp = recv_until(bus, 3.0)
        if not resp:
            return None
        payload = resp[1:] if (resp[0] & 0xF0) == 0x00 else resp

    # Multi-frame
    if len(resp) > 0 and (resp[0] & 0xF0) == 0x10:
        total = ((resp[0] & 0x0F) << 8) | resp[1]
        send(bus, [0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        collected = resp[2:]
        expected = total - len(collected)
        while expected > 0:
            cf = recv_until(bus, 0.5)
            if not cf:
                break
            collected.extend(cf[1:])
            expected -= len(cf) - 1
        payload = collected

    if len(payload) < 3 or payload[0] != 0x59:
        return None

    # Parse DTCs: 00 00 XX YY where XX is code, YY is status
    dtcs = []
    i = 3  # skip 59 02 09
    while i + 3 < len(payload):
        # Format is 00 00 XX YY
        if payload[i] == 0x00 and payload[i+1] == 0x00:
            code = payload[i+2]
            status = payload[i+3]
            dtcs.append((code, status))
            i += 4
        else:
            i += 1
    return dtcs

def read_did(bus, did):
    """Read a DID and return the response payload."""
    hi = (did >> 8) & 0xFF
    lo = did & 0xFF
    send(bus, [0x03, 0x22, hi, lo, 0x00, 0x00, 0x00, 0x00])
    resp = recv_until(bus, 0.5)
    if not resp:
        return None
    payload = resp[1:] if (resp[0] & 0xF0) == 0x00 else resp
    if len(payload) > 2 and payload[0] == 0x7F and payload[2] == 0x78:
        resp = recv_until(bus, 2.0)
        if not resp:
            return None
        payload = resp[1:] if (resp[0] & 0xF0) == 0x00 else resp
    if len(payload) > 0 and (resp[0] & 0xF0) == 0x10:
        total = ((resp[0] & 0x0F) << 8) | resp[1]
        send(bus, [0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        collected = resp[2:]
        expected = total - len(collected)
        while expected > 0:
            cf = recv_until(bus, 0.5)
            if not cf:
                break
            collected.extend(cf[1:])
            expected -= len(cf) - 1
        payload = collected
    return payload

def get_part_info(bus):
    """Read part number and software version."""
    info = {}
    # F191 - vehicle manufacturer ECU hardware number
    resp = read_did(bus, 0xF191)
    if resp and len(resp) > 3 and resp[0] == 0x62:
        info['hw'] = bytes(resp[3:]).decode('ascii', errors='replace').strip('\x00')
    # F189 - vehicle manufacturer ECU software number
    resp = read_did(bus, 0xF189)
    if resp and len(resp) > 3 and resp[0] == 0x62:
        info['sw'] = bytes(resp[3:]).decode('ascii', errors='replace').strip('\x00')
    return info

def display(dtcs, info=None):
    os.system('clear')
    print("MEB DC-DC DTC Poller  (Ctrl-C to stop)")
    if info:
        print(f"HW: {info.get('hw', '?')}   SW: {info.get('sw', '?')}")
    print("=" * 70)
    if dtcs is None:
        print("No response")
    elif len(dtcs) == 0:
        print("No DTCs")
    else:
        active = [(c, s) for c, s in dtcs if s & 0x01]
        stored = [(c, s) for c, s in dtcs if not (s & 0x01)]
        print(f"ACTIVE ({len(active)})")
        print("-" * 70)
        if active:
            for code, status in active:
                desc = DTC_DESC.get(code, "Unknown")
                print(f"  0x{code:02X}  0x{status:02X}  {desc}")
        else:
            print("  (none)")
        print()
        print(f"STORED ({len(stored)})")
        print("-" * 70)
        if stored:
            for code, status in stored:
                desc = DTC_DESC.get(code, "Unknown")
                print(f"  0x{code:02X}  0x{status:02X}  {desc}")
        else:
            print("  (none)")
    print("=" * 70)
    print(f"Updated: {time.strftime('%H:%M:%S')}")

def main():
    print(f"Opening {CHANNEL}...")
    try:
        bus = can.Bus(channel=CHANNEL, interface="socketcan", fd=True,
                      bitrate=BITRATE, data_bitrate=DATA_BITRATE)
    except Exception as e:
        print(f"Failed: {e}")
        sys.exit(1)

    # Enter extended session
    print("Entering extended session...")
    for _ in range(3):
        send(bus, [0x02, 0x10, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00])
        resp = recv_until(bus, 0.8)
        if resp:
            break
        time.sleep(0.3)

    # Read part info once
    info = get_part_info(bus)

    try:
        while True:
            dtcs = read_dtcs(bus)
            display(dtcs, info)
            time.sleep(2)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        bus.shutdown()

if __name__ == "__main__":
    main()
