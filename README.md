## VW MEB DC-DC Reverse Engineering
<img width="768" height="432" alt="dcdc" src="https://github.com/user-attachments/assets/890fcc1f-a5a3-4edc-9e93-c11e266e921e" />

Information on controlling the VW MEB DC-DC converter (Bosch Gen4H13, part 1EA907190G).

Tested on a bench with 12V supply and a Prius HV capacitor on the HV bus for precharge.

BMW PHEV Pack supplying 380V on HV side for standard DCDC 12V support.

## Wiring

<img width="672" height="837" alt="image-1-1" src="https://github.com/user-attachments/assets/1160886c-5d5e-4787-9fc7-5d76d3904086" />

## Hardware

- Bosch Gen4H13 DC-DC converter (diag address 0xB9)
- CAN-FD at 500 kbit/s / 2 Mbit/s
- Peak USB adapter with SocketCAN
- 12V power supply
- HV capacitor (Prius) on the HV bus to limit residual voltage

## Scripts

### `meb_dcdc_run.py`

Runs the DC-DC in buck mode, regulating the 12V output to 14.4V.

```bash
python3 meb_dcdc_run.py
```

### `meb_dcdc_precharge.py`

Precharges the HV bus and maintains it between 350V and 360V using hysteresis.

```bash
python3 meb_dcdc_precharge.py
```

## CAN Messages

### Transmitted (TX)

| ID | Name | Interval | Description |
|----|------|----------|-------------|
| 0x20F | NVEM_10 | 50 ms | 12V setpoint. Byte 7 = voltage raw: `(V - 10.6) / 0.025` |
| 0x503 | HVK_01 | 100 ms | Mode request. See below. |
| 0x271 | HVLM_13 | 100 ms | Charging management frame |
| 0x5BB | - | 500 ms | Keep-alive (zeros) |
| 0xCF | BMS_20 | 100 ms | Pack voltage (precharge only) |

### Received (RX)

| ID | Name | Description |
|----|------|-------------|
| 0x0F7 | DCDC_04 | Status. `DC_IstModus_02` at bit 41. |
| 0x2AE | DCDC_01 | HV voltage. `DC_IstSpannung_HV` at bits 12-23, scale 0.25V. |
| 0x3F4 | DCDC_02 | Status |
| 0x5CD | DCDC_03 | Status |

### HVK_01 (0x503) Mode Bits

Byte 3 contains the mode request:
- Bits 0-2: BMS mode
- Bits 3-5: DC-DC mode (`HVK_DCDC_Sollmodus`)

DC-DC modes:
- 0 = Standby
- 1 = Precharge (`HV_On_Vorladen`)
- 2 = Buck (`Tiefsetzen`)

Byte 1 high nibble:
- 0x6 = normal
- 0xE = precharge active

### CRC

VAG CRC-8H2F (AUTOSAR, poly 0x2F, init 0xFF, xorout 0xFF).

The PDU constant is **appended** after the payload, not prepended:

1. CRC over `data[1:]` with init 0xFF, no final XOR
2. Continue CRC with PDU constant byte, final XOR 0xFF

PDU constants are from the [Battery-Emulator](https://github.com/dalathegreat/Battery-Emulator) project.

## Crash Lock

The DC-DC has a crash lock that prevents operation after a crash event is detected. This is stored as a protected DTC and cannot be cleared by a standard DTC clear (service 14).

The unit is not SFD protected. A UDS routine (0x0302) returns a positive response but does not clear the lock without additional preconditions.

Clearing the crash lock requires further investigation.

## Requirements

- Python 3
- python-can
- SocketCAN interface (`can0`)

## License

GPL-3.0
