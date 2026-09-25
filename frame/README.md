# AvianVisitors e-ink frame

*The last 24h of birds, framed on the wall by your window.*

A [Pimoroni Inky Impression 13.3"](https://amzn.to/4xlAWr3) (Spectra 6) mirroring the live collage. A Pi screenshots the site, mats it onto an A5 opening, and pushes to the panel, refreshing only when the birds change. Build one of your own at [theodore.net/projects/AvianVisitors#frame-ous](https://theodore.net/projects/AvianVisitors/#frame-ous).

![](https://theodore.net/assets/images/AvianVisitors/final.jpg)

---

### BOM

| Qty | Description | Price | Link |
|-----|-------------|-------|------|
| 1 | Raspberry Pi Zero (2) W | ~$35 | [Amazon](https://amzn.to/49Xp58I) |
| 1 | 13.3" E Ink Display     | $299.99 | [Amazon](https://amzn.to/4xlAWr3) |
| 1 | A4 Wood Photo Frame    | $21.99 | [Amazon](https://amzn.to/3RWFbJE) |
| 1 | Long, Flat Micro USB Cable    | $7.99 | [Amazon](https://a.co/d/0a59rKSk) |
| 1 | Flat USB Brick    | $7.59 | [Amazon](https://amzn.to/3S4CtSs) |
| | **Total** | **~$372** | | |

CAD + 3d print files can be found in [`hardware/`](hardware/).

### Kits

I offer the frame and the bird mic as separate electronics kits. I put up a store for some of my open-source projects and will soon be able to offer kits cheaper than buying all the components individually, once I start buying in bulk.

- [Frame kit](https://theodore.net/store/avian-visitors/)
- [Bird mic kit](https://theodore.net/store/avian-mic/)

---

## 1. Flash the SD card

Flash an sd card with Raspberry Pi OS Lite (64-bit) via [Raspberry Pi Imager](https://www.raspberrypi.com/software/). In the customisation dialog set:

- Username
- WiFi SSID + password
- Hostname: `birdpic`
- Enable SSH with password auth

Then install in Pi and power up.

## 2. Run the installer

```bash
ssh <your-username>@birdpic.local
sudo apt update && sudo apt install -y git
git clone https://github.com/Twarner491/AvianVisitors
cd AvianVisitors/frame
```

Pick how the frame gets its birds:

```bash
# Pair with your bird mic on the same network (birdnet.local). The default.
./install.sh

# No microphone: draw the collage from BirdWeather for any ZIP code.
./install.sh --bird-weather --zip 94107

# Bird mic hosted at a public URL: point the frame straight at it.
./install.sh --image-url https://bird.onethreenine.net/frame.png?k=YOUR_FRAME_KEY
```

Each one enables SPI + I2C, installs the deps and a systemd timer, writes `~/.birdframe/config.toml`, and reboots once to bring SPI up. Full options live in [`config.example.toml`](config.example.toml).

Add `--panel epd7in3e` to any of the above for a [Waveshare RPi Zero PhotoPainter](https://www.waveshare.com/wiki/RPi_Zero_PhotoPainter) (800×480, 6-colour) instead of the Inky 13.3" - it's used in its own enclosure rather than a separate wood frame, so the collage fills the whole screen edge-to-edge instead of floating in an A5 mat opening. Its driver is vendored in [`waveshare_epd/`](waveshare_epd/) (Waveshare doesn't publish it as a pip package).

BirdWeather mode renders on the Pi from this repo's illustrations on GitHub, so there is no image set to copy over. ZIP codes with no station nearby fall back to the closest ones. If you are far from any BirdWeather station, add `--ebird-key <key>` (a free key from [ebird.org/api/keygen](https://ebird.org/api/keygen)) and the frame fills from eBird sightings instead.

The bundled illustrations center on the western U.S. If birds near your ZIP aren't in the set you cloned, the installer flags them and the frame skips them until they exist. To generate them, run [`generate_illustrations.py`](generate_illustrations.py) on a laptop or workstation (it uses the same rembg cutout as the rest of the pipeline, which the Pi can't fit in memory), passing your ZIP and a paid Google Gemini key, then commit the new cutouts or copy them to the Pi:

```bash
python3 generate_illustrations.py --zip 10001 --gemini-key YOUR_GEMINI_KEY
```

It generates only the species you're missing; `--country` and `--sample` carry through for non-US postcodes or a wider region.

---

### Split install: a weak Pi (e.g. a Zero W) driving the panel, a stronger one rendering

`shoot.py` needs a real headless browser and won't run on a Pi Zero W (see its own docstring). If your display Pi is that weak, keep it in `--image-url` mode fetching from a separate, stronger, always-on machine that runs the rendering instead - typically the same Pi that already runs BirdNET-Pi:

1. On the stronger Pi: clone this repo (or copy `frame/`), `python3 -m venv .venv-shoot && .venv-shoot/bin/pip install -r requirements-shoot.txt && .venv-shoot/bin/playwright install-deps chromium && .venv-shoot/bin/playwright install chromium`.
2. Edit [`render_frame.sh`](render_frame.sh)'s `shoot.py` flags to taste (title/subtitle, size, layout tuning), then install [`systemd/birdframe-shoot.service`](systemd/birdframe-shoot.service) + [`.timer`](systemd/birdframe-shoot.timer) (adjust `User=`/paths first) so it renders on the same 10-minute cadence, writing straight into a path Caddy already serves (e.g. BirdNET-Pi's own `Extracted/` dir needs no Caddy config changes at all).
3. On the display Pi: `./install.sh --image-url http://<stronger-pi>.local/frame.png [--panel epd7in3e]`.

No display Pi at all? An ESP32 PhotoPainter can poll the render directly - see [below](#esp32-frame-waveshare-esp32-s3-photopainter).

`render_frame.sh` reads `FRAME_WINDOW_HOURS`, `FRAME_TOP_N` and `FRAME_BATTERY_BADGE` from `birdnet.conf` if present (falling back to 24h / show-all / badge on) - on an AvianVisitors install these, plus `FRAME_DAYLIGHT_ONLY` for the ESP32 frame, are whitelisted in [`avian/api/config.php`](../avian/api/config.php), so they're adjustable from the admin panel's Settings without SSH. `FRAME_TOP_N` caps the collage to the N most-active species by call count; pairing a short window (e.g. 3h) with a small cap (e.g. 6) keeps each bird bigger and the roster actually turning over, instead of one slowly-accumulating full-day collage. The panel still only physically refreshes when that capped roster changes (or once a day, as a heal) - a shorter window and a lower cap doesn't mean more wear, just a more current picture whenever it does refresh.

---

### ESP32 frame: Waveshare ESP32-S3-PhotoPainter

A [Waveshare ESP32-S3-PhotoPainter](https://www.waveshare.com/wiki/ESP32-S3-PhotoPainter) (7.3" Spectra 6 / E6, 800×480, wood frame) can replace the display Pi entirely. There's no OS or SD card to maintain, and it deep-sleeps between checks, so it can run on its battery. It needs a machine running the [split-install](#split-install-a-weak-pi-eg-a-zero-w-driving-the-panel-a-stronger-one-rendering) renderer - typically the BirdNET-Pi itself.

**Firmware.** Waveshare's stock firmware can't poll a URL, so flash [esp32-photoframe](https://github.com/aitjcize/esp32-photoframe) (MIT, board `waveshare_photopainter_73`). It supports the E6 panel natively, even though its README calls it "7-color". Back up the stock firmware first, then flash the merged image from its Releases:

```bash
esptool --chip esp32s3 --port /dev/cu.usbmodemXXXX read-flash 0 0x1000000 photopainter-stock-backup-16MB.bin
esptool --chip esp32s3 --port /dev/cu.usbmodemXXXX --baud 921600 write-flash 0x0 photoframe-firmware-waveshare_photopainter_73-merged.bin
```

The stock firmware sleeps, which drops it off USB, so put the board in download mode first: hold **BOOT**, tap **PWR**, release **BOOT**. Any app that grabs Espressif serial ports will block `esptool`, so quit those first.

**Wi-Fi + settings.** On first boot it opens a `PhotoFrame - XXXXXX` access point. Join it and enter your Wi-Fi (2.4 GHz only), or use the ESP Frame companion app. Then set, either at `http://photoframe.local` or with `PATCH /api/config`:

| Setting | Value |
|---|---|
| `display_orientation` | `portrait` |
| `rotation_mode` | `url` |
| `image_url` | `http://<render-pi-IP>/avian/api/frame.php` |
| `auto_rotate` | `true` |
| `timezone` | your POSIX zone, e.g. `PST8PDT,M3.2.0,M11.1.0` |

Use the render Pi's **IP address**, not `<name>.local`. The firmware's HTTP client can't resolve mDNS names, and fails with `ESP_ERR_HTTP_CONNECT`. Give the render Pi a DHCP reservation so that IP doesn't change. The checking schedule (`rotate_cron`) is set by the Pi (see below), so you don't need to set it here.

**What [`frame.php`](../avian/api/frame.php) does:**

- **Skips refreshes that wouldn't change anything.** The ETag is taken from `frame.sig`, not the PNG, so the panel gets a `304` and skips its ~30s refresh unless the roster changed. It also does a daily heal refresh (`?heal=N` hours; `0` disables it).
- **Serves a panel-ready image.** It serves `frame-e6.png` rather than `frame.png`: already rotated to the panel's native 800×480 and dithered to the six exact E6 ink colours (`display.e6_panel_image`, the same snap and quantize `push_panel()` does for `epd7in3e`). The firmware displays a palette-exact, native-size PNG untouched. Left to its own dithering, it speckles the paper background, because it dithers against a measured palette whose white isn't neutral. `?raw=1` serves the unprocessed `frame.png`.
- **Battery badge.** The firmware reports its level in an `X-Battery-Percentage` header on every fetch. `frame.php` stores it in `frame-battery.txt`, and the next render draws it in the lower-right corner, filled red at 20% or below. The badge is hidden if the latest report is over 12 hours old. It doesn't force a refresh by itself; it updates whenever the panel next refreshes. The exception is when the drawn level first drops to 20% or below, which forces one refresh. Turn it off with `FRAME_BATTERY_BADGE`.
- **Checking schedule.** Every `200` response carries `rotate_cron` in `X-Config-Payload`: every 15 minutes around the clock, or with `FRAME_DAYLIGHT_ONLY`, every 30 minutes from 5:00 to 21:30. The firmware ignores the payload on a `304`, so toggling this costs one refresh to deliver. This makes Settings the source of truth for the schedule: anything set in the frame's own web UI is overwritten on its next refresh.

**Battery.** Charging over USB with the battery connected works on v2 boards, which use the TG28 power chip. On the original AXP2101 boards, running on USB and battery together causes random restarts, so use one or the other. Expect weeks of battery life, not months. Even in deep sleep the whole board draws about 1 mA, and it wakes 30-100 times a day. `FRAME_DAYLIGHT_ONLY` roughly halves the number of wake-ups.
