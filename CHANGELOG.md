# Changelog

All notable changes to AutoPi are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project follows
semantic versioning while pre-1.0 (staying in `0.x`).

## [Unreleased]

### Added

- **Find a control now tells you whether you found a command or just a status.** Each result is labelled: a "likely status" is what a module reports (replaying it usually does nothing), while a "likely command" appears mainly when you act on the control. A new "Verify effect" button proves it: AutoPi listens to every bus at rest, injects the candidate for a few seconds, and tells you whether anything on any bus actually reacted. If nothing reacts, you found a status and the real command is a different message, usually on another bus.

### Changed

- **Testing a found control no longer asks you to confirm first.** The Test button on the Signal Finder fires straight away so you can iterate quickly. It still only sends when you press it.

### Fixed

- **Find a control no longer lists streaming messages as false matches.** A message that carries a constantly changing value (a VIN or serial broadcast, a free running counter) used to show up as a strong match because its bytes change on every frame and so line up with anything you do. Those are now filtered out, so the list shows the controls that actually react to you.

### Fixed

- **A control you find now changes only its own bits, on the message that is live on the bus.** When you test a found control or add it to a cockpit, AutoPi used to replay the whole captured frame. That overwrote the other signals sharing that message and sent a stale value the vehicle usually ignored, which is why a found button often did nothing. Now it reads the message as it is on the bus right now and flips only the bits your control owns, leaving everything else untouched. On buses that protect messages with a rolling counter or checksum, more is still needed before the vehicle will accept the change.

### Added

- **Test a cockpit key without leaving the editor.** Selecting a key in the
  cockpit editor now shows a "Try it here" button next to its action binding.
  A one-shot action fires once per press; a periodic (toggle) CAN action shows
  whether it is sending right now and turns it on or off in place, so you can
  check a button does what you meant while you are still laying out the
  cockpit.

- **Filter and sort the CAN Monitor id list.** Type an arbitration ID (with or
  without the `0x`) or part of a decoded signal name into the new filter box to
  narrow the live table to just the frames you care about, and click the
  Arbitration ID, Count, or Last seen column headers to sort the list either
  direction.

- **The CAN Monitor highlights bytes that just changed.** When a frame's data
  updates, the bytes that differ from the previous frame flash amber for a
  moment, so you can press a button in the car and instantly see which byte
  moves on the bus.

- **One CAN Lab page with all five CAN tools in tabs.** Signal Finder, Monitor,
  Simulate / send, Firewall, and Diagnostics now live together under a single
  "CAN Lab" page, one click apart in tabs instead of six separate links. Each
  tool still opens on its own from the CAN Lab menu, and a tab only starts its
  bus when you first switch to it, so opening the hub does not wake all five at
  once.

### Changed

- **A much simpler, CAN-first navigation.** The top bar drops from eighteen items
  to seven: Home, Cockpit, CAN Lab (Signal Finder, Monitor, Simulate, CAN
  console, Firewall, Diagnostics), Databases, Vehicles, a Builder menu (the
  general-purpose actions, start menu, layout, automation, and test sequences,
  kept but tucked out of the way), and Settings. The home page now leads with what
  you actually do: find a signal, build a cockpit, watch the bus, manage
  databases, pick a vehicle.

### Fixed

- **"Test (fire)" and other actions right after a capture no longer fail.** A
  just-finished capture is now available the instant it is made, instead of only
  after its (sometimes slow) write to disk finishes, so firing a found message,
  cross-correlating, or adding it to the cockpit immediately after "Find a
  control" works reliably even on a busy bus.

### Added

- **Find a button and put it on the cockpit in a couple of presses.** In the
  Signal Finder's "Find a control", each result now has an "Add to cockpit"
  button: it turns the found message into a CAN-send button and drops it on a
  cockpit (existing or new) in one step, ready to press. The same button is on
  the save dialog for a bit-searched signal.
- **Send once or keep sending, with a suggestion.** When you add a found message
  to the cockpit, you choose whether the key sends it once per press (one-shot) or
  keeps sending it at a set rate and toggles on/off (needed for controls the ECU
  expects every cycle). AutoPi suggests which to use based on how often the
  message is already on the bus. A repeat rate is now a field on the CAN action
  driver too.

### Added

