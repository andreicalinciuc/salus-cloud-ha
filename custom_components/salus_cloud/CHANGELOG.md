# Changelog

All notable changes to this project are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [2.0.1] - 2026-10-27

Checked against a real IT800 system (SAWZ600GW Wi-Fi gateway with an IT800TX thermostat).

### Added
- Wi-Fi gateway: "Wi-Fi signal" (dBm) and "Cloud connection" diagnostic entities; software and hardware version on
  the device page (SAWZ600GW reports them as `sGateway:GatewaySoftwareVersion` / `GatewayHardwareVersion`).

### Fixed
- Diagnostics: the gateway also reports its Wi-Fi IP address, AWS certificate, cloud id, debug logs and device
  list; these are now redacted too (the Wi-Fi name and password already were).

### Note
- A SAWZ600GW does not report a boiler relay, so "Boiler" and "Mode" are not created for it; the Salus app's
  "Main / Auto off" on that tile is its default text when no relay state is reported.

## [2.0.0] - 2026-10-27

### Changed (breaking)
- New integration domain `salus_cloud` (was `salus_it600_cloud`), installed in `custom_components/salus_cloud`.
  Home Assistant treats it as a new integration: remove the old "Salus iT600 Cloud" integration and the old
  `custom_components/salus_it600_cloud` folder, install this version, restart and add **Salus Cloud** again.
  Entity IDs are created anew, so automations, scripts and dashboards that use the old ones need updating.
- The integration is called "Salus Cloud" in Home Assistant and HACS; supported models (iT600, iT800 / IT800TX)
  are listed in the description instead of the name.
- On iT800 thermostats the key lock is a switch (it was a read-only binary sensor).

### Added
New settings and values come from the Salus web app's own device model. Every entity is only created when the
device reports the property, and settings use the commands and values the app sends.
- iT800 thermostat settings: switches for key lock, display always on, optimum (adaptive) start and stop and frost
  protection; selects for display brightness, temperature display resolution and heating control (hysteresis
  ±0.25 … ±2.0 °C or TPI for underfloor heating, radiators or electric heating); numbers for the lowest and
  highest heating temperature.
- Wi-Fi receiver (gateway): "Boiler" (relay on / off) and "Mode" (auto, or switched on / off by hand on the
  receiver); firmware and model on the device page. Gateway states are read in a separate request, so a gateway the
  account cannot read never affects the thermostats.
- Diagnostics include the gateway's properties; Wi-Fi names, IP and MAC addresses are redacted.

### Fixed
- A negative temperature calibration was shown as about +25 °C: the thermostat reports it as an unsigned byte
  (-0.5 °C as 251). It is now decoded like the Salus app does.

## [1.3.0] - 2026-10-26

Property names and value ranges come from the Salus web app's own IT800 (ep1) device model, the same source that
gave the correct humidity property. Every entity is created only when the thermostat reports the property.

### Added
- Settings (number entities, configuration category), sent with the same commands the Salus app uses:
  - Temperature calibration (`sTherS:TempCalibration_x10`), -2.5 to +2.5 °C in 0.1 °C steps.
  - Frost protection temperature (`sComm:FrostSetpoint_x100`), limited by the device's Min/MaxFrostSetpoint.
- Diagnostic binary sensors: Battery low (`sPowerS:ErrorPowerSLowBattery`), Key lock (`sTherUIS:LockKey`,
  Locked / Unlocked) and Problem (on when any error flag such as a faulty temperature sensor is set; the flags are
  listed in the `errors` attribute).
- Floor temperature sensor (`sTherS:FloorTemperature_x100`); shows unknown when no floor probe is connected.
- The thermostat's slider uses the device's own MinHeatSetpoint / MaxHeatSetpoint when reported.
- Firmware and hardware version on the device page.

### Changed
- Thermostat presets are shown as Schedule / Manual / Frost protection with icons (were "schedule" / "manual" / "Away").

## [1.2.1] - 2026-10-26

### Changed
- Short entity names: under the device the entities are now called "Humidity", "Preset", "Heating" etc. instead of
  "<gateway> <device> Humidity", and the thermostat is shown with the device name. Existing entity ids do not change.
- Readable states and icons: Preset shows Schedule / Manual / Frost protection, System mode Off / Auto / Heat and
  the Heating sensor Heating / Idle (it showed "Normal" before). English, Czech and Romanian translations.

### Fixed
- On Home Assistant 2025.8 – 2026.2 no entity could be added ("unexpected keyword argument 'via_device_id'"):
  devices are now linked to their gateway with the parameter the running Home Assistant version supports.
  CI now also sets the integration up in a real Home Assistant instance on 2025.8.0, 2026.2.3 and the latest release.
- Devices the Salus app shows inside a group (room) were not discovered at all; groups are now searched
  recursively and a device listed both at the top level and in a group is added once.
  (Based on a fix by awhitwam.)

### Added
- Humidity for SQ610 (Quantum) thermostats, which report it in `ep9:sIT600TH:SunnySetpoint_x100`
  (found by Vlad Vesa). Only SQ610 models use this property for humidity.

## [1.2.0] - 2026-10-26

First release of Salus Cloud.

### Added
- Thermostats of the iT600 (`ep9`) and iT800 (`ep1`/`ep2`, e.g. IT800TX) families, detected from the properties a
  device reports: temperature, HVAC mode, presets (schedule / manual / frost protection) and relay state are read
  and written with the property names of the device's family. iT800 HVAC mode changes are sent through
  `SystemMode` (0 = off, 4 = heat) together with the matching hold type. (iT800 support by Vlad Ohai)
- Relays and smart plugs, door / window / motion sensors and OneTouch rules (buttons).
- Separate entities per thermostat value, created only for values the device reports: temperature, target
  temperature, humidity, battery voltage, preset and system mode sensors, plus a "Heating" binary sensor (heat
  demand, `RunningState`).
- Humidity: IT800TX reports it as `ep1:sHumiS:MeasuredValue_x100`; it is shown as a sensor and on the thermostat.
- Option "Synchronize thermostat modes": a mode change of one thermostat is applied to all thermostats of its
  gateway.
- Device state changes pushed over AWS IoT MQTT; polling every 5 minutes as a safety net, every 30 seconds when
  pushed changes are not available.
- Diagnostics download with the raw shadow properties of every device; credentials, device codes and personal
  data are redacted.
- GitHub Actions CI: pytest on Home Assistant 2025.8.0 (minimum) and the latest release, hassfest, HACS validation.
