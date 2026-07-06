#!/usr/bin/env bash
# Install the AvianVisitors round-panel kiosk on a Raspberry Pi that's
# already running BirdNET-Pi + the avian frontend (this installs onto the
# SAME Pi as the mic - it's not a second device like frame/ is).
#
# Targets Raspberry Pi OS's stock Desktop image (Bookworm/Trixie), which
# ships lightdm + the labwc Wayland compositor and already handles
# autologin and touchscreen mapping - this just swaps labwc's autostart
# (desktop wallpaper + taskbar) for a full-screen Chromium kiosk. It does
# NOT apply to Raspberry Pi OS Lite - Lite has no desktop session for a
# kiosk to run inside; reflash with the Desktop image if that's what
# you're on.
#
#   ./install.sh                  kiosk shows http://localhost/
#   ./install.sh --url <URL>      point at a different URL instead
set -euo pipefail
cd "$(dirname "$0")"
KIOSK="$(pwd)"

URL="http://localhost/"
while [ $# -gt 0 ]; do
  case "$1" in
    --url) [ $# -ge 2 ] || { echo "--url needs a value, e.g. --url http://birdnet.local/" >&2; exit 1; }
           URL="$2"; shift 2 ;;
    --url=*) URL="${1#*=}"; shift ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done

# Validate up front: this lands verbatim in a shell script that labwc execs.
case "$URL" in
  http://*|https://*) ;;
  *) echo "--url must start with http:// or https://" >&2; exit 1 ;;
esac
if printf '%s' "$URL" | LC_ALL=C grep -q '[^A-Za-z0-9._~:/?#@!$&()*+,;=%-]'; then
  echo "--url has characters that are not allowed in a URL" >&2
  exit 1
fi

if ! command -v labwc >/dev/null 2>&1; then
  echo "labwc not found - this installer targets Raspberry Pi OS's Desktop" >&2
  echo "image (Bookworm/Trixie), which ships labwc + lightdm autologin." >&2
  echo "If you're on Raspberry Pi OS Lite, reflash with the Desktop image." >&2
  exit 1
fi
if ! command -v chromium >/dev/null 2>&1; then
  echo "chromium not found (expected on Raspberry Pi OS Desktop) - install it:" >&2
  echo "  sudo apt-get install -y chromium" >&2
  exit 1
fi

echo "1/4  Writing ~/.config/labwc/autostart..."
mkdir -p "$HOME/.config/labwc"
DEST="$HOME/.config/labwc/autostart"
if [ -f "$DEST" ] && ! grep -q "AvianVisitors round-panel kiosk autostart" "$DEST"; then
  cp "$DEST" "$DEST.pre-avian-kiosk.bak"
  echo "     Existing $DEST didn't look like ours - backed it up to"
  echo "     $DEST.pre-avian-kiosk.bak before overwriting."
fi
sed "s|^AV_KIOSK_URL=.*|AV_KIOSK_URL=\"$URL\"|" "$KIOSK/autostart" > "$DEST"

# labwc-pi (Raspberry Pi's wrapper around labwc) always runs `labwc -m`
# (--merge-config), which merges the system-wide
# /etc/xdg/labwc/autostart with ours instead of ours replacing it - so
# the stock desktop wallpaper (pcmanfm-pi) and taskbar (wf-panel-pi)
# would still launch alongside Chromium even with our own autostart in
# place. Comment them out at the source instead of fighting the merge.
SYS_AUTOSTART=/etc/xdg/labwc/autostart
echo "2/4  Disabling the desktop wallpaper + taskbar in $SYS_AUTOSTART..."
if [ -f "$SYS_AUTOSTART" ]; then
  if [ ! -f "$SYS_AUTOSTART.pre-avian-kiosk.bak" ]; then
    sudo cp "$SYS_AUTOSTART" "$SYS_AUTOSTART.pre-avian-kiosk.bak"
  fi
  sudo sed -i -E \
    's@^(/usr/bin/lwrespawn /usr/bin/(pcmanfm-pi|wf-panel-pi).*)$@# avian-kiosk: disabled - \1@' \
    "$SYS_AUTOSTART"
else
  echo "     $SYS_AUTOSTART not found - nothing to disable, skipping." >&2
fi

# Raspberry Pi's autotouch (an XDG-autostart helper that runs on every
# labwc login) auto-writes ~/.config/labwc/rc.xml's <touch> element with
# mouseEmulation="yes" the first time it sees a touchscreen, for
# compatibility with older X11/LXDE apps that don't understand touch
# input. That's wrong for us: with mouse emulation on, a touch-drag turns
# into a synthetic mouse-drag, and browsers treat a mouse-drag over text
# or images as a selection, not a scroll - which is exactly the "won't
# scroll, just highlights everything" symptom on pages like the atlas.
# Chromium handles real touch input (pan-to-scroll, tap-to-click) natively,
# so switch it off. autotouch only writes this once and skips any rc.xml
# that already has a mouseEmulation attribute (checked via `grep -qs
# "touch.*mouseEmulation"` in its own source), so this survives reboots.
RC_XML="$HOME/.config/labwc/rc.xml"
echo "3/4  Disabling touch-to-mouse emulation in $RC_XML..."
if [ -f "$RC_XML" ] && grep -q 'mouseEmulation="yes"' "$RC_XML"; then
  cp "$RC_XML" "$RC_XML.pre-avian-kiosk.bak"
  sed -i 's/mouseEmulation="yes"/mouseEmulation="no"/' "$RC_XML"
elif [ -f "$RC_XML" ]; then
  echo "     Already set (or no touch device configured yet) - nothing to do."
else
  echo "     $RC_XML doesn't exist yet - it's created the first time labwc" >&2
  echo "     sees the touchscreen. Re-run install.sh after your first login" >&2
  echo "     if you still see selection-instead-of-scroll behaviour." >&2
fi

echo "4/4  Done."

cat <<DONE

Installed. Log out and back in (or reboot: sudo reboot) to see it - labwc
only reads autostart when a session starts.

The Pi will come up straight into a full-screen Chromium pointed at
  $URL
No taskbar, no desktop icons. Chrome (the nav bar, not the browser) fades
out after a few seconds of no touch and comes back on the next tap - never
auto-advances between views.

To get back to the normal desktop: SSH in and run
  rm ~/.config/labwc/autostart
  sudo cp $SYS_AUTOSTART.pre-avian-kiosk.bak $SYS_AUTOSTART
then log out/in (or reboot). Your original user autostart, if you had a
custom one, was backed up to ~/.config/labwc/autostart.pre-avian-kiosk.bak.
DONE
