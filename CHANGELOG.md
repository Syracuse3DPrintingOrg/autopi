# Changelog

All notable changes to AutoPi are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project follows
semantic versioning while pre-1.0 (staying in `0.x`).

## [Unreleased]

### Added
- **The dashboard camera can read the value on the device now, without the AI (and much faster).** Reading a number no longer has to go to the vision AI every couple of seconds. A local reader on the AutoPi box reads the cropped number in a fraction of the time, for free and offline, and because it is fast it takes many more readings so the search has more to work with. A Read with control lets you choose: on-device with the AI as backup (the default), on-device only, or AI only. On-device reading is best on a clear digital readout and falls back to the AI when it is unsure, so a fancy graphical cluster still works.

- **Crop the dashboard camera to just the value you want read.** A cluster that shows speed, RPM, gear, and temperature at once could send the AI reading the wrong number. Drag a box on the camera preview around only the value to read, and every frame is cropped to that box before it is read, so the reference tracks the number you meant. A Clear crop button goes back to reading the whole frame.

### Fixed
- **Unplugging the USB camera no longer takes the whole app down.** On a Pi the camera was passed through in a way that required it to be attached every time the app started, so unplugging it left the web page unreachable until you fixed it over SSH, and a reboot could not recover on its own. The camera is now granted in a way that does not depend on it being plugged in: the app starts either way, and it picks up a camera the moment you connect one, with no restart.
- **The dashboard camera crop box stays where you draw it.** While you were dragging a box around the value, the live preview refreshing in the background could make the selection jump to a thin sliver. The box now holds its position through a preview refresh, and the preview pauses while you are drawing.

- **The dashboard camera reference lines up with the capture now, and low-quality references are caught instead of guessed.** Each reading is timed to the moment its frame was grabbed, not the couple of seconds later when the AI answered (that delay varied per reading and smeared everything out of alignment). The readings are shown live as they come in, so you can see the value tracking your sweep. And when a search finds nothing, it now says why (too few readings, the value never changed, no CAN frames on the channel, or nothing tracked) instead of a generic message, and a flat reference no longer produces a confident but bogus match.


### Fixed
- **The signal finder now reports the real field's position and scale, not a look-alike.** When you match an unknown CAN field to a reference, several bit windows can fit almost identically (a real field always has near-identical shifted or truncated twins). The finder was picking whichever fit by a hair, so it often showed a field shifted a few bits over with an odd scale like 0.16 instead of the true 0.01. It now breaks those near-ties toward the field a real device would use (a sensible scale, a byte or nibble aligned start, the higher-resolution read), so the start bit and scale it shows are the ones worth saving. One-pass auto-decode also sweeps a small reaction-delay range by default, so a reference you logged a beat late still lines up.
- **Acting on a found control now works reliably.** After the Signal Finder turns up a candidate, using Bits, Test, or Verify on it could quietly do nothing or fail: the hunt's recording is kept in memory (so a busy bus does not thrash the device storage) and later steps could drop it or clear the capture selection. The recording is now held for the whole hunt and stays selected, so every follow-up action finds it.
- **A recording that fails to start now says so.** If a reference recording could not begin (an unknown mode, or a bus already being recorded), the page showed "Recording and capturing..." as though it had worked. It now reports why it could not start instead.
- **Find a control now catches commands that only appear when you act, even when you tap Mark a beat late.** The press-and-mark hunt already handles a control's byte changing before your tap; this extends the same latency allowance to messages that show up only while you operate the control (a command another module emits on trigger), so a mark landing a fraction of a second after the press no longer makes the message look like it was already there and drops it.

- **The on-device camera preview is no longer black, and phantom camera entries are gone.** A webcam hands back a dark first frame before it auto-exposes, so the preview showed black; AutoPi now skips the first frames so you get a real picture. It also lists only cameras that can actually capture, so the extra metadata node a webcam exposes (which showed as a broken image) no longer appears. And a flaky package mirror during a device update can no longer stop the whole update just because the camera tool would not install.

### Fixed

