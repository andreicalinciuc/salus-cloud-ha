# Installation – Salus Cloud

## 1. Install the files

**HACS (recommended):** HACS → ⋮ → **Custom repositories** → `https://github.com/andreicalinciuc/salus-cloud-ha`,
type **Integration** → **Add**, then search **Salus Cloud** → **Download**.

**Manual:** copy the `salus_cloud` folder from the
[latest release](https://github.com/andreicalinciuc/salus-cloud-ha/releases/latest) to `<config>/custom_components/`.

## 2. Restart Home Assistant

**Settings** → **System** → **Restart**.

## 3. Add the integration

1. **Settings** → **Devices & services** → **Add integration**.
2. Search **Salus Cloud**.
3. Log in with the email and password of your Salus Smart Home app account.

iT600 and iT800 thermostats, relays, sensors and OneTouch rules on the account are added automatically. Each thermostat gets a climate
entity plus one entity per value it reports (temperature, humidity, preset, heating, battery and so on); see the
[README](../../README.md#entities-per-thermostat).

## Troubleshooting

- **Invalid email or password:** check the login in the Salus app and use the email address, not a username.
- **No devices found:** make sure the devices are paired in the Salus app and the gateway is online, then reload the
  integration.
- **Reading works but control does not:** Home Assistant must reach `*.iot.eu-central-1.amazonaws.com` on port 443.
- **A device reports something unexpected:** device page → ⋮ → **Download diagnostics** and attach the file to an
  [issue](https://github.com/andreicalinciuc/salus-cloud-ha/issues).

Debug logging:

```yaml
logger:
  default: info
  logs:
    custom_components.salus_cloud: debug
```
