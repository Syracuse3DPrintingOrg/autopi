# Vendored CAN databases

`chrysler_cusw.dbc` is from comma.ai's opendbc (https://github.com/commaai/opendbc),
MIT licensed. It is a reverse-engineered database for the Chrysler CUSW platform
(covers the RAM 1500 2019-2024 among others) and is redistributed here under the
MIT license with attribution. It covers powertrain, steering, body, and driver-
assist signals; it does not include proprietary infotainment/radio messages.

`fca_giorgio.dbc` is also from opendbc (MIT), covering the Stellantis Giorgio
platform (Alfa Romeo Giulia/Stelvio, Maserati Grecale). Redistributed with
attribution under the MIT license.

`toyota_nodsu_pt_generated.dbc` is from opendbc (MIT), covering the
powertrain bus of dsu-less (no Driving Support ECU) Toyota/Lexus models from
around 2020 on, RAV4 among them. Redistributed with attribution under the
MIT license. One upstream typo (a missing semicolon on a `VAL_` line) is
corrected in the vendored copy so it parses; no message or signal content
was changed.

`honda_civic_ex_2022_can_generated.dbc` is from opendbc (MIT), covering the
Bosch-radar Honda Civic's powertrain, steering, and body buses. Redistributed
with attribution under the MIT license. Three upstream `CM_` comment lines
missing their `BO_`/signal-name field are corrected to valid `CM_ BO_ <id>`
message comments in the vendored copy (comment text and message id
preserved) so it parses; no message or signal content was changed.

`hyundai_canfd.dbc` is from opendbc (MIT), the shared database for the
Hyundai/Kia/Genesis CAN FD platform (2021+ models with 16/24/32-byte CAN FD
frames), covering models such as the Elantra, Sonata, and Ioniq. Redistributed
with attribution under the MIT license. Four upstream `CM_` comment lines
missing their `BO_` keyword are corrected the same way as above so it parses;
no message or signal content was changed.

All three vendored files also had any message id greater than 2047
(11-bit) programmatically OR'd with `0x80000000`, the same extended-id
convention already used by `chrysler_cusw.dbc` and `fca_giorgio.dbc`, so
cantools parses them as extended frames. Only `honda_civic_ex_2022_can_generated.dbc`
had ids in that range (`LKAS_HUD_A`, `LKAS_HUD_B`, `LKAS_HUD_2`); the Toyota
and Hyundai CAN FD files needed no change.
