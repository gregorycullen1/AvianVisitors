#!/usr/bin/env bash
# Renders the e-ink frame collage via shoot.py, reading FRAME_WINDOW_HOURS
# and FRAME_TOP_N from birdnet.conf so the AvianVisitors admin panel's
# "frame window" setting can control them without editing this script or
# its systemd unit.
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
TOP_N=0
BADGE=1
if [ -f "$CONF" ]; then
  V="$(sed -n 's/^FRAME_WINDOW_HOURS=\(.*\)$/\1/p' "$CONF" | tr -d '"' | head -1)"
  [ -n "$V" ] && WINDOW_HOURS="$V"
  V="$(sed -n 's/^FRAME_TOP_N=\(.*\)$/\1/p' "$CONF" | tr -d '"' | head -1)"
  [ -n "$V" ] && TOP_N="$V"
  V="$(sed -n 's/^FRAME_BATTERY_BADGE=\(.*\)$/\1/p' "$CONF" | tr -d '"' | head -1)"
  [ "$V" = "0" ] && BADGE=0
fi

OUT="$HOME/BirdSongs/Extracted/frame.png"
SIG="$HOME/BirdSongs/Extracted/frame.sig"
E6="$HOME/BirdSongs/Extracted/frame-e6.png"
BATT="$HOME/BirdSongs/Extracted/frame-battery.txt"

.venv-shoot/bin/python3 shoot.py --url http://localhost \
  --title "Avian Visitors" --subtitle "Just Heard" \
  --width 480 --height 800 --dsf 1 --mat 0.0 --collage-vh 72 --small-floor 0.07 \
  --window-hours "$WINDOW_HOURS" --top-n "$TOP_N" \
  --out "$OUT"

# Sidecar signature: the species signature for the SAME window + top-N cap
# just rendered with, so a display.py elsewhere can tell "did anything
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
print(display.signature(display.cap_top_n(species, $TOP_N)))
" > "$SIG"

# Panel-ready copy for microcontroller frames (avian/api/frame.php):
# pre-rotated and pre-dithered to exact E6 palette colours, the same
# conversion push_panel() does for epd7in3e, so esp32-photoframe displays
# it as-is instead of re-dithering (see display.e6_panel_image). Written
# via a temp file + mv so frame.php never serves a half-written PNG.
# frame.php stores the frame's last-reported battery level in $BATT; the
# level actually drawn goes to frame-e6.batt ("off" when FRAME_BATTERY_BADGE
# is 0) so frame.php can key its ETag off what this image really shows
# (-low forces a refresh when the drawn level first goes low, -nb when the
# badge is switched off) - never off a setting the image doesn't reflect yet.
# frame.png itself stays untouched for display.py consumers.
.venv-shoot/bin/python3 -c "
import sys
sys.path.insert(0, '.')
from PIL import Image
import display
pct = display.read_frame_battery('$BATT') if $BADGE else None
display.e6_panel_image(Image.open('$OUT'), battery=pct).save('$E6.tmp', format='PNG')
open('$E6.batt.tmp', 'w').write('off' if not $BADGE else '' if pct is None else str(pct))
" && mv -f "$E6.batt.tmp" "${E6%.png}.batt" && mv -f "$E6.tmp" "$E6"
