# Open-source CAN stack: what AutoPi leans on

AutoPi does not reinvent CAN tooling. It stands on well-maintained open-source
libraries and public vehicle data, and it chooses them so the product can stay
proprietary if that is the goal: permissive licenses wherever possible, and no
strong copyleft (GPL/AGPL) in the runtime. This page is the audit of that
choice. The per-dependency license table lives in LICENSING.md; this is the
why.

## The libraries we build on

- **cantools (MIT)** does all DBC bit math: parsing a database, and encoding and
  decoding frames against it. AutoPi never hand-rolls signal packing; it holds
  the original DBC text and lets cantools place the bits. This is why importing a
  real opendbc database and decoding a live bus just works.
- **python-can (LGPL-3.0)** is the transport: SocketCAN on the Pi, plus PEAK
  (PCAN) and Vector back ends and a virtual bus for bench work. It is the one
  weak-copyleft dependency. We use it as an unmodified library over its public
  API (a separable, dynamically imported module), which is the LGPL's intended
  use; we do not fork or statically bind it. If a fully permissive stack is ever
  required, SocketCAN can be driven directly, but there is no need today.
- **can-isotp (MIT)** and **udsoncan (MIT)** give ISO-TP segmentation and a UDS
  client for the Diagnostics page (UDS services and OBD-II PIDs).
- **opendbc (MIT)**, comma.ai's reverse-engineered database collection, is the
  source of the real vehicle samples (RAM 1500, Alfa Romeo Giulia, Ford F-150,
  Toyota RAV4, Honda Civic, Hyundai Elantra) and of the OEM counter and checksum
  algorithms reproduced in `service/app/can/checksum.py` (Chrysler, FCA Giorgio
  J1850, Toyota, Honda, Hyundai CAN FD), each verified against its reference.

## Deliberate license choices

- **We prefer MIT/BSD/Apache.** Everything above except python-can is permissive.
- **We avoided GPL on purpose.** The obvious library for OBD-II, python-OBD, is
  GPLv2, which would force the whole product open if linked. Instead AutoPi does
  OBD-II and UDS over the MIT-licensed can-isotp and udsoncan. Do not add a
  GPL/AGPL runtime dependency, and do not import GPL-licensed CAN tooling (for
  example SavvyCAN's code, GPLv3) into the app.
- **DBC files carry their own license, separate from code.** opendbc is MIT and
  is vendored with attribution (see `service/app/examples/data/NOTICE.md`).
  Databases from other sources vary and some carry IP risk; keep sourcing to
  clearly licensed data or the user's own captures.

## Where we could lean further

- More opendbc databases as additional vehicle samples (same MIT terms).
- More of cantools where it already helps (extended multiplexing, ARXML/SYM
  import) rather than adding parsers of our own.
- Keep new transports inside the existing python-can back-end model instead of
  bringing in a second transport stack.

The rule of thumb: reach for a maintained, permissively licensed library before
writing CAN code by hand, and keep GPL out of the runtime while the product is
closed. Before any public release, have counsel review the LGPL and CAN-data
sections in LICENSING.md.