- **Auto cross-correlation: find proprietary copies of signals you already
  decode.** In the Signal Finder, one button checks every signal your active
  database already decodes against a capture and lists unknown fields that mirror
  them, often a higher-resolution proprietary copy ("this unknown 16-bit field on
  0x123 mirrors WHEEL_SPEED_FL"). No reference to record, no guessing which known
  signal to compare. Each match saves in one click.
- **Test a found message by firing it back.** Once you have found a signal (from
  "Find a control" or a bit search), a "Test (fire)" button replays a
  representative captured frame for that message onto the bus so you can confirm
  it does what you think. It asks first, since transmitting on a live bus is a
  real action.
- **Save a found signal into a new custom database on the spot.** The save dialog
  now has a "New custom database" option, so you can start a database for your
  vehicle straight from the Signal Finder instead of importing one first.

### Added

- **"Find a control" — the simple way to find a button or switch.** Press Start,
  operate the control a few times (tapping Mark or the spacebar each time), and
  the Signal Finder listens to every active CAN bus at once and shows the message
  that reacted to your presses, ranked, with the byte that changed. No reference
  sweep, no timing sync, and no need to know which bus the control is on. One
  click jumps to searching that message's bits.

### Added

- **Generic OBD2 decoder overlay.** A toggle on the Monitor decodes the standard
  OBD-II signals (vehicle speed, RPM, coolant, throttle, MAF, fuel level, ...) on
  top of whatever CAN database is active, since those diagnostics responses are
  the same on every vehicle and need no vehicle-specific database. Turn it on to
  read standard signals on any bus, alongside a proprietary database's signals.

### Added

- **A dedicated Databases page.** CAN databases now have their own page (in the
  top nav) instead of being buried on the CAN page. Each database is tagged with
  the vehicle it fits (make, model(s), years) plus source, author, and license,
  and you can filter the list to a saved vehicle. A built-in catalog of real
  open-source databases lets you import permissively-licensed ones (opendbc, MIT)
  in one click, or follow a link to sources we cannot redistribute and import
  them yourself. You can also import any database by URL or file and tag it, so
  non-open databases can be added on a device without being shipped in the
  software. Selecting a vehicle can now surface the databases that match it.

### Changed

- **The Signal Finder now shows when a reference is loaded and where to go next.**
  After recording a reference (or building one from a known signal), a clear
  "Reference loaded: N points, now press Survey the bus" banner appears on the
  Search step and the page scrolls to it, so the flow is no longer a mystery.

### Added

- **Signal Finder result plot.** Each signal candidate now has a Plot button that
  overlays the decoded candidate against your reference over time, so you can see
  at a glance whether they move together and confirm you found the right field
  instead of trusting the fit score alone.
- **The AI assist now uses your loaded CAN database as context.** When a database
  is selected, the interpret and name buttons tell the model which signals the
  vehicle already has decoded, so it suggests better names and does not re-propose
  signals you already know.

### Added

- **Use a known signal as the Signal Finder reference.** If a capture already
  contains a signal you can decode (OBD2 speed or RPM, or a signal you reverse
  engineered earlier), you can now pick it as the reference and skip the manual
  sweep or button-pressing entirely. It is decoded straight from the capture, so
  it is machine-accurate: pick the database and signal, press Use, and Survey.
  This is the precise "CAN-based reference" workflow, and the fastest way to find
  a proprietary signal that tracks something you can already read.

### Fixed

- **Captures on a busy CAN-FD bus no longer report "0 frames" when they actually
  captured thousands.** A short capture on a fast bus collects a lot of frames,
  and writing them all to the SD card could take longer than the capture's own
  stop timeout, so the result came back empty even though the frames were there
  (and every empty-looking attempt still grew the capture file, making the next
  one slower). Captures now hand back their frames from memory before writing to
  disk, and the on-disk capture history is capped, so a capture returns what it
  caught right away regardless of how big it is.
- **The Signal Finder capture now opens CAN-FD exactly like the "sniff" test
  does.** It resolves the interface's bitrate and CAN-FD setting from your saved
  config (and forces CAN-FD whenever the live link is CAN-FD) and passes them to
  the socket directly, instead of re-deriving them indirectly, so a capture can no
  longer open a classic socket on a CAN-FD bus and come back empty while the sniff
  on the same bus works. The "came back empty" message also stops citing a version
  number and instead suggests restarting the app if it was just updated.
- **A CAN-FD bus is now captured in FD mode even if the interface was saved with
  CAN-FD unticked.** A classic socket receives none of a CAN-FD bus's frames, so
  the Signal Finder and the monitor now open a link in FD mode whenever the live
  link is up in CAN-FD, regardless of the saved setting. This is what "frames are
  reaching the bus but none were read" pointed at.
- **Each CAN channel comes up with its own bitrate and mode, and it sticks.** The
  boot bring-up used to force one bitrate and CAN-FD mode on both HAT channels, so
  a mixed setup (say a 500k CAN-FD bus on one port and a 125k classic bus on the
  other) left the classic port down. It now brings each channel up the way you
  configured it in Settings, CAN Interfaces, and that survives a reboot.

### Changed

- **CAN interface speeds are a dropdown of standard rates, and the CAN-FD boxes
  only show when CAN-FD is on.** Setting up a bus no longer means typing raw bit/s
  by hand (an "Other" option is there for a non-standard bus), and a classic bus
  no longer shows data-bitrate and FD sample-point fields that do not apply to it.

### Added

- **Cockpits read from every CAN channel they use.** A cockpit can mix gauges
  bound to different buses (say engine data on one channel and body data on
  another), and the operate view now makes sure a monitor is running on each of
  those channels, so all the gauges get live data at once instead of only the one
  channel you happened to open the CAN monitor for.
- **The Signal Finder says why a live snapshot came back empty.** Instead of just
  showing nothing, it now reports whether the port was idle (no frames arrived,
  so your traffic is on the other channel), whether the bus was active but the
  frames arrived corrupt (receive errors climbing: a CAN-FD bit-timing or
  termination mismatch, e.g. a terminator jumper left on), or whether frames were
  arriving but not read (a CAN-FD versus classic mode mismatch), reading the
  interface's own counters, so you know which knob to turn.

### Fixed

- **The CAN HAT interfaces now keep the board's names.** The kernel used to name
  the Waveshare HAT's two ports in whatever order it found them, which often
  landed Linux "can0" on the board's CAN1 connector and vice versa, so the app,
  the monitor, and `ip` all disagreed with the label printed on the board. Setup
  now pins each name to its physical port, so can0 is the board's CAN0 connector
  and can1 is CAN1. Re-run the CAN setup and reboot once to apply it. This also
  fixes captures that "produced nothing" while the monitor saw traffic: they were
  running on the other, quiet port.
- **Captures on a CAN-FD bus set up outside the app no longer come back empty.**
  If a bus was brought up in CAN-FD mode by the boot service (not the in-app
  interface form), a capture on it opened a plain socket that never receives FD
  frames. The app now notices an FD link and opens it in FD mode either way.

### Added

- **Optional AI help in the Signal Finder.** Add an API key under Settings, AI
  Assist, and the Signal Finder can suggest a name, unit, and description for a
  signal it found, and interpret what a whole message is carrying, so you spend
  less time guessing what a candidate is. It works with Google Gemini (the
  default), Anthropic Claude, OpenAI, or a local Ollama server, and you can pick
  the model and add a note about the vehicle to sharpen the guesses. It is
  entirely optional: with no key the Signal Finder works exactly as before on
  statistics alone, and nothing leaves the device until you press one of the AI
  buttons.

### Fixed

- **Listen and Signal Finder no longer intermittently see "no frames" on a busy
  bus.** The Monitor, the Listen diagnostic, and captures were sharing one socket
  per channel, so a short read could come back empty when the Monitor was open or
  after the interface had been brought down and up. Each short read and each
  capture now uses its own dedicated socket (SocketCAN delivers every frame to
  each open socket), so they always see the traffic and never compete.

### Added

- **CAN bit-timing sample points, and a live error meter.** Each interface can now
  set a nominal and CAN-FD data sample point, applied by both the app's Bring up
  and the boot-time bring-up, so you can match a bus that needs a specific timing
  and have it persist across reboots (the driver default no longer keeps coming
  back). A new "Error meter" button on each interface watches the CAN error
  counters live and shows whether error-warn/error-pass are still climbing, so you
  can tune timing or termination and see the effect without SSH.

### Fixed

- **CAN-FD buses now actually receive frames.** A classic SocketCAN socket does
  not get a bus's CAN-FD frames from the kernel, and most of the app (the Monitor,
  captures, the Listen diagnostic) was opening channels in classic mode, so an
  all-FD bus looked silent ("no frames arrived") even when it was healthy and up.
  Every channel now opens using its configured fd and bitrate, so a CAN-FD
  interface is opened in FD mode everywhere, and a channel is reopened if its FD
  setting changes.

