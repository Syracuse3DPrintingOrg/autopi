# AutoPi Dependency Licensing

This document tracks the license of every third-party dependency AutoPi ships
or links against, and what each one means for distributing AutoPi as a
**proprietary (closed-source) product**. AutoPi is not currently open source,
but it could be: the notes below call out what would change either way.

This is a practical engineering summary, not legal advice. Before a commercial
release, have counsel review it, especially the LGPL and the CAN-data sections.

## The short version

- **Almost everything is permissive** (MIT, BSD, Apache-2.0, public domain).
  You can ship these in a closed-source product. The only obligation is to
  preserve their copyright and license notices in what you distribute.
- **One dependency is weak copyleft: `python-can` (LGPL-3.0).** You can use it
  in a closed product as long as you keep it a separate, replaceable library
  (a normal pip install satisfies this), do not modify it, and include its
  license and source (or a written offer). Do not fork and bundle a modified
  `python-can` into a closed product.
- **No strong copyleft (GPL/AGPL) is present.** Keep it that way while the
  product is closed: do not add a GPL/AGPL runtime dependency, and do not
  import GPL-licensed CAN tooling into the app.
- **CAN databases (DBC files) carry their own licenses, separate from the
  code.** opendbc is MIT. Other sources vary and some carry IP risk. AutoPi
  records each imported database's `source` and `license` so provenance is
  auditable.

## Dependency license table

Runtime dependencies (`service/requirements.txt`) and the Stream Deck
controller (`streamdeck/requirements.txt`):

| Dependency | License (SPDX) | Type | Notes |
|---|---|---|---|
| fastapi | MIT | Permissive | Web framework |
| starlette (via fastapi) | BSD-3-Clause | Permissive | |
| uvicorn | BSD-3-Clause | Permissive | ASGI server |
| jinja2 | BSD-3-Clause | Permissive | Templates |
| itsdangerous | BSD-3-Clause | Permissive | Session signing |
| python-multipart | Apache-2.0 | Permissive | Form parsing; patent grant |
| pydantic / pydantic-settings | MIT | Permissive | |
| httpx | BSD-3-Clause | Permissive | HTTP client |
| sqlalchemy | MIT | Permissive | Local database |
| **python-can** | **LGPL-3.0** | **Weak copyleft** | **See "python-can" below** |
| cantools | MIT | Permissive | DBC parse + encode/decode (Erik Moqvist) |
| bitstruct (via cantools) | MIT | Permissive | |
| can-isotp | MIT | Permissive | ISO-TP (ISO 15765-2) transport (Pier-Yves Lessard) |
| udsoncan | MIT | Permissive | UDS (ISO 14229) client (Pier-Yves Lessard) |
| gpiozero | BSD-3-Clause | Permissive | GPIO |
| lgpio | Unlicense (public domain) | Permissive | GPIO pin backend |
| streamdeck (python-elgato-streamdeck) | MIT | Permissive | Deck driver |
| Pillow | MIT-CMU (HPND) | Permissive | Key image rendering |
| websockets | BSD-3-Clause | Permissive | Deck kiosk control |

Bundled data:

| Data | License | Notes |
|---|---|---|
| opendbc DBC files (comma.ai) | MIT | Imported on demand, not vendored in the repo. Keep attribution. |
| User-imported DBC files | Varies | Recorded per database in `CanDatabase.source` / `.license`. |

## python-can (LGPL-3.0): what it means

`python-can` is the only weak-copyleft dependency. LGPL is designed to let a
proprietary program use a library without becoming open source, provided the
library stays independent and replaceable.

You are compliant when **all** of these hold, which the default setup already
satisfies:

1. **Unmodified and separate.** AutoPi imports `python-can` as a standard,
   separately installed package. It is not modified and not statically bundled
   into AutoPi's own code. A Python import is dynamic linking for LGPL purposes.
2. **Replaceable by the user.** Because it is a normal installed package
   (`pip`), a recipient can upgrade or swap it for their own build. That is the
   LGPL "allow the user to relink" requirement.
3. **License and source conveyed.** When you distribute AutoPi as an image,
   container, or device, include `python-can`'s LGPL-3.0 license text and
   either its source or a written offer to provide it. Shipping the pip package
   as-is (which includes its metadata and is fetchable from PyPI) plus this
   note generally covers it; a device image should carry the license file.

What would break compliance, and how to avoid it:

- **Do not fork and patch `python-can` and ship it closed.** If you must modify
  it, release your modified `python-can` (only that library) under LGPL-3.0.
  Keeping local changes as a separate wrapper module in AutoPi's own code is
  fine and stays proprietary.
- **Do not statically bundle it** in a way that prevents replacement (e.g. a
  frozen single-file binary with no way to substitute the library) without
  providing the object files/relinking mechanism the LGPL requires.

If you ever want zero copyleft, note there is no drop-in permissive replacement
for `python-can`'s multi-backend support, so the realistic path is to comply
with the LGPL rather than remove it.

## CAN databases (DBC) are a separate licensing question

The software license of a DBC parser (cantools, MIT) is independent of the
license of the **DBC data** you load into it.

- **opendbc** is MIT: safe to use and redistribute with attribution. AutoPi
  imports it on demand (`scripts/import-opendbc.sh`) rather than vendoring it,
  and stamps `source=opendbc`, `license=MIT` on each imported database.
- **Other DBC sources vary.** Some community or vendor DBCs are unlicensed,
  proprietary, or reverse-engineered from an OEM. Two distinct risks:
  - *License risk*: redistributing a DBC you do not have the right to.
  - *IP risk*: reverse-engineered OEM signal definitions can carry legal
    exposure independent of any software license.
  Only import databases you have the right to use, and use the per-database
  `source`/`license` fields to keep provenance auditable.

## AutoPi's own license

AutoPi's own code is under `LICENSE` (PolyForm Noncommercial 1.0.0), which is
source-available and noncommercial, not an OSI open-source license. Because Dan
holds the copyright to AutoPi's own code, it can be relicensed later (for
example to a permissive or commercial license, or fully open source) without
any third-party dependency blocking it: the permissive dependencies allow any
relicensing, and LGPL `python-can` is compatible with both proprietary and
open-source distribution.

## Keeping this current

Update the table whenever a dependency is added, removed, or version-bumped in
`service/requirements.txt` or `streamdeck/requirements.txt`. When you add a
dependency, record its SPDX license and flag anything that is not permissive
(anything GPL/AGPL should be rejected for a closed product; anything LGPL/MPL
gets a compliance note like the `python-can` section above).
