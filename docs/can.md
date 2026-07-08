# CAN bus

AutoPi's CAN support lets an action send a frame onto a vehicle's CAN bus,
the same way a GPIO action drives a pin or an HTTP action calls another
application. This page covers getting the hardware recognized and picking a
backend; creating and running CAN actions works like any other action,
through the drag-and-drop editor.

## Supported hardware

The default and first-supported board is the **Waveshare 2-Channel CAN-FD
HAT**. It carries two MCP2518FD controllers wired over SPI, and once its
driver is loaded, Raspberry Pi OS presents each one as an ordinary Linux
network interface: `can0` and `can1`. AutoPi talks to both through
[python-can](https://python-can.readthedocs.io/)'s `socketcan` backend, which
means any other adapter that shows up the same way (a USB-CAN dongle, a
different MCP2518FD carrier board) works too, without any code changes.

AutoPi also supports other CAN test equipment through python-can's other
backends, no extra dependency needed:

- **PEAK PCAN-USB** adapters, over the `pcan` backend.
- **Vector** interfaces (VN1610, VN1630, and similar), over the `vector`
  backend. These need Vector's XL Driver Library installed on the host.
- **Virtual**, an in-process loopback bus with no hardware at all, useful
  for building and testing an action layout before any adapter is plugged
  in.

Configure which backend, channel, and bitrate each interface uses on the
**CAN Interfaces** settings page. A channel you never configure there falls
back to SocketCAN at 500 kbit/s, so the Waveshare HAT keeps working with no
extra setup.

### Not yet supported: LIN and automotive Ethernet (DoIP)

**LIN** (Local Interconnect Network, the low-speed single-wire bus behind
things like window and mirror switches) and **DoIP** (Diagnostics over IP,
used for UDS diagnostic sessions over automotive Ethernet on newer
vehicles) are not implemented. python-can has no LIN backend at all, and
DoIP isn't a CAN backend in the first place, so both need a different
integration than the `CanProvider` used here.

The extension points exist in code as stubs
(`service/app/can/lin.py`, `service/app/can/doip.py`), always reporting
unavailable, so where this support will land is visible without hunting
through the roadmap. A DoIP implementation would most likely use the
MIT-licensed [doipclient](https://github.com/jacobjrose/doipclient)
library.

## Bringing up the HAT

1. Attach the HAT to the Pi's 40-pin header and power the Pi off before doing
   so.
2. Boot the Pi and run the setup script from the AutoPi checkout:

   ```bash
   sudo scripts/image-build/setup-can-waveshare.sh
   ```

   This enables SPI, adds the `mcp251xfd` overlay for both controllers to the
   boot config, and installs a small service that brings `can0` and `can1` up
   at every boot with a 500 kbit/s arbitration bitrate and a 2 Mbit/s CAN-FD
   data bitrate.
3. Reboot. After the Pi comes back, confirm both interfaces are up:

   ```bash
   ip -details link show can0
   ip -details link show can1
   ```

   Each should report `state UP` and the bitrate you configured.

### Choosing a different bitrate

Most vehicle networks run at 500 kbit/s, but pass a different value if yours
doesn't:

```bash
sudo CAN_BITRATE=250000 CAN_DBITRATE=1000000 scripts/image-build/setup-can-waveshare.sh
```

Re-running the script is safe: it only adds what is missing from the boot
config and always re-applies the bitrate.

### Classic CAN only

If your bus doesn't use CAN-FD, turn FD off and the data bitrate is ignored:

```bash
sudo CAN_FD=false scripts/image-build/setup-can-waveshare.sh
```

## Creating a CAN action

Add an action with the `can` driver from the layout editor and fill in:

- **Interface**: `can0` or `can1` (whichever the HAT channel is wired to).
- **Arbitration ID**: the frame's CAN id, in hex (`0x7DF`, for example).
- **Data bytes**: the payload, in hex, space or comma separated
  (`02 01 0C`).
- **CAN-FD frame**: on if this frame should use the FD payload and framing.
- **Extended (29-bit) id**: on if the id is a 29-bit extended id rather than
  the usual 11-bit standard id.

Running the action sends that frame on the chosen interface. If no HAT is
attached (or you're running AutoPi on a plain server), the action still
runs: it validates the frame and reports what it would have sent, so you can
build and test a layout before the hardware is in the loop.