### Added

- **Signal Finder works on a live bus, with sweep and button reference capture.**
  Point it at a live channel (can0/can1/...), "Snapshot live bus" to see which
  arbitration ids are active before you hunt, and record the reference the way you
  interact with the vehicle: a Sweep slider for a continuous control (a volume
  knob) or a Button/spacebar press whose timestamps become a pulse the search
  matches to a toggling bit. The bus and the reference are captured together on
  the same clock, so they align automatically, then survey and bitsearch run on
  that live-captured data.

### Changed

- **Virtual cockpit: pick a gauge's signal from a searchable dropdown.** When you
  bind a cockpit gauge or indicator to a CAN database, the signal field is now a
  type-to-search dropdown of that database's signals (with the message and id
  shown), instead of a free-text box you had to fill from memory. Picking a signal
  fills in its arbitration id automatically.

### Added

- **Signal Finder: reverse-engineer an unknown CAN signal automatically.** Capture
  a bus, note a reference signal over time (sweep a control and record its value),
  and AutoPi finds the signal for you: a bit-activity survey flags counters and
  checksums, a correlation pass ranks which CAN ids track your reference, a
  bitsearch tries every start bit, length, byte order, and sign and scores each by
  how straight the fit is (preferring the shortest field), and a linear regression
  derives the scale and offset (rounded to realistic values). Save the result
  straight into a CAN database and decode it on the Monitor. This is the method
  from CSS Electronics' AI CAN reverse-engineering write-up, built in as a
  deterministic, offline tool.

