#!/usr/bin/env python3
"""
MEB DC-DC precharge with hysteresis band.
Maintains HV voltage between TARGET_HV_LOW and TARGET_HV_HIGH.
"""

import can
import time
import threading

def crc8h2f_continue(data: bytes, crc: int, final_xor: int = 0x00) -> int:
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x80:
                crc = (crc << 1) ^ 0x2F
            else:
                crc <<= 1
            crc &= 0xFF
    return crc ^ final_xor

def vw_crc(data: bytes, pdu_const: int) -> int:
    crc = crc8h2f_continue(data[1:], 0xFF, 0x00)
    return crc8h2f_continue(bytes([pdu_const]), crc, 0xFF)

HVK_01_PDU = [0xED, 0xD6, 0x96, 0x63, 0xA5, 0x12, 0xD5, 0x9A, 0x1E, 0x0D, 0x24, 0xCD, 0x8C, 0xA6, 0x2F, 0x41]
NVEM_10_PDU = [0xD4, 0x22, 0xAD, 0x3F, 0x25, 0xAA, 0x62, 0x5B, 0xDC, 0x73, 0xED, 0xC3, 0x9A, 0x14, 0x2F, 0x3E]
BMS_20_PDU = [0xEE, 0x80, 0x6E, 0x4E, 0x29, 0xC6, 0x92, 0xC0, 0x65, 0xAA, 0x3A, 0xA1, 0x8F, 0xCD, 0xE6, 0x90]

TARGET_HV_HIGH = 360.0
TARGET_HV_LOW = 350.0
TARGET_LV_VOLTAGE = 14.4
RAW_LV = int(round((TARGET_LV_VOLTAGE - 10.6) / 0.025))

hv_voltage = 0.0
dcdc_mode = 7
hv_lock = threading.Lock()

def build_20f(counter: int, voltage_raw: int) -> bytes:
    data = bytearray([0x00, counter & 0x0F, 0x00, 0x00, 0x40, 0x00, 0xFD, voltage_raw & 0xFF])
    data[0] = vw_crc(data, NVEM_10_PDU[counter & 0x0F])
    return bytes(data)

def build_503_request(counter: int) -> bytes:
    data = bytearray([0x00, 0x60 | (counter & 0x0F), 0x00, 0xC8, 0x0F, 0x00, 0x60, 0x00])
    data[0] = vw_crc(data, HVK_01_PDU[counter & 0x0F])
    return bytes(data)

def build_503_precharge(counter: int) -> bytes:
    data = bytearray([0x00, 0xE0 | (counter & 0x0F), 0x00, 0xC8, 0x0F, 0x00, 0x60, 0x00])
    data[0] = vw_crc(data, HVK_01_PDU[counter & 0x0F])
    return bytes(data)

def build_503_standby(counter: int) -> bytes:
    data = bytearray([0x00, 0x60 | (counter & 0x0F), 0x00, 0xC0, 0x0F, 0x00, 0x60, 0x00])
    data[0] = vw_crc(data, HVK_01_PDU[counter & 0x0F])
    return bytes(data)

def build_271() -> bytes:
    return bytes.fromhex("0000000024001cfd8f000000000000f500008abb00000000000000000000003f0700")

def build_5bb() -> bytes:
    return bytes(8)

def build_cf(counter: int, pack_voltage: float, zk_voltage: float) -> bytes:
    pack_raw = int(pack_voltage / 0.25)
    zk_raw = int((zk_voltage + 1000) / 0.5)
    data = bytearray(8)
    data[1] = counter & 0x0F
    data[2] = 0x07
    data[5] = zk_raw & 0xFF
    data[6] = (zk_raw >> 8) & 0x0F
    data[6] |= (pack_raw & 0x0F) << 4
    data[7] = (pack_raw >> 4) & 0xFF
    data[0] = vw_crc(data, BMS_20_PDU[counter & 0x0F])
    return bytes(data)

def decode_hv_voltage(data: bytes) -> float:
    raw = ((data[1] & 0xF0) >> 4) | (data[2] << 4)
    return raw * 0.25

