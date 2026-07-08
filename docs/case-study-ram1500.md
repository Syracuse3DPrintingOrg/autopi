# Live sample: RAM 1500 (2024), on a real open-source DBC

Unlike the DT15 example (a placeholder DBC), this sample uses a **real**
reverse-engineered database: `chrysler_cusw.dbc` from comma.ai's opendbc (MIT),
which covers the Chrysler CUSW modules used by the RAM 1500 (2019-2024). Load it
from the Vehicles page ("Load" next to the RAM 1500 sample) or POST
`/examples/ram1500/load`.

## What is real here

- **Monitoring is fully real.** Bring up the Waveshare HAT (`can0`), connect to a
  RAM 1500, open the **Monitor** page, and pick this database: the real vehicle
  speed (`CLUSTER_1.SPEEDOMETER`), gear (`GEAR.PRNDL`), steering angle
  (`STEERING.STEER_ANGLE`), wheel speeds, doors, and seatbelt decode from the
  actual bus.
- **The steering-wheel keys are the real cruise/ACC buttons** (`CRUISE_BUTTONS`):
  Cruise On/Off, Resume, Set +/-, Cancel, and gap +/-.
- The PRNDL selector, turn-signal selector, and speed/tach controls drive a
  **cluster simulation** built from the real cluster messages.

## Sending: counter and checksum are computed

Chrysler messages carry a rolling **COUNTER** and a **CHECKSUM** that receiving
modules validate. AutoPi now computes both (the exact opendbc Chrysler
algorithm) when a message or simulation entry sets its checksum to `chrysler`,
which the RAM 1500 sample does. So a frame it sends carries a rolling counter and
a valid checksum, and a real cluster or ECU accepts it. This DBC does not include
proprietary infotainment/radio messages, capture those from the vehicle with the
Monitor page.

## Which bus

The RAM 1500 has several CAN buses; powertrain/steering/body signals here are on
one, and the infotainment head unit is on another. Put each on the correct
channel of the 2-channel CAN-FD HAT (`can0` / `can1`).

## Save and recall

Loading the sample saves the whole setup into the **RAM1500** profile, so you can
recall the entire bench in one click from the Vehicles page and switch between
vehicles.
