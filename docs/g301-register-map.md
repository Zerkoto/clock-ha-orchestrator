# TCL G301 Version G Register Map

Source baseline: TCL Protocol Converter Unit-based centralized control Modbus
protocol, Version G, dated 2025-06-27.

## Confirmed Transport

- RS-485 Modbus RTU.
- 9600 bps, 8 data bits, no parity, 1 stop bit.
- Read holding registers: function `0x03`.
- Write single register: function `0x06`.
- Write multiple registers: function `0x10`.
- Protocol converter slave addresses are DIP-switch configured in the confirmed
  range `1-255`.

## Indoor Unit Control Registers

The range `0x0201-0x021A` is documented as readable/writable control data.

| Register | Purpose | Encoding |
| --- | --- | --- |
| `0x0201` | Power | `1` on, `0` off |
| `0x0202` | Mode | `1` cool, `2` dry, `3` fan, `4` heat, `5` auto |
| `0x0203` | Set temperature | transmitted value = `10 * C`, range `160-310` |
| `0x0204` | Fan speed | `1` auto, `2-7` low through ultra-high |
| `0x0214` | Mode limitation | `0` none, `1` heat prohibited, `2` cool/dry prohibited |
| `0x0215` | Upper temperature limit | Celsius integer, range `26-31` |
| `0x0216` | Lower temperature limit | Celsius integer, range `16-25` |
| `0x0219` | New iFeel switch | `1` on, `0` off |
| `0x021A` | Indoor ambient injection | transmitted value = `10 * C + 1000`, range `0-50 C` |

## Indoor Unit Readback Registers

| Register | Purpose | Encoding |
| --- | --- | --- |
| `0x030E` | Capability bits | bit 0 up/down swing through bit 7 access control |
| `0x030F` | Power status | `1` on, `0` off |
| `0x0310` | Operating mode | same mode values as control register |
| `0x0311` | Fan status | fan-speed status values |
| `0x0315` | Access control switch status | `0` unavailable, `1` closed, `2` open |
| `0x0318` | Ambient temperature | transmitted value = `10 * C + 1000` |
| `0x0321` | Indoor malfunction flag | `1` fault, `0` normal |
| `0x0322` | Indoor fault bits | decoded in `app.g301_adapter.registers` |

## Implementation Boundary

The repository currently implements only offline codecs, planning, readback
comparison and simulation. Live gateway transport, polling intervals, write
ordering under real bus contention and final room-to-slave assignment must wait
for bench commissioning.

The offline contract verifies power and mode against actual status registers:

| Control write | Verification read |
| --- | --- |
| `0x0201` power | `0x030F` actual power |
| `0x0202` mode | `0x0310` actual operating mode |
| `0x0203` setpoint | `0x0203` accepted setpoint |
| `0x0204` fan | `0x0311` actual fan status |

Enabled intents first read `0x030E` and `0x0214-0x0216`. Invalid mode
limitations or device temperature bounds reject the intent before any write.
Readback is deliberately retryable because status may lag command acceptance.