- **The on-device camera now actually finds your USB camera, with a live preview to aim it.** The app runs in a container that could not see a camera plugged into the device, and it had no tool to grab a frame, so the device-camera list came up empty. Now the app image ships fswebcam, a Pi appliance passes any plugged-in camera through automatically, and the plain server compose has a ready-to-uncomment camera block. The Dashboard camera's device option shows a live preview so you can aim it at the dashboard before you start, and when a camera still is not usable it tells you the exact fix (grant the container access, or rebuild the image for the capture tool) instead of a blank list.

### Added

- **The Dashboard camera can now use a USB camera plugged into the AutoPi box.** The reference recorder's camera mode has a new source choice: your browser's camera (as before), or a camera on the AutoPi device itself. Pick the device option and AutoPi grabs the frames on the box (with ffmpeg or fswebcam, whichever is installed) and reads the dashboard value from there, so it works over a plain http address, with no camera permissions to grant, and the readings line up with the live capture on the device's own clock. If no camera or capture tool is found, the page says exactly what is missing.

### Fixed

- **The Dashboard camera explains itself instead of failing cryptically.** Browsers only allow camera access on a secure page (https, or the device's own screen at localhost), so over a plain LAN address the camera could not open and showed a confusing error. It now tells you plainly what is needed, and it no longer leaves a reference recording running with no camera. And when the browser cannot open a camera at all, the new on-device option is offered right in the message.
- **Find a control now reliably catches the button you press.** The detection assumed the CAN change happened after you tap Mark, but people tap a beat after acting, so the control's byte had usually already changed and the search missed most presses (a real button often scored something like 2 out of 8 and got buried, or was mislabelled a "status"). It now looks at a window centred on each mark and measures how far a byte moves from its resting value, so a control you operated on every press reads that way. It also labels a byte that is quiet except when you act as a likely command even when its message is broadcast every cycle, instead of calling it a status.
- **Settings search now finds settings, not just section names.** Typing in the settings search box now matches the actual settings inside each section (so searching "theme", "bitrate", or "brightness" finds the right section), and it opens the section when only one matches.

### Fixed

- **Style and script updates now take effect without a hard refresh.** The app's stylesheet and scripts are versioned per release, so after an update your browser fetches the new files instead of a stale cached copy. This is what was hiding the top-menu dropdown fix: the browser kept using the old cached stylesheet, so the menus still opened behind the page until now.

### Fixed

- **The CAN Monitor no longer reloads every database on each refresh.** When a vehicle with a linked database was selected, the monitor was pulling every installed database's full contents into memory a few times a second just to decode. It now looks up only what it needs, so monitoring stays light on the device.
- **A way out of the CAN Lab's embedded tools.** Each tool in the CAN Lab runs in its own panel, which meant dialogs like "Save signal" or "Add to cockpit" opened cramped inside that panel. A new open-in-new-tab button in the tab bar opens the current tool full-page where those dialogs have room.

### Fixed

- **The top-menu dropdowns are clickable again.** On the new dark theme the frosted top bar was trapping its own menus behind the page, so the CAN Lab, Builder, Settings, and vehicle menus could not be reached. They now open above the page as they should.

### Changed

- **The operator screen now leads with your vehicle's buttons.** On a touchscreen or Stream Deck, the operator view opens straight onto the controls you mapped for the active vehicle (lock, windows, lights, horn, and the rest), as big buttons grouped by area and sized for a tap. Press one and it fires the saved CAN command, no menus to dig through. Slots you have not mapped yet stay off this screen so it stays clean and glanceable, and the "Builder" button in the corner takes you to the full builder when you are at a desktop.

### Added

- **Graph a signal over time.** Each bit-search candidate now has a "Graph" button that plots that field's decoded value across the capture on its own timeline, so you can see the trend and spot glitches, without needing a reference to compare against.

### Added

- **Replay a capture back onto the bus.** Any saved capture can be replayed onto the bus at its original timing (or faster), so you can reproduce a sequence while you probe for what a message does. It is bounded in length so a big capture cannot run away.

### Added

- **Fuzz an id to see what reacts.** The Simulate / send page has a new fuzzer: pick an id and a template, choose which bytes to randomize, and send a bounded run of frames. Every frame it sends is listed, so when something on the car reacts you can trace it straight back to the exact bytes that caused it. Meant for a bench or a bus you control.

### Added

- **Auto-find a signal in one click.** Once you have a reference (a sweep, a dashboard camera read, or a known signal), the new "Auto-find signal" button does the whole search for you: it ranks the ids, searches their bits (including each multiplexer value), picks the best fit, and, when AI is configured, names it. It is the find-and-refine work you would otherwise do by hand, in a single pass.
- **Your vehicle's database is used to decode automatically.** Once you link a database to a vehicle and pick that vehicle in the top bar, the CAN Monitor decodes its traffic with that database on its own, so you no longer have to reselect it every time. Choosing a database by hand on the Monitor still wins when you want a different one.
- **The Databases page floats the ones that fit your vehicle to the top.** With a vehicle selected, installed databases and open-source catalog entries that match its make, model, and year rise to the top with a "Matches your vehicle" badge, so the right database is the first thing you see.
- **More vehicles in the open-source database catalog.** The catalog now points to community CAN references for Tesla Model 3, Nissan Leaf, Ford Mustang S550, Kia Soul, VW's electric MEB cars, BMW 7 Series, and more, drawn from the community "awesome-automotive-can-id" index (also linked directly). These are reference links you follow and import yourself, not bundled files, so the licensing of each source stays with its author.
- **Install a database with one click, even offline.** The Databases page now has a "Ready to install, no internet needed" section with a couple of openly-licensed databases that ship with AutoPi (a generic powertrain and a generic body/comfort set). Click Install and it is added on the spot, no network required, so a freshly flashed device has something to decode with right away. You can retag either one for your own vehicle.
- **Read the dashboard with a camera to find a signal.** The reference recorder has a new "Dashboard camera" mode: point a camera (or your webcam) at the dash, change the value, and AutoPi reads the number off each frame with the vision AI and records it as the reference, timed against the live capture. Then the bit search matches an unknown CAN field to what the dash actually showed, so you can find things like speed or RPM without a known signal to compare against. Needs an AI provider configured.

### Added

- **The bit search understands multiplexed messages.** Some messages reuse the same bytes for different signals depending on a selector byte, so a signal that only exists for one selector value used to get averaged away and missed. AutoPi now spots the selector and lets you search within a single value, so those signals can be found. When a search comes up empty on a multiplexed message, it tells you and offers the selector values to try.

### Added

- **The bit search now warns you when a decode is weak.** Each candidate's fit quality is colour-coded, and if nothing tracks your reference well the results lead with a plain warning that the field is probably not the signal (or the reference was noisy). This works with no AI key; when AI is configured, the name suggestion still adds its own plausibility check.

### Added

- **Send a found control to the transmit workbench, and edit it live.** Every Signal Finder result now has a "To workbench" button that drops the command into the Simulate / send panel, ready to run. There you can edit an entry's data bytes while it is transmitting and the change takes effect on the next cycle, so you can nudge a value and watch the car respond without stopping and re-adding the frame.

### Fixed

- **"Find a control" no longer bogs the device down on a busy bus.** Like Verify effect before it, the search was writing every frame it heard on every bus to the SD card, which on a busy CAN-FD bus is tens of thousands of frames and made the device sluggish after each run. It now keeps those frames in memory (the Bits view still opens them), so the search stays responsive.

### Added

- **The Signal Finder now spots protected messages and rebuilds valid frames.** Many command messages carry a rolling counter and a checksum, and the vehicle rejects any frame whose counter does not advance or whose checksum is wrong, which is why a plain replay (even flooded) does nothing. A found control that is protected now shows a "protected" badge, and Test and Flood regenerate each frame with a fresh, advancing counter and a recomputed checksum so it can be accepted. If the checksum uses a scheme AutoPi does not recognize yet, the badge warns you that the vehicle may still drop it, so you are not left guessing.

### Added

- **Pick which databases your vehicle uses, right on the Databases page.** With a vehicle selected in the top bar, each installed database shows a "Use with" button, and the ones already in use carry an "In use" badge with a one-click Remove. The choice is saved with the vehicle, so its linked databases follow it everywhere.
- **Flood a command to out-rate the real sender.** Some controls are broadcast continuously by another module, so sending your found command once loses to the next real frame and nothing happens. The Signal Finder now has a "Flood 1s" button that sends the command every 10 ms for a second to win that contest, and a control saved to a cockpit can be set to flood on each press (a "Flood on press" option on the CAN action). This is what a momentary command like mute usually needs.

### Fixed

- **Firing a CAN-FD control now actually sends.** Injecting a found control on a CAN-FD bus could report "could not inject" and transmit nothing, while a shorter classic control on the same bus fired fine. The transmit was going out on a socket opened in classic mode, which the kernel refuses for a CAN-FD frame. Firing a control, verifying its effect, and holding a control down (repeat send) now open the bus in CAN-FD mode whenever the frame is CAN-FD, so the frame goes out. Classic frames are unaffected.

### Fixed

- **Find a control now shows only what actually reacts to you, and how consistently.** On a busy bus, the old detection listed almost every message because they are all on the bus near each press. It now keys off whether a message appears right when you act and was absent just before, which is what tells a real command apart from a broadcast that is always there. A message you operated on 6 of 9 presses now reads 6/9, and messages that are simply always present no longer show up at all.

### Fixed

- **"Verify effect" no longer bogs down the device.** It used to save every frame it heard to the SD card while it worked, which on a busy CAN-FD bus wrote tens of thousands of frames and made the whole interface feel like it had hung. It now keeps those frames only in memory (it never needed to save them), so it stays responsive.

### Added

- **Every vehicle now has a full set of controls you can fill in.** A new Vehicle controls page (under Vehicles) gives the active vehicle a ready made list of common buttons (lock, windows, lights, climate, mute, and more). Fill any slot from a saved library command or by typing the CAN frame yourself, and clear it just as easily.
- **A shared command library.** Save a command you found in the Signal Finder to a reusable library (the new "Save to library" button on a found control), then map it onto any vehicle's controls later.

### Fixed

- **Find a control no longer floods the list with false matches.** Messages that are on the bus continuously with a fixed payload were being listed as if they only appear when you act, which produced a long list of look-alike candidates. Only messages that are genuinely sent around your presses are listed now.

### Changed

- **A denser, more technical look across the whole app.** AutoPi now wears a dark cockpit theme built around its pink accent: tighter tables and forms fit more on screen, panels sit on glass-style surfaces over a faint engineering grid, labels and readouts use a monospace technical type, and the top bar, menus, and scrollbars match. The operator screen and Start page share the same look, so the touchscreen and the workbench feel like one instrument. Everything stays high-contrast and readable.

### Fixed

- **"Verify effect" no longer mistakes a failed send for "no effect".** If the frame could not actually be transmitted (for example a CAN-FD frame on a classic channel, or an interface that is not up for sending), the tool now says the injection failed and why, instead of reporting that nothing reacted (which wrongly suggested the message was only a status). It also returns a clear message instead of an error when it cannot start listening.

### Added

- **Copy a vehicle.** Duplicate an existing vehicle from the vehicles page to start a new one from a known-good setup (its linked databases, transmit lists, and mapped controls carry over; the VINs do not, since those belong to one physical vehicle).

### Added

- **Your vehicle now follows you everywhere.** A vehicle selector sits at the top of every screen, so the vehicle you are working on is always visible and one click to change. Whatever you pick is the active vehicle the rest of the app works against, and it stays selected across restarts.

### Added

- **Find a control also catches commands that just appear.** Some controls are driven by a command another module sends with a fixed payload, so nothing in the message "changes", it only shows up while you act. Those are now detected and listed (marked "appears") instead of being missed, so a button whose command is a constant frame can still be found and replayed.

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
