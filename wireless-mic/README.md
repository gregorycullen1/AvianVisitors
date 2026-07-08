# AvianVisitors wireless mic

*The mic lives by the window; the Pi doesn't have to.*

A spare Pi streams the USB mic over the LAN via RTSP, so BirdNET-Pi's own `RTSP_STREAM` setting - a first-class, already-supported feature of upstream BirdNET-Pi (`scripts/birdnet_recording.sh`) - pulls audio from across the room/house instead of needing a local mic plugged directly into the main Pi.

---

### BOM

| Qty | Description | Notes |
|-----|-------------|-------|
| 1 | A spare Raspberry Pi | See "Which Pi" below - board choice matters more than it looks like it should. |
| 1 | USB microphone | The same lavalier mic from the main [BOM](../README.md#bom) works fine. |
| 1 | Micro SD card | 8GB+ is plenty; this installs nothing heavy. |

No HAT, no extra parts - just a second, cheap Pi with the mic plugged into it instead of the main one.

### Which Pi

Anything with a USB port and WiFi works, but two things turned out to matter in practice, not just in theory:

- **CPU**: `mediamtx` + `ffmpeg` together aren't free, and a single-core board (the original Pi Zero W) runs them close to 100% of its one core just for this - deploying without headroom to spare. A quad-core board (3B+/4/5/Zero 2 W) drops that to roughly 10-15% of one core, with no perceptible difference otherwise.
- **WiFi chip**: the original Zero W and the plain 3 Model B share the same older, single-band chip (Broadcom BCM43438), which under sustained streaming can intermittently stall its firmware's control channel for a second or two - self-healing (the retry loop below absorbs it), but a real, measurable source of brief audio gaps. The 3B+ (BCM43455, dual-band) doesn't exhibit this.

A 3B+ is the sweet spot: cheap, quad-core, and the better radio. A Zero W works and is what this was originally built and tested on - just expect the occasional multi-second gap in a recording, which upstream's retry logic recovers from on its own within a few seconds either way.

---

## 1. Flash the SD card

Raspberry Pi OS **Lite** (32- or 64-bit, either works - pick 64-bit unless the board is ARMv6-only, i.e. an original Zero/Zero W/1B, which *only* runs 32-bit). In [Raspberry Pi Imager](https://www.raspberrypi.com/software/)'s customisation dialog, set:

- Username, WiFi SSID + password, WiFi country
- Hostname: something distinct from your main Pi (e.g. `birdmic`)
- Enable SSH - drop in your own machine's public key here for key auth from the start

## 2. Wire it up

Plug the USB mic into the Pi's USB-A port (a Zero W has only one USB *data* port via its micro-USB OTG connector - power it from the separate PWR port, mic goes in the other one; a 3B+ and up have plenty of full-size USB-A ports, no OTG dance needed).

## 3. Run the installer

```bash
ssh <your-username>@birdmic.local
sudo apt update && sudo apt install -y git
git clone https://github.com/Twarner491/AvianVisitors
cd AvianVisitors/wireless-mic
./install.sh
```

Installs ffmpeg + [mediamtx](https://github.com/bluenviron/mediamtx) (the RTSP relay), auto-detects your mic and its architecture, and prints the stream URL when done - something like `rtsp://192.168.1.50:8554/birdmic`.

## 4. Point BirdNET-Pi at it

On the **main** Pi: admin panel → Settings → **Audio source**, paste in the URL from step 3. Or by hand over SSH: set `RTSP_STREAM="rtsp://<mic-pi-ip>:8554/birdmic"` in `birdnet.conf`, then `sudo systemctl restart birdnet_recording birdnet_analysis`.

To switch back to a local mic later, plug it into the main Pi and clear `RTSP_STREAM` (blank in the admin panel, or delete the line in `birdnet.conf`) - `birdnet_recording.sh` falls back to the local mic automatically when it's unset.

---

## Known issues (found the hard way)

**Don't run `livestream.service` and `birdnet_recording` against a weak mic Pi at the same time.** BirdNET-Pi's built-in "Live Audio Stream" feature pulls the RTSP stream *independently* of `birdnet_recording` - meaning two concurrent readers hit the mic Pi's `mediamtx` at once. On a single-core board this genuinely overloaded it (load average 7+, dropped audio, detections stopped), even though a single reader alone was comfortably fine. If you're on a Zero W or similarly weak board and don't need the live-listen feature, leave `livestream.service` disabled (`sudo systemctl disable --now livestream`). A 3B+ or better has enough headroom for both at once.

**Don't SSH into the mic Pi more than you have to while it's live.** Sounds strange, but on a single-core board, every SSH login spins up a per-session `systemd --user` + `dbus-daemon` + `mpris-proxy` trio that itself costs real CPU (measured: 70-100% of the one core, however briefly) - repeated monitoring logins can look just like the streaming pipeline being unstable when it's actually your own troubleshooting causing the blips. If you need to check on it, do it, then leave it alone for a few minutes before concluding anything's actually wrong.

**Raw PCM audio (`pcm_s16be`), not a compressed codec.** Tried Opus first, expecting a real CPU win on a weak board - there wasn't one, because the bulk of the CPU cost turned out to be ffmpeg's own RTSP/network handling, not encoding. So this streams uncompressed (lossless, best for species-ID accuracy; at mono/48kHz that's ~768kbps, trivial on a LAN). One real gotcha: **little-endian PCM (`pcm_s16le`) doesn't work** - ffmpeg's `rtsp` muxer generates an SDP mediamtx rejects (`invalid SDP: media 1 is invalid: clock rate not found`). Big-endian (`pcm_s16be`, also the RTP `L16` standard's byte order) works fine; this is what `install.sh` sets up.

**Both RTSP transports enabled, not just TCP.** `birdnet_recording.sh` doesn't specify `-rtsp_transport` when it pulls the stream, so it uses ffmpeg's default negotiation - the server has to accept whatever that picks, or the very first connection fails with `461 Unsupported Transport`. `mediamtx.yml` here allows `[udp, multicast, tcp]` for exactly this reason.

**`sudo` isn't passwordless by default on every image/board combination.** Pi OS's `pi` user usually has it out of the box; a custom username in the Imager sometimes doesn't. `install.sh` checks for this up front and tells you the one-line fix rather than failing partway through a package install.

**Verify the mic actually captures real audio, not silence**, especially after any change: `ffmpeg -rtsp_transport tcp -i rtsp://localhost:8554/birdmic -t 5 -f wav /tmp/test.wav` on the mic Pi, then check it's not just near-zero samples (a bad USB port, a muted mic, or a wrong ALSA device can all produce a "working" stream that's actually silent).