### Added

- **CAN interfaces now show which Waveshare HAT port they are, plus live
  diagnostics.** The detected-interfaces list maps each kernel interface to the
  board's silkscreen port (the Waveshare HAT labels its two ports CAN0 and CAN1,
  which no longer match canN once a USB adapter shifts the numbering), shows the
  SPI device and receive/transmit packet counts, and each configured interface
  gets a "Listen 3s" button that reports how many frames arrived and which
  arbitration ids were seen. Zero frames tells you a bus is not reaching the
  interface even when it is up and self-tests fine, which is the quickest way to
  find a wiring or bitrate mismatch.

### Added

- **See the CAN interfaces on your device, and pick channels from a dropdown.**
  The CAN Interfaces settings now list every interface actually present on the
  device and what each one is (for example can0 = PEAK PCAN-USB, can1 = Waveshare
  CAN-FD HAT), with a Use button to fill the form, so you no longer have to guess
  channel names. The Monitor page's channel field is now a dropdown of those
  detected and configured channels, each shown with its purpose or adapter.

### Fixed

- **Waveshare 2-CH CAN FD HAT second channel: use the correct SPI bus (Mode A).**
  Per the factory wiki, the HAT's default Mode A puts the two channels on two
  independent SPI buses: channel 0 on SPI0-0 (interrupt 25) and channel 1 on
  SPI1-0 (interrupt 24) with spi1-3cs. The setup had the second controller on
  spi0-1, where no chip exists in Mode A, so it read all zeros and never probed.
  The setup now configures Mode A by default (and a CAN_MODE=b option for boards
  with the resistors moved to single-SPI mode).

### Fixed

- **Waveshare 2-CH CAN FD HAT second channel now initializes.** The CAN setup used
  the wrong interrupt GPIO for the second channel (24, which is the board's SPI1
  mode), so only the first channel came up. It now uses the factory SPI0-mode pin
  (spi0-1 interrupt 13, per the Waveshare 2-CH CAN FD HAT wiki), adds the factory
  restart-ms auto-recovery, and documents the SPI1-mode pins for boards jumpered
  that way.

### Fixed

- **Updates no longer break when an optional dependency will not build.** The
  container build now installs the core web app (which must succeed) and the
  optional or hardware libraries (python-can, cantools, gpiozero/lgpio, smbus2,
  pymodbus, and the diagnostics libs) best-effort with prebuilt wheels, so one
  package that has no wheel for the board (lgpio is the usual culprit) can no
  longer fail the whole image build or an on-device update. Each already degrades
  gracefully at runtime.
- **The Waveshare CAN-FD HAT is now enabled by the installer.** A Pi appliance
  install now runs the CAN HAT setup (the mcp251xfd overlay for can0/can1), which
  it did not before, so the interfaces exist after a reboot instead of showing as
  not detected. The setup also declares the oscillator explicitly (needed for
  CAN-FD timing), falls back to classic CAN if FD will not come up, and prints
  diagnostics; a "not detected" SocketCAN interface now explains how to enable the
  HAT and reboot.
- **Host-bridge update path.** Re-running the bridge installer now restarts the
  running daemon (so an update actually takes effect), and the out-of-date message
  points to the device update rather than only a restart.

### Added

- **Update from the Settings page.** The Updates pane now has an Update now button
  (and shows the host-helper version and whether it is out of date), so a device
  can be updated without SSH. The updater is also installed as a command, so
  'sudo autopi-update' works on the device.

### Fixed

- **PEAK PCAN (and Vector) now say why they will not connect.** Picking the pcan
  or vector backend used to show the interface as available even when it could
  not open, then fail a self-test with a generic error. The status and self-test
  now report the real reason. On a Raspberry Pi the usual cause is that a PEAK
  PCAN-USB is a SocketCAN device (can0/can1 via the peak_usb driver), not the
  pcan backend, which needs PEAK's separate PCAN-Basic driver; the message now
  says exactly that and points to the socketcan backend.
- **Clearer fix when the host-bridge is out of date.** Bringing a CAN interface
  up on an older device reported the bridge as out of date but only suggested a
  restart, which does not help when the bridge file itself is old. The message
  now points to the device update (which reinstalls and restarts the bridge), and
  re-running the bridge installer now restarts the running daemon instead of
  leaving the old one in place.

### Added

- **Kiosk hardening: rotation, idle blanking, and an on-screen keyboard.** The Pi
  kiosk installer now takes optional settings to rotate the display (90/180/270,
  for a portrait or inverted mount), blank the screen after a set idle time and
  wake it on touch, and show an on-screen keyboard for text entry on a touch-only
  bench. All are off by default, so nothing changes unless you turn them on, and
  the kiosk still runs if a helper tool is unavailable.

