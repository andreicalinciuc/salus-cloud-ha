# Salus Cloud for Home Assistant

[![CI](https://github.com/andreicalinciuc/salus-cloud-ha/actions/workflows/ci.yml/badge.svg)](https://github.com/andreicalinciuc/salus-cloud-ha/actions/workflows/ci.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/docs/faq/custom_repositories/)

Home Assistant integration for Salus devices through the Salus Cloud (AWS Cognito login, device shadows over
AWS IoT MQTT). Supports iT600, Quantum, fan coil and iT800 (IT800TX) thermostats, TRVs, relays and smart plugs,
roller shutters, sensors and OneTouch rules; see [Supported devices](#supported-devices). iT500 thermostats, which
use an account and cloud of their own, are supported as well; see [Salus iT500](#salus-it500).

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
5. **Settings → Devices & services → Add integration → Salus Cloud**, choose the app you use (**Salus Smart Home**
   or **Salus iT500**) and log in with the email and password of that app.

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
| `button.<name>_refresh` | sends `sZDO:SetRefresh_d`: the thermostat reports all its values again | |

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

## How values update

- **Pushed changes:** what a device reports reaches Home Assistant within seconds over AWS IoT MQTT. Device states
  are also polled every 5 minutes as a safety net (every 30 seconds when pushed changes are not available).
- **The device decides when it reports.** An IT800TX reports its temperature when it changes by a step of its
  display resolution (0.5 °C by default, see `select.<name>_temperature_display_resolution`) and its humidity only
  after a large change: one kept reporting 57.48 % for 16 hours while the room had 61.84 %.
- **Humidity reading:** every 5 minutes the integration asks devices with a humidity sensor for a fresh reading,
  with the command the Salus app uses (`sHumiS:SetReadMeasuredValue`); the value arrives within a second. Change the
  interval, or set 0 to turn it off, under **Settings → Devices & services → Salus Cloud → Configure**. Each reading
  is a short radio message to the thermostat, which may run on batteries (the IT800TX reports battery power), so a
  longer interval saves battery; 5 minutes is a default, not a recommendation.
- **Refresh button:** asks the thermostat to report all its values again (`sZDO:SetRefresh_d`, about 40 seconds on
  an IT800TX), for example after changing something in the Salus app.

## Salus iT500

The iT500 does not use Salus Cloud: it has its own account (the one of the **Salus iT500** app) and its own cloud
(Arrayent, `sal-emea-p01-api.arrayent.com`). Choose **Salus iT500** when adding the integration. Since
salus-it500.com was taken offline (October 2026), integrations that read that website no longer work; this one uses
the API of the app instead.

Each thermostat of the account is a device named as in the app:

| Entity | Attribute | Values |
|---|---|---|
| `climate.<name>` | `A84` / `A85` temperature and target (0.01 °C), `A89` off, `A92` manual, `A88` temporary hold | heat / off, presets Schedule / Temporary hold / Manual |
| `sensor.<name>_temperature`, `…_target_temperature` | `A84`, `A85` | °C |
| `binary_sensor.<name>_heating` | `A87` boiler relay | Heating / Idle |
| `binary_sensor.<name>_frost_protection` | `A90` | |
| `binary_sensor.<name>_battery_low` (diagnostic) | `S03` | |
| `binary_sensor.<name>_cloud_connection` (diagnostic) | `online` | Connected / Disconnected |
| `sensor.<name>_signal_strength` (diagnostic, disabled) | `rfrssi` | dBm |
| `button.<name>_refresh` | `F` (refresh mode) | the thermostat reports all its values |
| Zone 2 (systems with an iT300TX, `S06` = 1) | `B84` … `B92` | climate "Zone 2", its temperatures, heating and frost protection |
| Hot water (`S06` = 2) | `C42` mode, `C45` status | select Auto / Once / On / Off, binary sensor Heating / Idle |

Values are read every minute; reading sends nothing to the thermostat. A command first puts the thermostat in refresh
mode (`F` = 60, "Turn On Refresh Mode for X Seconds" in the API's own words), so the battery thermostat takes it at
once, then sets one attribute per request (the iT500 reports `multiAttributeCapable` = false). The new value is shown
until the thermostat reports it, and the values are read again 10 seconds later. Setting a temperature in schedule
mode is held until the next change of the schedule, as on the thermostat. A temporary hold is ended through manual
mode, as a direct change does not stick. A password Salus stored without its special characters is retried without
them.

The protocol and the meaning of the attributes follow [ZaBug/salus-it500](https://github.com/ZaBug/salus-it500) and
[Peterka35/salus-it500-cloud](https://github.com/Peterka35/salus-it500-cloud) (both MIT) and the attribute
descriptions the API returns. The iT500 support has not been checked against a real iT500 yet; zone 2 and hot water
follow those descriptions only. If something looks wrong, please open an issue with the diagnostics file (phone
numbers and the geolocation rule are redacted).

## Supported devices

- Thermostats: **IT800TX**, iT600 (HTRP-RF, HTRS-RF, HTR-RF, TS600, VS10/VS20), Quantum (SQ610, SQ620),
  dial RF (SQ605), IT700TX / IT710TX, fan coil (FC600), RF (RSQ800WRF), Elypso (C900T, EL600T),
  TRVs with their own thermostat (TRV3RF, CTLV630), AO600RF / AO600, IT400TX, and **iT500** (see
  [Salus iT500](#salus-it500))
- TRVs controlled by a thermostat (it600TRV, it600MINITRV, TRV10RFM) and receivers: whether they heat
- Relays and plugs: SR600, SC812ZB, SC824ZB, SP600, SPE600, light switches; RS600 used as one or two relays
- Roller shutters and blinds: RS600
- Sensors: remote temperature sensors (PS600 and others) with their battery alarm
- Binary sensors: door / window contacts (SW600, OS600), water leak (WLS600), smoke, heat and motion sensors (MS600)
- Buttons: OneTouch rules

The models added in 2.4.0 and 2.5.0 have not been checked against real devices yet: they follow the property names
the Salus app itself uses for them (category by category, from the Salus web app). If one of them shows something
wrong, please open an issue with the diagnostics file. An IT400TX is recognized by its model name; it reports the
`sTherS` / `sComm` names under ep9 like an FC600, so it is controlled like one (off through the hold type alone, a new
temperature keeps its system mode).

Not supported yet: hot water timers (it600HW, TS600HW), energy readings of SPE600 plugs and ECM600 meters (the
scale of their values is not known yet), cooling and fan speed of fan coil thermostats (they are shown as heat / off),
lights, dimmers, door locks and sirens.

### How a device is recognized

Each device in the Salus device list has a category (the groups of the Salus app). The integration uses it first,
then the Salus app's model catalog, then the model name, so a device the Salus app knows gets the right entities even
when its exact model is new.

| Device | Shadow properties |
|---|---|
| iT600 / Quantum / dial RF / IT700TX thermostats | `ep9:sIT600TH:*` (see the table above) |
| IT800TX, TRV3RF, RSQ800WRF, Elypso thermostats | `ep1:sTherS:*`, `ep1:sComm:HoldType` |
| FC600 fan coil | `ep9:sTherS:*`, `ep9:sComm:HoldType`; turned off with the hold type alone, a new temperature keeps its system mode |
| Relays and plugs | every `sOnOffS:OnOff` endpoint; the first one is shown with the device name, further ones as "Relay <n>" |
| RS600 roller shutter (unless `ep1:sButtonS:Mode` is 1 or 3: one or two relays) | `ep1:sLevelS:CurrentLevel` (0 closed … 100 open), moved with `ep1:sLevelS:SetMoveToLevel` (`"64FFFF"` = open) |
| Remote temperature sensors | `sTempS:MeasuredValue_x100`, `sIASZS:ErrorIASZSLowBattery` / `sPowerS:ErrorPowerSLowBattery` |
| TRVs controlled by a thermostat, receivers | `ep6:sIT600I:RelayStatus` |
| Contacts, leak, smoke and motion sensors | `sIASZS:ErrorIASZSAlarmed1` |

The heating state of all thermostats is bit 0 of `RunningState` (an iT600 can report 129 and an FC600 33 while
heating).

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
| `properties.py` | Property names of the thermostat families (iT600, iT800, sTherS outside ep1) |
| `shadow.py` | Shadow property helpers: lookup, scaling, command names |
| `thermostat.py`, `settings.py`, `gateway.py` | What is shown for thermostats, app settings and gateways |
| `measurements.py` | What is shown for other devices: temperature sensors, TRV relays, battery alarms |
| `entity.py` and the platform modules | Home Assistant entities |
| `it500/` | Salus iT500 accounts: Arrayent API client, attribute decoding, coordinator and entities |

CI runs the tests against Home Assistant 2025.8.0 (minimum), 2026.2.3 and the latest release, ruff, plus
[hassfest](https://github.com/home-assistant/actions) and the [HACS action](https://hacs.xyz/docs/publish/action/).

Pull requests are welcome; every change to `main` goes through a pull request reviewed by the maintainer
([CODEOWNERS](.github/CODEOWNERS)).

## License

MIT. See [LICENSE](LICENSE).
