#!/usr/bin/env bash
# Renders the e-ink frame collage via shoot.py, reading FRAME_WINDOW_HOURS
# from birdnet.conf so the AvianVisitors admin panel's "frame window"
# setting can control it without editing this script or its systemd unit.
#
# Assumes a "shooter" setup: this Pi has a .venv-shoot/ (requirements-shoot.txt)
# and writes straight into BirdNET-Pi's own Caddy-served webroot, matching
# what a split install (this Pi renders, a separate lightweight Pi/panel
# just fetches image_url and pushes to its e-ink panel) needs. Not part of
# install.sh - see the main README for the split-install writeup.
set -euo pipefail
cd "$(dirname "$0")"

CONF=/etc/birdnet/birdnet.conf
[ -f "$CONF" ] || CONF="$HOME/BirdNET-Pi/birdnet.conf"
WINDOW_HOURS=24
if [ -f "$CONF" ]; then
  V="$(sed -n 's/^FRAME_WINDOW_HOURS=\(.*\)$/\1/p' "$CONF" | tr -d '"' | head -1)"
  [ -n "$V" ] && WINDOW_HOURS="$V"
fi

OUT="$HOME/BirdSongs/Extracted/frame.png"
SIG="$HOME/BirdSongs/Extracted/frame.sig"

.venv-shoot/bin/python3 shoot.py --url http://localhost \
  --title "Avian Visitors" --subtitle "Just Heard" \
  --width 480 --height 800 --dsf 1 --collage-vh 66 --small-floor 0.07 \
  --window-hours "$WINDOW_HOURS" \
  --out "$OUT"

# Sidecar signature: the species signature for the SAME window just
# rendered with, so a display.py elsewhere can tell "did anything
# meaningfully change" from the underlying data rather than the rendered
# pixels, which differ render-to-render even for identical data (the site
# re-rolls small cosmetic randomness - e.g. a bird's perched-vs-flight
# pose - on every fresh page load, which shoot.py always is). See
# image_change_signal()'s docstring in display.py.
.venv-shoot/bin/python3 -c "
import sys
sys.path.insert(0, '.')
import display
species = display.fetch_recent('http://localhost', $WINDOW_HOURS, 15)
print(display.signature(species))
" > "$SIG"