- **Point-and-click rule builder for GPIO and CAN cross-triggering.** The
  Automation page now builds logic rules without writing JSON: name an input (a
  CAN signal via database/message/signal, a GPIO pin, or a constant), pick a
  condition (compare, on/off, edge, on/off-delay timer, or latch), and choose the
  actions to fire, including CAN commands and relay, I2C, or Modbus outputs. So
  "when this CAN signal crosses a value, drive this output" and "when this input
  goes high, send this CAN command" are a few clicks. Start the scan loop and
  watch rules fire.

- **Stream Deck keys now match their on-screen tile.** A physical key's face
  now shows the same icon, label, and color the start menu and layout editor
  draw for it, so what you arrange on screen is what you see on the deck. A
  key whose icon can't be drawn falls back to a short abbreviation instead of
  going blank, and paging past a full deck shows which page pressing the
  paging key lands on. Key images scale to whatever deck is plugged in
  (Mini, original/MK.2, or XL).

- **CAN firewall and inhale/exhale.** Sit between two CAN buses and control
  traffic in flight: rules match by arbitration id (exact, mask, or range) and an
  optional decoded-signal comparison, and allow, block, rewrite (change a signal
  and re-encode with the checksum recomputed), or inject frames, in either
  direction. Inhale captures a bus into a named recording; exhale replays it to
  the other side at the original pace, optionally through the same rules. A new
  Firewall page manages the rules, starts and stops the gateway with a live
  forwarded/blocked/rewritten count, and runs captures.

- **Virtual cockpit: design your own dashboard.** Upload a photo of your
  dashboard (or any background art) on the new Cockpit page, then place keys
  and gauges directly on top of it: a key runs any action with a tap, a
  gauge or indicator reads a live CAN signal and updates in real time. Every
  element scales with the image, so a layout built on a phone looks right on
  a full-screen kiosk display too. Open a cockpit's kiosk view for a
  full-screen, chrome-free operate screen.

