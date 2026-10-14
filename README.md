## VW MEB DC-DC Reverse Engineering
<img width="768" height="432" alt="dcdc" src="https://github.com/user-attachments/assets/890fcc1f-a5a3-4edc-9e93-c11e266e921e" />

Information on controlling the VW MEB DC-DC converter (Bosch Gen4H13, part 1EA907190G).

Tested on a bench with 12V supply and a Prius HV capacitor on the HV bus for precharge.

BMW PHEV Pack supplying 380V on HV side for standard DCDC 12V support.

**Requires CAN-FD.** The bus runs at 500 kbit/s nominal / 2 Mbit/s data. Standard CAN will not work.

## Wiring

<img width="672" height="837" alt="image-1-1" src="https://github.com/user-attachments/assets/1160886c-5d5e-4787-9fc7-5d76d3904086" />

## Hardware

- Bosch Gen4H13 DC-DC converter (diag address 0xB9)
- CAN-FD capable interface (Peak USB recommended)
- SocketCAN or [Tom-evnut's SavvyCAN fork](https://github.com/Tom-evnut/SavvyCAN/tree/fork-ci) (fork-ci branch has proper CAN-FD support)
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

### `meb_dcdc_replay.py`

Clears all DTCs including persistent ones (crash lock, HV interrupt). Self-contained replay of a verified clear sequence.

```bash
python3 meb_dcdc_replay.py
```

DTCs clear by ~frame 300 (~15 seconds). Power-cycle the unit afterwards.

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

### `meb_dcdc_replay.py`

Clears all DTCs including persistent ones (crash lock, HV interrupt). Self-contained replay of a verified clear sequence.

```bash
python3 meb_dcdc_replay.py
```

DTCs clear by ~frame 300 (~15 seconds). Power-cycle the unit afterwards.

## DTC Types

The DC-DC stores two categories of DTCs:

### Standard DTCs

Communication and operational faults that clear when the condition resolves or with a standard DTC clear (service 14). Examples:
- Lost communication with BMS
- Bus performance faults
- Voltage sensor range/performance

### Persistent DTCs

Protected faults that survive power cycles and standard DTC clears. These require specific vehicle conditions to clear:

| DTC | Code | Description |
|-----|------|-------------|
| Crash Lock | - | Latched after crash detection. Prevents operation. |
| P1BC300 | 0x54 0xED | HV interruption detected. Prevents operation. |
| P0E5600 | 0x0D 0x65 | Input voltage too low |

**Clearing persistent DTCs:**

The unit clears these when it sees a valid vehicle environment. No diagnostic session or clear command is required — just the right frames on the bus for ~15 seconds.

Minimum frame set (from verified log):

| ID | Name | Interval | Purpose |
|----|------|----------|---------|
| 0x3C0 | Klemmen_Status_01 | 100ms | Ignition (Kl15) on |
| 0x503 | HVK_01 | 100ms | Mode request |
| 0x5A2 | - | 500ms | Vehicle status |
| 0x6B2 | Diagnose_01 | 1000ms | Unlearn counter, odometer |
| 0x6B7 | - | 1000ms | - |
| 0x700 | Tester Present | 1000ms | Keep diagnostic session alive |

The `meb_dcdc_replay.py` script sends this exact sequence. After ~15 seconds, poll DTCs — all should be gone. Power-cycle to confirm they stay clear.

## Requirements

- Python 3
- python-can
- SocketCAN interface (`can0`) with CAN-FD enabled
- Or [Tom-evnut/SavvyCAN](https://github.com/Tom-evnut/SavvyCAN/tree/fork-ci) (fork-ci branch)

## License

GPL-3.0
