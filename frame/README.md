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

`render_frame.sh` reads `FRAME_WINDOW_HOURS` and `FRAME_TOP_N` from `birdnet.conf` if present (falling back to 24h / show-all) - on an AvianVisitors install both are whitelisted in [`avian/api/config.php`](../avian/api/config.php), so they're adjustable from the admin panel's Settings without SSH. `FRAME_TOP_N` caps the collage to the N most-active species by call count; pairing a short window (e.g. 3h) with a small cap (e.g. 6) keeps each bird bigger and the roster actually turning over, instead of one slowly-accumulating full-day collage. The panel still only physically refreshes when that capped roster changes (or once a day, as a heal) - a shorter window and a lower cap doesn't mean more wear, just a more current picture whenever it does refresh.