def decode_mode(data: bytes) -> int:
    return (data[5] >> 1) & 0x07

def rx_thread(bus):
    global hv_voltage, dcdc_mode
    while True:
        msg = bus.recv(timeout=0.1)
        if not msg:
            continue
        if msg.arbitration_id == 0x2AE and len(msg.data) >= 4:
            v = decode_hv_voltage(msg.data)
            with hv_lock:
                hv_voltage = v
        elif msg.arbitration_id == 0x0F7 and len(msg.data) >= 6:
            m = decode_mode(msg.data)
            with hv_lock:
                dcdc_mode = m

def main():
    print(f"Precharge band: {TARGET_HV_LOW:.0f}–{TARGET_HV_HIGH:.0f} V")
    print("Starting on can0...")
    bus = can.interface.Bus(channel='can0', bustype='socketcan', fd=True)
    rx = threading.Thread(target=rx_thread, args=(bus,), daemon=True)
    rx.start()
    t0 = time.monotonic()
    next_20f = next_503 = next_271 = next_5bb = next_cf = t0
    ctr_20f = ctr_503 = ctr_cf = 0
    phase = "WAIT_STABLE"
    stable_count = 0
    last_print = t0
    try:
        while True:
            now = time.monotonic()
            with hv_lock:
                v = hv_voltage
                mode = dcdc_mode
            if phase == "WAIT_STABLE" and 0.5 < v < 10.0:
                stable_count += 1
                if stable_count >= 5:
                    print(f"\nHV stable at {v:.1f} V — requesting precharge")
                    phase = "REQUEST"
            elif phase == "WAIT_STABLE":
                stable_count = 0
            if phase == "REQUEST" and mode == 1:
                print(f"\nDC-DC confirmed precharge mode — activating")
                phase = "PRECHARGE"
            if phase == "PRECHARGE" and v >= TARGET_HV_HIGH and v < 1000.0:
                print(f"\nTarget reached: {v:.1f} V — switching to standby")
                phase = "HOLD"
            if phase == "HOLD" and v < TARGET_HV_LOW:
                print(f"\nVoltage dropped to {v:.1f} V — resuming precharge")
                phase = "REQUEST"
            if now - last_print >= 1.0:
                mode_names = {0: "Standby", 1: "Precharge", 2: "Buck", 5: "Error", 7: "Init"}
                print(f"  HV: {v:.1f} V  Mode: {mode_names.get(mode, mode)}  Phase: {phase}")
                last_print = now
            if now >= next_20f:
                bus.send(can.Message(arbitration_id=0x20F, data=build_20f(ctr_20f, RAW_LV), is_extended_id=False, is_fd=True, bitrate_switch=True))
                ctr_20f = (ctr_20f + 1) & 0x0F
                next_20f += 0.050
            if now >= next_503:
                if phase == "PRECHARGE":
                    frame = build_503_precharge(ctr_503)
                elif phase == "REQUEST":
                    frame = build_503_request(ctr_503)
                else:
                    frame = build_503_standby(ctr_503)
                bus.send(can.Message(arbitration_id=0x503, data=frame, is_extended_id=False, is_fd=True, bitrate_switch=True))
                ctr_503 = (ctr_503 + 1) & 0x0F
                next_503 += 0.100
            if now >= next_271:
                bus.send(can.Message(arbitration_id=0x271, data=build_271(), is_extended_id=False, is_fd=True, bitrate_switch=True))
                next_271 += 0.100
            if now >= next_cf:
                bus.send(can.Message(arbitration_id=0xCF, data=build_cf(ctr_cf, TARGET_HV_HIGH, v), is_extended_id=False, is_fd=True, bitrate_switch=True))
                ctr_cf = (ctr_cf + 1) & 0x0F
                next_cf += 0.100
            if now >= next_5bb:
                bus.send(can.Message(arbitration_id=0x5BB, data=build_5bb(), is_extended_id=False, is_fd=True, bitrate_switch=True))
                next_5bb += 0.500
            time.sleep(0.001)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        bus.shutdown()

if __name__ == "__main__":
    main()
