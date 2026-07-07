# Changelog

All notable changes to AutoPi are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project follows
semantic versioning while pre-1.0 (staying in `0.x`).

## [Unreleased]

### Added

- **First cut of the AutoPi control surface.** A web start menu and an
  optional Stream Deck share one layout of keys. Each key runs an action you
  define: toggle or pulse a GPIO pin, run a shell command, or call another
  application over HTTP. Arrange the keys by dragging them in the layout
  editor. The app runs standalone over its own Wi-Fi access point or on your
  network, and on a plain server with no Pi attached (the hardware drivers
  no-op cleanly when there is nothing to drive).
