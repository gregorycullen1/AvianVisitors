# AvianVisitors round-panel kiosk

*The live collage, touchable, right on your Pi's desk.*

A round HDMI touchscreen wired to the *same* Pi that runs BirdNET-Pi, booting straight into a full-screen Chromium showing the live collage/stats/atlas UI - no taskbar, no desktop icons, no address bar. Unlike [`frame/`](../frame/README.md) (a second, low-power Pi that screenshots the site onto slow e-ink), this is the real interactive frontend running live on fast HDMI, so all the normal touch interactions - switching views, opening the menu, tapping into the atlas - work exactly as they do on a phone.

A round panel is a square framebuffer behind a circular bezel, so the frontend auto-detects a ~1:1 aspect-ratio screen and repositions its nav to stay inside the visible circle, then fades that nav out after a few seconds of no touch, leaving just the bird collage. See the `round-mode` rules in [`avian/frontend/styles.css`](../avian/frontend/styles.css) and the idle-fade logic in [`avian/frontend/apt.js`](../avian/frontend/apt.js) if you want to tune the timing or the offsets.

**This requires Raspberry Pi OS's Desktop image, not Lite.** Lite has no desktop session for a kiosk to run inside. The Desktop image already ships `lightdm` (autologin) and the `labwc` Wayland compositor with automatic touchscreen-to-output mapping - this installer just swaps labwc's default autostart (wallpaper + taskbar) for a full-screen Chromium.

---

### BOM

| Qty | Description | Price | Link |
|-----|-------------|-------|------|
| 1 | 5" 1080x1080 round HDMI touchscreen | ~$70-90 | [Waveshare](https://www.waveshare.com/5inch-1080x1080-lcd.htm) |

No extra Pi needed - this installs onto your existing BirdNET-Pi.

---

## 1. Wire it up

Connect the panel to your Pi over HDMI (+ USB for touch). Raspberry Pi OS Desktop auto-detects and maps the touch input to the right output on its own - nothing to configure. Boot the Pi as usual.

## 2. Set up autologin (one-time, if not already on)

The kiosk needs a logged-in desktop session to launch into. In `raspi-config` (or the Raspberry Pi Imager's customisation dialog when flashing): System Options -> Boot / Auto Login -> Desktop Autologin.

## 3. Run the installer

```bash
ssh <your-username>@birdnet.local
cd ~/BirdNET-Pi/kiosk
./install.sh
```

By default the kiosk points at `http://localhost/` - the same collage BirdNET-Pi already serves at `/`. To point it somewhere else instead:

```bash
./install.sh --url http://birdnet.local/
```

This writes `~/.config/labwc/autostart` (backing up anything already there first). Log out and back in, or reboot, for labwc to pick it up:

```bash
sudo reboot
```

## 4. Getting back to the normal desktop

```bash
ssh <your-username>@birdnet.local
rm ~/.config/labwc/autostart
sudo reboot
```

If you had a customized autostart before running the installer, it's sitting at `~/.config/labwc/autostart.pre-avian-kiosk.bak`.

## Tuning the round layout

- Idle-fade timeout: `IDLE_MS` near the "Round-panel idle-fade" block in `avian/frontend/apt.js`.
- Nav offsets/spacing: the `.round-mode` rules near the end of `avian/frontend/styles.css` - nudge `top`/`bottom` if your bezel crops slightly differently than the ideal circle the CSS was tuned against.
- Chromium flags (e.g. to disable pull-to-refresh bounce further, or to hide the cursor for a touch-only setup) live in `kiosk/autostart` - edit and re-run `install.sh`, or just edit `~/.config/labwc/autostart` directly on the Pi for a quick test.
