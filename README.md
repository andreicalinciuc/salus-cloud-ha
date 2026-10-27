# Salus Cloud for Home Assistant

[![CI](https://github.com/andreicalinciuc/salus-cloud-ha/actions/workflows/ci.yml/badge.svg)](https://github.com/andreicalinciuc/salus-cloud-ha/actions/workflows/ci.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/docs/faq/custom_repositories/)

Home Assistant integration for Salus devices through the Salus Cloud (AWS Cognito login, device shadows over
AWS IoT MQTT). Supports iT600 and iT800 (IT800TX) thermostats, relays and smart plugs, sensors and OneTouch rules;
see [Supported devices](#supported-devices).

## Highlights

- **iT600 and iT800 (IT800TX) thermostats**: read and control, detected automatically from the properties a device reports.
- **One entity per value**: temperature, target and floor temperature, humidity, battery, preset, system mode,
  heating, key lock, problem; calibration and frost protection temperature as settings.
- **Humidity on IT800TX** (`ep1:sHumiS:MeasuredValue_x100`), also shown on the thermostat card.
- **Diagnostics download** with the raw shadow properties (identifiers redacted).
- **Tested**: pytest including a real Home Assistant setup on 2025.8.0 (minimum), 2026.2.3 and the latest release;
  hassfest; HACS validation.

### IT800TX field mapping

The integration detects the device family from the shadow properties it reports.
One `ep1:`/`ep2:` property is enough to treat the device as iT800. Devices reporting the `ep9` names
behave exactly as before.

| Meaning | iT600 (`ep9`) | iT800 (`ep1`/`ep2`) |
|---|---|---|
| Measured temperature (x100) | `ep9:sIT600TH:LocalTemperature_x100` | `ep1:sTherS:LocalTemperature_x100` |
| Target temperature (x100) | `ep9:sIT600TH:HeatingSetpoint_x100` | `ep1:sTherS:HeatingSetpoint_x100` |
| System mode (0 off, 4 heat) | `ep9:sIT600TH:SystemMode` | `ep1:sTherS:SystemMode` |
| Hold type (0 schedule, 2 manual, 7 frost) | `ep9:sIT600TH:HoldType` | `ep1:sComm:HoldType` |
| Heat demand | `ep9:sIT600TH:RunningState` | `ep1:sTherS:RunningState` |
| Battery voltage (x10) | `ep9:sBasicS:BatteryVoltage` | `ep1:sPowerS:BatteryVoltage_x10` |
| Relative humidity (x100) | `ep9:sHumiS:MeasuredValue_x100` (if reported) | `ep1:sHumiS:MeasuredValue_x100` |
| Relay on/off | `ep9:sOnOffS:OnOff` | `ep2:sOnOffS:OnOff` |

Commands use the same names with `Set` before the property (e.g. `ep1:sTherS:SetHeatingSetpoint_x100`).
Turning an iT800 thermostat on/off sends `SetSystemMode` (4/0) **and** the matching `SetHoldType`
(schedule/frost), because iT800 devices ignore a hold type change alone.

The iT800 support was written by Vlad Ohai.

## Installation

### HACS (custom repository)

1. HACS → ⋮ (top right) → **Custom repositories**.
2. Repository: `https://github.com/andreicalinciuc/salus-cloud-ha`, type: **Integration** → **Add**.
3. Search **Salus Cloud** → **Download** → choose the latest release.
4. Restart Home Assistant.
5. **Settings → Devices & services → Add integration → Salus Cloud**, then log in with your Salus account.

### Manual

Copy `custom_components/salus_cloud` from the [latest release](https://github.com/andreicalinciuc/salus-cloud-ha/releases/latest)
into `<config>/custom_components/` and restart Home Assistant.

## Entities per thermostat

Besides the climate entity, each thermostat gets one entity per value it reports, with a short name under the
device ("Humidity", "Preset", "Heating"). A value the device never reports gets no entity.

| Entity | Source property | Unit |
|---|---|---|
| `sensor.<name>_temperature` | `LocalTemperature_x100` | °C |
| `sensor.<name>_target_temperature` | `HeatingSetpoint_x100` | °C |
| `sensor.<name>_humidity` | `sHumiS:MeasuredValue_x100` / `…Humidity…` | % |
| `sensor.<name>_battery_voltage` (diagnostic) | `BatteryVoltage` / `BatteryVoltage_x10` | V |
| `sensor.<name>_preset` | `HoldType` → Schedule / Manual / Frost protection | |
| `sensor.<name>_system_mode` (diagnostic) | `SystemMode` → Off / Auto / Heat | |
| `binary_sensor.<name>_heating` | `RunningState` → Heating / Idle | |
| `sensor.<name>_floor_temperature` | `FloorTemperature_x100` (unknown without floor probe) | °C |
| `binary_sensor.<name>_battery_low` (diagnostic) | `ErrorPowerSLowBattery` | |
| `binary_sensor.<name>_key_lock` (diagnostic, iT600) | `LockKey` → Locked / Unlocked | |
| `binary_sensor.<name>_problem` (diagnostic) | any `Error…` flag, listed in the `errors` attribute | |
| `number.<name>_temperature_calibration` (config) | `TempCalibration_x10`, -2.5 … +2.5 | °C |
| `number.<name>_frost_protection_temperature` (config) | `FrostSetpoint_x100`, device min/max | °C |
| `number.<name>_minimum_heating_temperature` / `…_maximum_heating_temperature` (config) | `MinHeatSetpoint_x100` / `MaxHeatSetpoint_x100`, 5 … 35 | °C |

iT800 thermostats (IT800TX) also get the settings of the Salus app, sent with the same commands and values the app
uses:

| Entity | Source property | Values |
|---|---|---|
| `switch.<name>_key_lock` | `sTherUIS:LockKey` | on = locked |
| `switch.<name>_display_always_on` (config) | `sComm:DisplayAlwaysOn` | |
| `switch.<name>_optimum_start` / `…_optimum_stop` (config) | `sComm:OptimizeStart` / `OptimizeStop` | adaptive start / stop |
| `switch.<name>_frost_protection` (config) | `sComm:HolidayActive` | what the app's "Frost protection" setting writes |
| `select.<name>_display_brightness` (config) | `sComm:LEDBrightness` | High (204) / Low (64) |
| `select.<name>_temperature_display_resolution` (config) | `sComm:TempDisplayResolution_x10` | 0.5 °C (5) / 0.1 °C (1) |
| `select.<name>_heating_control` (config) | `sComm:HeatingControlAlgorithm` | hysteresis ±0.25 … ±2.0 °C (0, 1, 3, 4, 5), TPI underfloor / radiators / electric (16, 17, 18) |

## Gateway

| Entity | Source property | Values |
|---|---|---|
| `sensor.<gateway>_wi_fi_signal` (diagnostic) | `sGateway:WiFiRSSI` | dBm |
| `binary_sensor.<gateway>_cloud_connection` (diagnostic) | `sAWSIoT:CloudStatus` | Connected / Disconnected |
| `binary_sensor.<gateway>_boiler` | `sComm:RelayStatus`, only on gateways with a boiler relay | Heating / Idle |
| `sensor.<gateway>_mode` | `sComm:PanelSwitchStatus`, only on gateways with a boiler relay | Auto / Manual on / Manual off |

The device page shows the gateway's software and hardware version. Gateway states are polled (every 5 minutes
while thermostat changes are pushed). A SAWZ600GW Wi-Fi gateway reports no boiler relay, so it only gets the first
two entities.

The thermostat's temperature range follows the device's `MinHeatSetpoint_x100` / `MaxHeatSetpoint_x100`, and the
device page shows its firmware and hardware version. Presets are shown as Schedule / Manual / Frost protection.

Every sensor shows the exact shadow property it reads in its `shadow_property` attribute. For a device that
reports something unexpected, use **Download diagnostics** on the integration and open an issue with the file.

## Supported devices

- Thermostats: HTRP-RF, TS600, VS10/VS20, SQ610, FC600, **IT800TX**
- Relays and plugs: RS600, SPE600, SR600
- Sensors: temperature, humidity, battery
- Binary sensors: door / window contacts (SW600, OS600), water leak (WLS600), smoke and motion sensors
- Buttons: OneTouch rules

## Troubleshooting

- **Invalid email or password:** check the login in the Salus app and use the email address, not a username.
  Accounts with two-factor authentication are not supported.
- **No devices found:** make sure the devices are paired in the Salus app and the gateway is online, then reload
  the integration.
- **Reading works but control does not:** Home Assistant must reach `*.iot.eu-central-1.amazonaws.com` on port 443.
- **A device reports something unexpected:** device page → ⋮ → **Download diagnostics** and attach the file to an
  [issue](https://github.com/andreicalinciuc/salus-cloud-ha/issues).

Debug logging:

```yaml
logger:
  logs:
    custom_components.salus_cloud: debug
```

## Development

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt ruff==0.14.0
pytest
ruff check && ruff format --check
```

Code layout (`custom_components/salus_cloud`):

| Module | Purpose |
|---|---|
| `api.py` | Salus Cloud REST API: Cognito login, gateways and devices, device shadows, AWS IoT credentials |
| `mqtt.py` | AWS IoT MQTT connection: sends commands, receives pushed shadow documents |
| `state.py` | Reported properties per device plus commanded values not reported yet |
| `coordinator.py` | Polling, pushed updates, commands and thermostat mode synchronization |
| `device.py` | `SalusDevice`: device list entry plus current shadow state, device classification |
| `properties.py` | Property names of the iT600 and iT800 families |
| `shadow.py` | Shadow property helpers: lookup, scaling, command names |
| `thermostat.py`, `settings.py`, `gateway.py` | What is shown for thermostats, app settings and gateways |
| `entity.py` and the platform modules | Home Assistant entities |

CI runs the tests against Home Assistant 2025.8.0 (minimum), 2026.2.3 and the latest release, ruff, plus
[hassfest](https://github.com/home-assistant/actions) and the [HACS action](https://hacs.xyz/docs/publish/action/).

Pull requests are welcome; every change to `main` goes through a pull request reviewed by the maintainer
([CODEOWNERS](.github/CODEOWNERS)).

## License

MIT. See [LICENSE](LICENSE).
