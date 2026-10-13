#!/usr/bin/env python3
"""
MEB DC-DC runner — using CRC method and constants from Battery-Emulator.
CRC: data[1:] first, then PDU constant appended (not prepended).
"""

import can
import time

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
    # CRC over data[1:] with init 0xFF, no final XOR
    crc = crc8h2f_continue(data[1:], 0xFF, 0x00)
    # Then append PDU constant with final XOR 0xFF
    return crc8h2f_continue(bytes([pdu_const]), crc, 0xFF)

# PDU constants from Battery-Emulator
HVK_01_PDU = [0xED, 0xD6, 0x96, 0x63, 0xA5, 0x12, 0xD5, 0x9A, 0x1E, 0x0D, 0x24, 0xCD, 0x8C, 0xA6, 0x2F, 0x41]
NVEM_10_PDU = [0xD4, 0x22, 0xAD, 0x3F, 0x25, 0xAA, 0x62, 0x5B, 0xDC, 0x73, 0xED, 0xC3, 0x9A, 0x14, 0x2F, 0x3E]

TARGET_VOLTAGE = 14.4
RAW_14V = int(round((TARGET_VOLTAGE - 10.6) / 0.025))  # 152 = 0x98

def build_20f(counter: int, voltage_raw: int = RAW_14V) -> bytes:
    data = bytearray([0x00, counter & 0x0F, 0x00, 0x00, 0x40, 0x00, 0xFD, voltage_raw & 0xFF])
    data[0] = vw_crc(data, NVEM_10_PDU[counter & 0x0F])
    return bytes(data)

def build_503(counter: int) -> bytes:
    # Payload from successful log: 00 D1 0F 42 E4 00
    data = bytearray([0x00, 0x60 | (counter & 0x0F), 0x00, 0xD1, 0x0F, 0x42, 0xE4, 0x00])
    data[0] = vw_crc(data, HVK_01_PDU[counter & 0x0F])
    return bytes(data)

def build_271() -> bytes:
    return bytes.fromhex("0000000024001cfd8f000000000000f500008abb00000000000000000000003f0700")

def build_5bb() -> bytes:
    return bytes(8)

def main():
    print(f"Target: {TARGET_VOLTAGE} V")
    print("Starting on can0...")

    bus = can.interface.Bus(channel='can0', bustype='socketcan', fd=True)
    t0 = time.monotonic()
    next_20f = next_503 = next_271 = next_5bb = t0
    ctr_20f = ctr_503 = 0

    try:
        while True:
            now = time.monotonic()
            elapsed = now - t0

            if elapsed < 4.0:
                volt = 0x00
            else:
                volt = RAW_14V

            if now >= next_20f:
                bus.send(can.Message(arbitration_id=0x20F, data=build_20f(ctr_20f, volt), is_extended_id=False, is_fd=True, bitrate_switch=True))
                ctr_20f = (ctr_20f + 1) & 0x0F
                next_20f += 0.050

            if now >= next_503:
                frame = build_503(ctr_503)
                bus.send(can.Message(arbitration_id=0x503, data=frame, is_extended_id=False, is_fd=True, bitrate_switch=True))
                ctr_503 = (ctr_503 + 1) & 0x0F
                next_503 += 0.100

            if now >= next_271:
                bus.send(can.Message(arbitration_id=0x271, data=build_271(), is_extended_id=False, is_fd=True, bitrate_switch=True))
                next_271 += 0.100

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