- **Toyota, Honda, and Hyundai samples on real open-source DBCs.** Three more
  vehicle examples built on real opendbc data (MIT): a 2024 Toyota RAV4
  (toyota_nodsu_pt), a 2022 Honda Civic (honda_civic_ex), and a 2024 Hyundai
  Elantra (hyundai_canfd, the shared Hyundai/Kia/Genesis CAN FD database).
  Monitoring is fully real, and each OEM checksum is computed and verified
  against a reference (Toyota's trailing byte, Honda's shared nibble, and
  Hyundai CAN FD's CRC-16), so their checksum-protected messages send valid
  frames a real module accepts.

- **Ford F-150 (2024) sample on the real Ford CAN-FD DBC.** A fourth vehicle
  example uses the real ford_lincoln_base_pt.dbc from opendbc (MIT), which covers
  the modern Ford CAN-FD platform (F-150, Mustang Mach-E, Explorer, Bronco Sport,
  Maverick, and more). Monitoring is fully real: connect over the HAT and the
  actual vehicle speed, gear, engine RPM, wheel speeds, and steering angle decode
  from the bus. Ford protects messages with per-message counters and checksums,
  so this sample is read-focused; if you have FORScan definitions or captures for
  a specific truck, import them on the CAN page to extend it.

- **Set up and test the CAN hardware from the app.** The CAN Interfaces settings
  now bring an interface up or down (bitrate and CAN-FD data bitrate), show a live
  health badge (up/down, bus-off or error-passive, and error counts), run a
  loopback self-test, and send a test frame, so you can confirm each bus is live
  and correctly wired. Give each bus a purpose (Powertrain, Infotainment, Body,
  Diagnostic) and that name shows everywhere you pick a channel, so you always
  know which network is which. Bring-up runs through the on-device host helper;
  off-device it shows the exact command to run instead.

- **A builder overview dashboard.** Opening the app on a computer now lands on an
  overview that orients you: the active vehicle, your CAN interfaces and their
  status, quick tiles for the main jobs (monitor, console, arrange keys, run a
  test, import a DBC, operator screen), and recent activity with the last test
  result. The navigation was tidied to follow the setup flow.

- **Alfa Romeo Giulia (2024) sample on a real open-source DBC.** A third vehicle
  example uses the real fca_giorgio.dbc from opendbc (MIT), covering the
  Stellantis Giorgio platform (Alfa Romeo Giulia and Stelvio, Maserati Grecale).
  Monitoring is fully real: connect over the HAT and the actual wheel speeds,
  steering angle, engine RPM, and ACC HUD speed decode from the bus. Its
  checksum-protected messages send a valid J1850 counter and checksum so a real
  module accepts them.

- **Two ways to use it: an operator screen and a builder.** The Raspberry Pi
  runs standalone with a simple, large-touch Operator screen (the active vehicle,
  its key grid, and a full-screen test runner with pass/fail confirms), while a
  browser on a PC gets the full builder. The app picks the right one by context:
  on the device it opens the operator screen, a remote browser opens the builder,
  and either is one tap from the other. Set a fixed preference under Settings >
  Display & Kiosk if you want.
- **Profile sync from a server (groundwork).** A Profile Sync settings pane lets
  a device point at a central server and pull vehicle profiles (with their
  databases, keys, layout, simulation, and sequences). This is future-facing: it
  stays quiet until you have a server to point it at.

- **Automated test sequences.** A new Tests page lets you build a sequence of
  steps, send a CAN command, assert a specific CAN response arrives within a
  timeout (matched by id and an optional decoded-signal comparison), pause to
  ask the operator to confirm pass/fail, run an action, or delay, and then run it
  step by step with live status and a final report. Results are recorded to the
  SD-card log (each step and the overall result), so a run leaves an auditable
  trail. Sequences are saved and can be tied to a vehicle profile.

- **A logging journal on the device.** A Logs page records what the device
  does (actions run, and later test steps and results) to daily files on the
  SD card, with a live event view, a file list you can download, a clear
  button, and a retention setting in Settings under Logging.
- **Live RAM 1500 (2024) sample on a real open-source DBC.** A second example on
  the Vehicles page uses the real chrysler_cusw.dbc from comma.ai's opendbc
  (MIT, vendored with attribution), which covers the RAM 1500 (2019-2024). Its
  monitoring is fully real: connect over the Waveshare HAT and the actual speed,
  gear (PRNDL), steering angle, wheel speeds, doors, and seatbelt decode from the
  bus. The steering-wheel keys are the real cruise/ACC buttons, and a PRNDL /
  turn-signal / speed selector drives a cluster simulation. Sending to
  checksum-validated modules still needs the Chrysler counter/checksum computed
  (a follow-up); reading is unaffected. See docs/case-study-ram1500.md.
- **DBC import tolerates real-world quirks.** The importer now falls back to
  lenient parsing, and encode fills unset signals with defaults, so real DBCs
  (like opendbc's) import and a command key that sets one signal still encodes.

- **DT15 case study: a full RAM DT bench you can load in one click.** A complete
  worked example on the Vehicles page loads the DT15 profile (2025 RAM DT, VIN,
  Atlantis High) with media/ICS keys, steering-wheel media keys, an adjustable
  vehicle-speed signal, a PNDL (P/R/N/D/L) selector, an ignition (Off/Accy/Run/
  Start) selector, a Stream Deck/start layout, and a running instrument-cluster
  simulation. The selectors update the live periodic broadcast, so a connected
  cluster follows the gear, ignition, and speed you pick. See
  docs/case-study-dt15.md.
- **A vehicle is a recallable test bench.** Save the whole current setup
  (databases, keys, layout, and simulation) into a profile, and recall it in one
  click from the Vehicles page. Switch vehicles by recalling; the databases are
  matched by name and remapped so keys keep working.
- **Automotive diagnostics (ISO-TP, UDS, OBD-II).** A Diagnostics page runs UDS
  services (session, tester present, read/write DID, routine control, read DTCs)
  and OBD-II PID reads over ISO-TP, built on the MIT libraries can-isotp and
  udsoncan, simulating when no bus is present.

- **Multiple CAN interfaces: PCAN, Vector, and a virtual bus.** Beyond the
  Waveshare SocketCAN default, AutoPi can now talk to PEAK PCAN and Vector
  hardware through python-can's backends, and a built-in virtual bus lets you
  build and test without any hardware. A new CAN Interfaces settings pane
  configures each channel's backend, bitrate, and CAN-FD data bitrate. LIN and
  automotive Ethernet (DoIP) have marked extension points for later.

- **Phase 3 start: closing the loop between inputs and CAN, plus more I/O.** A
  logic runtime runs your rules on a live scan loop: inputs (a CAN signal
  decoded from a database, a GPIO pin, or a constant) drive the rules, which
  fire actions. So a CAN signal can switch an output, or a physical input can
  send a vehicle CAN command. Start, stop, and single-step it from the
  Automation page. Three new I/O drivers join the action library: a relay-board
  driver (active-low by default, for relay HATs), an I2C device driver
  (read/write a register), and a Modbus TCP driver (read/write coils and
  registers). Each simulates when its hardware or library is absent, so keys are
  buildable and testable on a bench.

- **Live CAN bus monitor.** A new Monitor page shows frames arriving on a
  channel in real time (arbitration id, how many times it has been seen, the
  latest data), and decodes them into named signals when you pick one of your
  CAN databases. Start and stop the capture per channel; it degrades cleanly to
  "not live" when there is no bus.

- **The app now warns when the host-bridge is out of date.** The bridge reports
  a version; the app compares it and, if the running bridge is older than
  expected (updated on disk but not restarted, which broke Wi-Fi with a cryptic
  error), shows a clear banner in Network settings telling you to run
  `sudo systemctl restart autopi-host-bridge`. `GET /system/bridge` reports the
  running and expected versions.

### Fixed

- **Logic runtime kept edge/timer/latch state across scans.** The scan loop
  rebuilt its engine every cycle, which wiped timer, edge, and latch memory so
  those condition types never worked live; the engine is now kept alive and only
  its rules refresh each scan.

- **Wi-Fi and other host features no longer show a bare "not found" after an
  update.** The host-bridge is a long-running service, so replacing its file on
  disk during an update does not change the running process; if its restart did
  not fire, the old bridge kept serving and the new Wi-Fi routes returned 404.
  The updater now restarts the bridge reliably (with a fallback if systemd-run
  is unavailable, and it re-enables and clears any failed state), and the app
  now shows an actionable message ("the host-bridge is out of date, restart it")
  instead of "not found" when the bridge is behind.

### Fixed

- **Wi-Fi scan (and update, reboot, deck restart) now work on the Pi.** These
  said "Only available on a Raspberry Pi appliance" even on a real Pi, because
  the check ran inside the container, which cannot see the Pi's device-tree.
  They now gate on whether the host-bridge answers (the bridge does the work and
  only runs on a Pi appliance), which is the correct signal, and Pi detection
  also reads /proc/cpuinfo so it works from inside the container.

### Fixed

- **Stream Deck and start settings save reliably now.** Settings are re-read
  from disk on every request, so a saved rotation, brightness, model, or the
  start-page toggle no longer appears to revert (the settings object was loaded
  once at startup, so a second worker process could serve stale values). The
  health page now also reports the data directory and whether it is writable, to
  make a stuck save easy to diagnose.

### Fixed

- **The Stream Deck keeps its keys through an update, and recovers on its own.**
  The controller now reads its key layout straight from the app's data files on
  the device, so a deck no longer blanks or loses its keys while the app
  container restarts during an update, the way it did before. Combined with the
  in-process recovery, a plugged-in deck reconnects by itself. Updating a device
  also rewrites the deck's service so a previous crash loop can no longer wedge
  it: the service is told never to give up, and its failed state is cleared on
  update.

- **Changing keys no longer wedges the Stream Deck.** The controller only
  caught network errors, so a transient USB write failure while repainting the
  new layout crashed the process, and systemd relaunched it straight back into
  the same crash, which is why a manual restart did not recover it. The loop now
  never exits on a deck or paint error: it re-opens the deck in-process (like
  the source project), paints defensively per key, and its service never gives
  up after a burst of restarts.

- **Updating a device now actually applies host-side fixes.** The OTA updater
  overwrote itself but kept running the old copy, so changes to the updater (like
  GPIO passthrough) never took effect on the update that shipped them. It now
  re-executes the fresh copy after pulling, syncs the Stream Deck controller and
  the compose override separately from the Docker image (the image never carries
  them), recovers a diverged checkout, and reports whether anything changed. This
  is why the Stream Deck and GPIO fixes did not take on the last update.
- **The Stream Deck controller now actually runs.** It was importing the app's
  paging code from a path that does not exist once the controller is installed
  on its own, so it crashed on startup and never connected. The controller is
  now fully self-contained, like the source project's, so a plugged-in deck
  comes up and shows your layout.
- **GPIO keys work on the start menu and the deck.** The demo lamp, fan, and
  door keys did nothing because the app runs in a container with no access to
  the Pi's GPIO and no pin backend installed. The installer (and updater) now
  map the board's GPIO devices into the container and the image ships the lgpio
  backend, so GPIO actions drive real pins. A blank start page left over from
  an earlier build now re-seeds its demo keys on update.
- **Stream Deck rotation, brightness, and Restart now work from the web
  editor.** The app runs in a container and cannot restart the host service, so
  Restart used to report "No Stream Deck service on this host." The controller
  now pulls the rotation and brightness you set in the editor on each check and
  applies them to a live deck without a restart, and Restart is a request the
  controller honors by reconnecting itself. When a deck is connected, Restart
  reports "Reconnecting the Stream Deck."

### Added

- **Vehicles, CAN simulation, and Wi-Fi configuration.** Three more sections of
  the platform go live. **Vehicles**: create vehicle test profiles (year, make,
  model, one or more VINs) and pick an active one; Stellantis **Atlantis High**
  and **Atlantis Mid** are seeded to start from (infotainment focus).
  **Simulate**: a CAN transmit list of periodic (cyclic) and one-shot frames,
  each raw hex or encoded from a DBC signal set, with a scheduler you start and
  stop. **Wi-Fi**: the Network settings pane scans for networks and joins one
  (on a Pi appliance), and the fallback access point now actually serves the
  app (a captive redirect sends `http://192.168.99.1` to the app), fixing the
  hotspot that reached nothing before.

- **The platform is now visible and usable in the app, not just the API.** New
  top-nav sections put the tools one click away: a **CAN** console and an
  **Automation** page. The CAN console lists your imported CAN databases,
  uploads a DBC file or bulk-imports opendbc, browses each database's messages
  and signals, and decodes a raw frame into named values or encodes signal
  values and sends them, plus a raw-frame sender and live interface status. The
  Automation page lists your logic rules and does database backup and restore
  (download the whole database as a file, import it back without wiping data).
  Settings now links across to CAN, Automation, and the layout editor.

- **Import open-source CAN databases (DBC), and decode/encode frames.** AutoPi
  now speaks DBC, the format the open-source CAN world ships its message and
  signal definitions in. Upload any DBC file, or pull comma.ai's opendbc
  collection (the largest open set of vehicle databases) onto a device with
  `scripts/import-opendbc.sh`. Each imported database is stored locally with its
  messages and signals, and records where it came from and under what license,
  so open-source content stays attributable. Frames decode into named signal
  values and encode back, built on the cantools library. New endpoints under
  `/can` list databases and decode/encode. A LICENSING.md now tracks every
  dependency's license and what it means for shipping AutoPi as a proprietary
  product (notably python-can under the LGPL, and that CAN database content
  carries its own licenses separate from the code).

- **Phase 2 foundations: a database, a CAN core, and a logic engine.** Three
  building blocks toward turning AutoPi into a full test and automation
  platform. A locally-hosted SQLite database (under the data directory) stores
  actions, vehicle profiles, CAN message/signal definitions, and logic rules,
  with whole-database and per-profile import and export at `/db/export` and
  `/db/import`. A CAN core built on python-can with a backend-independent frame
  model and provider abstraction: the socketcan backend and a bring-up script
  for the Waveshare 2-Channel CAN-FD HAT (`can0`/`can1`) are in, and the CAN
  action now sends real frames when an interface is present and simulates
  otherwise. A PLC-like logic engine evaluates rules (comparisons, boolean
  inputs, rising/falling edges, on-delay and off-delay timers, set-reset
  latches, combined with AND/OR/NOT) on a fixed scan cycle, viewable at
  `/logic/rules`. Each is pure and heavily tested; wiring them together (rules
  driven by CAN signals, DB-backed actions, vehicle profiles) follows.

- **Raspberry Pi appliance platform (host-bridge + appliance compose).**
  Following the Pi appliance blueprint, a small root helper (the host-bridge on
  127.0.0.1:9299) now performs the privileged host operations the container
  cannot: OTA update, reboot, restarting the Stream Deck service, and reading Pi
  power/thermal/disk health. The app runs with host networking on a Pi so it can
  reach the bridge, relays those operations to it with a shared token, and
  degrades to a clean no-op on a plain server.
- **Visual Stream Deck and Start Page editor.** Drag keys from a categorized
  library onto a deck-shaped grid. The grid scales to the selected model (Mini
  6, MK.2 15, XL 32) or, when a Stream Deck is plugged in and its controller is
  running, to the real deck automatically. Rotation reshapes the grid, and a
  layout longer than the deck paginates with a wrapping "More" key. Set the
  model, rotation, and brightness, then save the deck settings and both layouts
  at once. A connected badge shows which deck reported in.
- **A real interface, matching the look and feel it was spun out from.** The
  start menu, layout editor, and settings now use the same Bootstrap dark theme
  and icons, with a blue accent. The settings page is a sectioned menu
  (Appearance, Start Page & Stream Deck, Display & Kiosk, Network, Actions,
  Home Assistant, Security, Updates, Advanced) with search, one click to any
  section. A fresh install seeds a handful of demo keys (a lamp, a fan, a door
  pulse, a ping, a status check, a webhook, and an "all on" macro) onto both
  the start menu and the Stream Deck so the grid is populated out of the box.
- **On-device updater.** `autopi-update` pulls the latest source, rebuilds the
  stack, and refreshes the Stream Deck controller, run over SSH.
- **One-line install on a Raspberry Pi.** Flash Raspberry Pi OS Lite, SSH in,
  and run a single `curl ... | bash` line. It detects the Pi, a display, and a
  Stream Deck, installs Docker if needed, brings up AutoPi, and on a Pi
  appliance also sets up the kiosk display, the Stream Deck controller, and a
  Wi-Fi access point fallback. The same line installs the stack on a plain
  Debian or Ubuntu server.
- **First cut of the AutoPi control surface.** A web start menu and an
  optional Stream Deck share one layout of keys. Each key runs an action you
  define: toggle or pulse a GPIO pin, run a shell command, or call another
  application over HTTP. Arrange the keys by dragging them in the layout
  editor. The app runs standalone over its own Wi-Fi access point or on your
  network, and on a plain server with no Pi attached (the hardware drivers
  no-op cleanly when there is nothing to drive).
