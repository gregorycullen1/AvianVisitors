#!/usr/bin/env bash
# Install a wireless RTSP mic relay on a spare Pi (a Zero W, 3B+, etc.) -
# streams a USB mic over the LAN so BirdNET-Pi's RTSP_STREAM setting can
# point at it instead of a locally-plugged mic. Useful when the mic needs
# to live somewhere the main Pi doesn't (or vice versa).
#
# Run this ON THE SPARE PI with the mic plugged in, not the main
# BirdNET-Pi. It only sets up the streaming side; point RTSP_STREAM at
# the URL it prints when done (admin panel -> Settings -> Audio source,
# or birdnet.conf by hand over SSH).
#
#   ./install.sh
set -euo pipefail
cd "$(dirname "$0")"
MICDIR="$(pwd)"

MEDIAMTX_VERSION=v1.19.2

if ! sudo -n true 2>/dev/null; then
  echo "This needs passwordless sudo for $USER. Raspberry Pi OS's default" >&2
  echo "'pi' user has this out of the box; if you're on a different" >&2
  echo "username (or it's been tightened), set it up first:" >&2
  echo "  echo \"$USER ALL=(ALL) NOPASSWD: ALL\" | sudo tee /etc/sudoers.d/010-$USER-nopasswd" >&2
  echo "  sudo chmod 440 /etc/sudoers.d/010-$USER-nopasswd" >&2
  exit 1
fi

echo "1/6  Detecting the USB microphone..."
# The stable plughw:CARD=<name> form, not hw:N - N is a card *index* that
# can shift across reboots (e.g. if another USB audio device is ever
# plugged in first), while the name is stable.
ALSA_DEVICE="$(arecord -L 2>/dev/null | grep '^plughw:CARD=' | head -1)"
if [ -z "$ALSA_DEVICE" ]; then
  echo "No USB microphone detected (arecord -l shows no capture devices)." >&2
  echo "Plug it into a USB port (not just power) and re-run." >&2
  exit 1
fi
echo "     Found: $ALSA_DEVICE"

echo "2/6  Installing ffmpeg + alsa-utils..."
# This pulls in a surprisingly large, unrelated dependency tree - mesa,
# LLVM, even a speech-recognition language pack - because Debian bundles
# ffmpeg/ffplay/ffprobe as one package and ffplay needs SDL2. Harmless
# (nothing in that tree is loaded by the audio-only command below), just
# slow to download on a first-gen/weak board's WiFi. Can take several
# minutes on a Pi Zero W; a 3B+ or newer is much faster.
sudo apt-get update -qq
sudo apt-get install -y -qq ffmpeg alsa-utils

echo "3/6  Installing mediamtx $MEDIAMTX_VERSION..."
ARCH="$(uname -m)"
case "$ARCH" in
  armv6l)  MTX_ARCH=armv6 ;;   # Pi Zero (1st gen)/Zero W, original 1B
  armv7l)  MTX_ARCH=armv7 ;;   # 32-bit Pi OS on a 3/4/5-class board
  aarch64) MTX_ARCH=arm64 ;;   # 64-bit Pi OS on a 3/4/5-class board
  x86_64)  MTX_ARCH=amd64 ;;
  *) echo "Unrecognised architecture: $ARCH (mediamtx has no matching release build)" >&2
     exit 1 ;;
esac
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
curl -sL -o "$TMP/mediamtx.tar.gz" \
  "https://github.com/bluenviron/mediamtx/releases/download/$MEDIAMTX_VERSION/mediamtx_${MEDIAMTX_VERSION}_linux_${MTX_ARCH}.tar.gz"
tar -xzf "$TMP/mediamtx.tar.gz" -C "$TMP"
sudo install -m 755 "$TMP/mediamtx" /usr/local/bin/mediamtx

echo "4/6  Writing mediamtx config..."
sudo mkdir -p /usr/local/etc
sudo cp "$MICDIR/mediamtx.yml" /usr/local/etc/mediamtx.yml

echo "5/6  Installing systemd services..."
sed "s|/home/monalisa|$HOME|g; s|User=monalisa|User=$USER|" \
  "$MICDIR/systemd/mediamtx.service" | sudo tee /etc/systemd/system/mediamtx.service >/dev/null
# ALSA_DEVICE can contain '/' (unlikely, but not guaranteed not to) -
# use a sed delimiter that won't collide with it.
sed "s|/home/monalisa|$HOME|g; s|User=monalisa|User=$USER|; s#__ALSA_DEVICE__#$ALSA_DEVICE#" \
  "$MICDIR/systemd/birdmic-publish.service" | sudo tee /etc/systemd/system/birdmic-publish.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now mediamtx.service
sleep 2
sudo systemctl enable --now birdmic-publish.service

echo "6/6  Verifying the stream..."
sleep 3
if command -v ffprobe >/dev/null 2>&1 && \
   ffprobe -hide_banner -rtsp_transport tcp -i rtsp://127.0.0.1:8554/birdmic 2>&1 | grep -q "Stream #0"; then
  echo "     Stream confirmed working."
else
  echo "     Could not confirm the stream from here - check:" >&2
  echo "       sudo journalctl -u mediamtx -u birdmic-publish -n 30" >&2
fi

IP="$(hostname -I | awk '{print $1}')"
cat <<DONE

Installed. This Pi is now streaming its mic at:
  rtsp://$IP:8554/birdmic

Point BirdNET-Pi at it: on the main Pi's admin panel, go to Settings ->
Audio source and paste that URL in (or edit RTSP_STREAM in birdnet.conf
by hand over SSH, then restart birdnet_recording + birdnet_analysis).

If the main Pi also runs BirdNET-Pi's live-listen feature
(livestream.service), know that a weak single-core board (a Zero W, or
the original 3B) can struggle to serve two simultaneous readers
(recording + live-listen) pulling from it at once - a 3B+/4/5 has real
headroom for both; a Zero W does not. See README.md's "known issues"
section for the wider list of things that turned out to matter.

Logs:      sudo journalctl -u mediamtx -u birdmic-publish -f
Re-check:  ffprobe -rtsp_transport tcp -i rtsp://localhost:8554/birdmic
DONE
