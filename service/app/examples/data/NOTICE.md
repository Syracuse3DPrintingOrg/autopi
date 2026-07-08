# Vendored CAN databases

`chrysler_cusw.dbc` is from comma.ai's opendbc (https://github.com/commaai/opendbc),
MIT licensed. It is a reverse-engineered database for the Chrysler CUSW platform
(covers the RAM 1500 2019-2024 among others) and is redistributed here under the
MIT license with attribution. It covers powertrain, steering, body, and driver-
assist signals; it does not include proprietary infotainment/radio messages.

`fca_giorgio.dbc` is also from opendbc (MIT), covering the Stellantis Giorgio
platform (Alfa Romeo Giulia/Stelvio, Maserati Grecale). Redistributed with
attribution under the MIT license.

`ford_lincoln_base_pt.dbc` is from opendbc (MIT), the modern Ford CAN-FD
powertrain database (F-150, Mustang Mach-E, Explorer, Bronco Sport, Maverick,
and more). Redistributed with attribution under the MIT license.

`toyota_nodsu_pt_generated.dbc`, `honda_civic_ex_2022_can_generated.dbc`, and
`hyundai_canfd.dbc` are from opendbc (MIT), covering Toyota/Lexus, Honda, and the
shared Hyundai/Kia/Genesis CAN FD platform. Redistributed with attribution under
the MIT license; a few upstream parse-blocking typos (a missing VAL_ semicolon and
malformed CM_ comment lines) were corrected on the vendored copies.
