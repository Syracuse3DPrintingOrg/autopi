# Case study: DT15, a 2025 RAM DT (Atlantis High) test bench

This is a complete, working example of using AutoPi as a bench for a vehicle's
radio, display, and instrument cluster over the Waveshare 2-Channel CAN-FD HAT.
Load it in one click from the Vehicles page ("Load" next to "DT15"), or POST
`/examples/dt15/load`.

Profile: **DT15**, 2025 RAM DT, VIN `1C6RRFFG9SN513894`, platform Atlantis High.

## What it sets up

- A vehicle profile (year/make/model/VIN, platform, interfaces).
- An example CAN database (DBC) with the messages used below. This is an
  example layout, not the vehicle's real proprietary definitions; import the
  real DBC on the CAN page and repoint the keys when you have it.
- A Stream Deck / start-menu layout of keys.
- A running instrument-cluster simulation: periodic CAN broadcast the real
  cluster reads.

## The keys

- **Media / ICS**: Play/Pause, Next, Prev, Vol +/-, Mute, Source, Power, sent to
  the radio as `ICS_Command` frames (the `can_command` driver).
- **Steering-wheel media**: Vol +/-, Next, Prev, Mode, Voice, Mute as
  `SWC_Media` frames.
- **Vehicle speed**: presets (0/30/60/100 km/h) and +5/-5 keys. These set the
  `Speed` signal on the periodic `VehicleSpeed` message, so the cluster follows.
- **PNDL selector**: P/R/N/D/L set the `Gear` signal on the periodic
  `Transmission` message.
- **Ignition selector**: Off/Accy/Run/Start set `IgnState` on the periodic
  `IgnitionStatus` message.

The speed, PNDL, and ignition keys use the `sim_set` driver, which updates a
running simulation entry, so selecting a gear or turning the key changes what
the cluster shows in real time. The media and steering-wheel keys are momentary
commands sent once to the radio.

## Simulating the instrument cluster

The Simulate page holds the periodic transmit list: `VehicleSpeed`,
`Transmission`, `IgnitionStatus`, `Cluster_Engine` (RPM), and `Cluster_Status`
(fuel, coolant temp). Start the scheduler to broadcast them on `can0`; the real
cluster reads them. Adjust any value there directly, or drive them with the
selector keys.

## Saving and recalling a vehicle

The whole setup (databases, keys, layout, and simulation) is saved into the DT15
profile as a bundle. On the Vehicles page, **Recall** reloads a vehicle's entire
bench in one click, and **Save** captures the current setup into a profile. Build
DT15, tune it, save it, then do the same for the next vehicle and switch between
them by recalling.
