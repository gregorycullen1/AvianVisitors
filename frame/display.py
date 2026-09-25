#!/usr/bin/env python3
"""Frame-Pi client: turn a collage screenshot into Inky panel pixels.

Runs on the Pi Zero W on a systemd timer. Each run it decides whether a
refresh is worth it (the species set or call-count brackets changed, and it
is not quiet hours), then crops the title and collage from the screenshot,
centres and mats them, and pushes the result to the Inky Impression 13.3".
``--preview out.png`` writes an approximate 6-ink dither instead, so the
look can be checked on any machine without the panel.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import inspect
import io
import json
import os
import re
import statistics
import sys
import time
import urllib.request
from datetime import datetime

from PIL import Image, ImageChops, ImageDraw

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib

# Per-panel working canvas size. "" / "el133uf1": Inky Impression 13.3",
# portrait canvas (the panel itself is 1600x1200 landscape, rotated at push
# time). "epd7in3e": Waveshare PhotoPainter - its outer housing is portrait
# (154x214mm) even though the display glass inside is native-landscape
# (800x480px), the same as the panel is mounted rotated inside a portrait
# housing; compose portrait here and rotate at push time, same pattern as
# the 13.3".
PANEL_SIZES = {
    "": (1200, 1600),
    "el133uf1": (1200, 1600),
    "epd7in3e": (480, 800),
}
PANEL_W, PANEL_H = PANEL_SIZES[""]  # reset per-run in run(), from cfg["panel"]

# Approximate ink palettes, used only for --preview. On hardware each
# library/driver maps to the panel's real palette.
SPECTRA6 = [(236, 234, 223), (26, 26, 28), (165, 60, 56),
            (198, 176, 74), (49, 71, 130), (58, 110, 72)]
# Black, White, Yellow, Red, Blue, Green - matches epd7in3e.py's own palette
# order exactly (its 5th slot duplicates Black as an unused ORANGE placeholder;
# this panel has no orange).
WAVESHARE6 = [(0, 0, 0), (255, 255, 255), (255, 255, 0),
              (255, 0, 0), (0, 0, 255), (0, 255, 0)]
PREVIEW_PALETTES = {"": SPECTRA6, "el133uf1": SPECTRA6, "epd7in3e": WAVESHARE6}

DEFAULTS = {
    "base_url": "http://birdnet.local",
    "species_source": "",   # "" = the recent API at base_url; "birdweather" = BirdWeather near a ZIP
    "zip": "",              # BirdWeather ZIP / postal code (with species_source = "birdweather")
    "bw_days": 7,           # BirdWeather lookback window, in days
    "bw_country": "us",     # geocoder country for the ZIP
    "hours": 24,
    "top_n": 0,             # cap the collage to the N most-active species by call count (0 = show all)
    "image": "",            # local PNG written by the shooter
    "image_url": "",        # or a published screenshot URL
    "shoot": False,         # or capture inline (needs a browser; the Zero 2 W handles it)
    "shoot_title": None, "shoot_subtitle": None,
    "shoot_headline_px": 42, "shoot_eyebrow_px": 18, "shoot_lowercase": False,
    "shoot_mat": 0.04, "shoot_small_floor": 0.04, "shoot_count_exp": 0.65,
    "mat": 0.0,             # extra global shrink of the content inside the A5 opening
    "layout": "mat",        # "mat" = float in an A5 opening (wood-frame builds);
                            # "fill" = cover the whole panel (e.g. the PhotoPainter's own enclosure)
    "rotate": 90,           # 90 or 270 if the frame hangs the other way up
    "saturation": 0.6,
    "panel": "",            # "el133uf1" forces the 13.3" driver if auto() fails
    "quiet_start": 0, "quiet_end": 0,    # 0/0 = no quiet hours
    "heal_hours": 24,
    "state": "~/.birdframe/state.json",
    "cache": "~/.birdframe",
    "timeout": 45,
    "basic_user": None, "basic_pass": None,
}


def _auth(cfg):
    if not cfg.get("basic_user"):
        return None
    raw = f"{cfg['basic_user']}:{cfg.get('basic_pass') or ''}".encode()
    return "Basic " + base64.b64encode(raw).decode()


# --- change detection -------------------------------------------------------
def slugify(sci):
    return re.sub(r"[^a-z0-9]+", "-", sci.lower()).strip("-")


def _bucket(n):
    for i, edge in enumerate((1, 2, 5, 15, 40, 100, 300, 1000)):
        if n <= edge:
            return i
    return 8


def fetch_recent(base, hours, timeout, auth=None):
    url = f"{base.rstrip('/')}/avian/api/birdnet-api.php?action=recent&hours={hours}"
    req = urllib.request.Request(url, headers={"User-Agent": "AvianVisitors-frame/1.0"})
    if auth:
        req.add_header("Authorization", auth)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read(2_000_000)).get("species", [])


def signature(species):
    items = sorted((slugify(s["sci"]), _bucket(int(s.get("n") or 1))) for s in species)
    return hashlib.sha256(json.dumps(items).encode()).hexdigest()[:16]


def cap_top_n(species, n):
    """The N most-active species by call count - the same trim shoot.py's
    API rewrite applies at render time, so a signature computed from this
    matches what actually got drawn. n <= 0 means no cap."""
    if not n or len(species) <= n:
        return species
    return sorted(species, key=lambda s: s.get("n") or 0, reverse=True)[:n]


def fetch_species(cfg, auth=None):
    """The species list the signature is built from: the BirdNET-Pi recent API
    by default, or BirdWeather's recent detections near a ZIP when
    species_source = "birdweather"."""
    if cfg.get("species_source") == "birdweather":
        import birdweather
        return birdweather.species_for_zip(cfg["zip"], country=cfg["bw_country"], days=cfg["bw_days"])
    return fetch_recent(cfg["base_url"], cfg["hours"], cfg["timeout"], auth)


def is_image_mode(cfg):
    """True when the actual panel content comes from a pre-rendered image
    (image_url / image, e.g. a shoot.py running elsewhere) rather than
    this process rendering it (shoot = true) or drawing from BirdWeather
    data directly. In this mode the species/hours signature below reflects
    whatever window *this* config happens to have (often just its 24h
    default) - not necessarily the window the image was actually rendered
    with (e.g. a separately-configured --window-hours upstream) - so it's
    not a reliable change-detector for what we're about to display."""
    return (cfg.get("species_source") != "birdweather" and not cfg.get("shoot")
            and bool(cfg.get("image_url") or cfg.get("image")))


def image_change_signal(src, timeout, auth=None):
    """The 'has the image we're about to display actually meaningfully
    changed' signal for image mode.

    Tries a sidecar signature file first - the convention render_frame.sh
    publishes: <image>.sig next to <image>.png, containing the species
    signature computed from the SAME underlying data and window the
    renderer actually used. This is the only reliable signal: an HTTP
    ETag/Last-Modified or a pixel hash of the rendered image both falsely
    report "changed" on every single render even with byte-for-byte
    identical species data, because the site re-rolls small cosmetic
    randomness (e.g. a bird's perched-vs-flight pose) on every fresh page
    load, which shoot.py always is.

    Falls back to an HTTP conditional-request token (ETag/Last-Modified)
    for an image source with no sidecar published (e.g. some other
    image_url entirely, not a render_frame.sh instance) - a strictly
    weaker signal (refreshes somewhat more often than truly necessary),
    but still reacts to the feed changing at all."""
    if re.match(r"^https?://", src):
        sig_url = re.sub(r"\.png(\?.*)?$", ".sig", src)
        try:
            req = urllib.request.Request(sig_url, headers={"User-Agent": "AvianVisitors-frame/1.0"})
            if auth:
                req.add_header("Authorization", auth)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return "sig:" + r.read(200).decode("utf-8", "replace").strip()
        except (urllib.error.HTTPError, urllib.error.URLError):
            pass  # no sidecar published for this source; fall back to ETag
        req = urllib.request.Request(src, method="HEAD", headers={"User-Agent": "AvianVisitors-frame/1.0"})
        if auth:
            req.add_header("Authorization", auth)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return "etag:" + (r.headers.get("ETag") or r.headers.get("Last-Modified") or "")
    return "mtime:" + str(os.path.getmtime(os.path.expanduser(src)))


# --- image ------------------------------------------------------------------
def get_image(src, timeout, auth=None):
    if re.match(r"^https?://", src):
        req = urllib.request.Request(src, headers={"User-Agent": "AvianVisitors-frame/1.0"})
        if auth:
            req.add_header("Authorization", auth)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return Image.open(io.BytesIO(r.read(20_000_000))).convert("RGB")
    return Image.open(os.path.expanduser(src)).convert("RGB")


def fit_panel(img):
    if img.size != (PANEL_W, PANEL_H):
        img = img.resize((PANEL_W, PANEL_H), Image.LANCZOS)
    return img


def fill_panel(img):
    """Cover-fit: scale to fill the panel exactly, centre-cropping any
    overflow, preserving aspect ratio (unlike fit_panel's naive stretch).
    For layout = "fill" - a panel used in its own enclosure, with no
    separate wood-frame mat opening to float content inside."""
    img = img.convert("RGB")
    s = max(PANEL_W / img.width, PANEL_H / img.height)
    nw, nh = max(1, round(img.width * s)), max(1, round(img.height * s))
    img = img.resize((nw, nh), Image.LANCZOS)
    x0, y0 = (nw - PANEL_W) // 2, (nh - PANEL_H) // 2
    return img.crop((x0, y0, x0 + PANEL_W, y0 + PANEL_H))


def _paper(img):
    """Median of the four corners, robust to a stray inked corner."""
    w, h = img.size
    px = (img.getpixel(p) for p in ((4, 4), (w - 5, 4), (4, h - 5), (w - 5, h - 5)))
    return tuple(int(statistics.median(c)) for c in zip(*px))


# The mat opening is an A5 rectangle (1 : sqrt(2)) centred in the panel; the
# content floats inside it with `mat` of inner whitespace. Recomputed
# alongside PANEL_W/PANEL_H in run() (layout = "mat" only), not just set once
# at import time, so a non-default panel size doesn't leave these stale.
A5_H = PANEL_H * 0.7071           # A5 is 1/sqrt(2) of the panel height
A5_W = A5_H / 1.41421             # A5 aspect 1 : sqrt(2)


def _place(content, paper, mat):
    s = min(A5_W * (1 - mat) / content.width, A5_H * (1 - mat) / content.height)
    nw, nh = max(1, round(content.width * s)), max(1, round(content.height * s))
    content = content.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (PANEL_W, PANEL_H), paper)
    canvas.paste(content, ((PANEL_W - nw) // 2, (PANEL_H - nh) // 2))
    return canvas


def _region_bbox(img, paper, y0, y1):
    region = img.crop((0, y0, img.width, y1))
    diff = ImageChops.difference(region, Image.new("RGB", region.size, paper))
    bb = diff.convert("L").point(lambda p: 255 if p > 34 else 0).getbbox()
    return None if not bb else (bb[0], y0 + bb[1], bb[2], y0 + bb[3])


def _scale_w(img, target_w):
    s = target_w / img.width
    return img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)


def _scale_h(img, target_h):
    s = target_h / img.height
    return img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)


def _centroid_x(img, paper):
    """Horizontal centre of ink weight (what the eye reads as centred)."""
    m = ImageChops.difference(img, Image.new("RGB", img.size, paper)).convert("L")
    cols = list(m.resize((img.width, 1), Image.BOX).tobytes())
    total = sum(cols) or 1
    return sum(x * v for x, v in enumerate(cols)) / total


# Content layout inside the A5 opening: the title and collage are sized
# independently (as fractions of the opening width), so tuning one leaves the
# other untouched. gap is a fraction of the opening height.
TITLE_H_FRAC, COLLAGE_FRAC, GAP_FRAC = 0.065, 0.66, 0.1


def mat_and_center(img, mat, empty=False):
    """Crop the title and collage, size each to a fraction of the A5 opening,
    stack with a gap, and centre on the panel."""
    img = img.convert("RGB")
    paper = _paper(img)
    mask = ImageChops.difference(img, Image.new("RGB", img.size, paper))
    mask = mask.convert("L").point(lambda p: 255 if p > 34 else 0)
    full = mask.getbbox()
    if not full:
        return img
    levels = list(mask.resize((1, img.height), Image.BOX).tobytes())  # per-row content
    top, bot = full[1], full[3]
    split, run = None, 0
    for y in range(top, bot):
        if levels[y] <= 2:
            run += 1
            if run >= 60:  # split below the headline; a 60px band clears the ~30px eyebrow/headline gap so the title stays whole
                cy = y
                while cy < bot and levels[cy] <= 2:
                    cy += 1
                split = (y - run + 1, cy)
                break
        else:
            run = 0
    tb = _region_bbox(img, paper, top, split[0]) if split else None
    cb = _region_bbox(img, paper, split[1], bot + 1) if split else None
    box_w, box_h = A5_W * (1 - mat), A5_H * (1 - mat)
    # No birds yet: hold the title where a full collage would put it and float
    # the one-line note where the birds would be, so a birdless frame reads like
    # a full one with the collage removed, not a title card drifted to the middle.
    if empty and tb and cb:
        title = _scale_h(img.crop(tb), box_h * TITLE_H_FRAC)
        note = _scale_w(img.crop(cb), box_w * 0.30)
        gap = round(box_h * GAP_FRAC)
        region = box_w * COLLAGE_FRAC  # stand in for a usual-size collage
        cw = max(title.width, note.width)
        comp = Image.new("RGB", (cw, round(title.height + gap + region)), paper)
        comp.paste(title, ((cw - title.width) // 2, 0))
        ny = title.height + gap + max(0, (round(region) - note.height) // 2)
        comp.paste(note, ((cw - note.width) // 2, ny))
        canvas = Image.new("RGB", (PANEL_W, PANEL_H), paper)
        canvas.paste(comp, ((PANEL_W - comp.width) // 2, (PANEL_H - comp.height) // 2))
        return canvas
    if not (tb and cb):
        return _place(img.crop(full), paper, mat)
    title = _scale_h(img.crop(tb), box_h * TITLE_H_FRAC)
    gap = round(box_h * GAP_FRAC)
    # Size the collage to fill the room left under the fixed-size title,
    # binding on whichever of width or remaining height runs out first, so the
    # title stays a consistent size whether the collage is tall or compact
    # instead of ballooning when the collage happens to be short.
    coll = img.crop(cb)
    cs = min(box_w * COLLAGE_FRAC / coll.width, (box_h - title.height - gap) / coll.height)
    collage = coll.resize((max(1, round(coll.width * cs)), max(1, round(coll.height * cs))), Image.LANCZOS)
    ccx = _centroid_x(collage, paper)  # centre the collage by ink weight, not bbox
    half = max(ccx, collage.width - ccx)
    # A wildly off-centre collage can push the centroid-mirrored width (2*half)
    # past the A5 opening; shrink only the collage, never the fixed-size title,
    # so nothing spills under the physical mat.
    if 2 * half > box_w:
        s = box_w / (2 * half)
        collage = collage.resize((max(1, round(collage.width * s)), max(1, round(collage.height * s))), Image.LANCZOS)
        ccx = round(ccx * s)
        half = max(ccx, collage.width - ccx)
    cw = round(max(title.width, 2 * half))
    comp = Image.new("RGB", (cw, title.height + gap + collage.height), paper)
    comp.paste(title, ((cw - title.width) // 2, 0))
    comp.paste(collage, (round(cw / 2 - ccx), title.height + gap))
    canvas = Image.new("RGB", (PANEL_W, PANEL_H), paper)
    canvas.paste(comp, ((PANEL_W - comp.width) // 2, (PANEL_H - comp.height) // 2))
    return canvas


def quantize_preview(img, palette):
    pal = Image.new("P", (1, 1))
    flat = [c for ink in palette for c in ink]
    flat += list(palette[0]) * ((768 - len(flat)) // 3)  # pad the 256-entry palette with paper
    pal.putpalette(flat[:768])
    return img.convert("RGB").quantize(palette=pal, dither=Image.Dither.FLOYDSTEINBERG).convert("RGB")


def _draw_mat_box(img):
    """Dev aid: outline the A5 mat opening so the matte and centring show."""
    x0, y0 = round((PANEL_W - A5_W) / 2), round((PANEL_H - A5_H) / 2)
    ImageDraw.Draw(img).rectangle((x0, y0, PANEL_W - x0 - 1, PANEL_H - y0 - 1),
                                  outline=(170, 60, 56), width=2)


# --- hardware ---------------------------------------------------------------
def _snap_near_white(img, threshold=210):
    """Snap near-white pixels to pure (255,255,255).

    epd7in3e's palette has no dedicated off-white/cream ink - only pure
    white - so the site's actual (slightly cream) paper colour otherwise
    gets Floyd-Steinberg dithered against white across the *entire* flat
    background, scattering visible speckle everywhere. A real bird
    illustration's colours have at least one channel well below this
    threshold, so they're untouched; only the flat paper area is affected.
    """
    lut = [255 if v >= threshold else v for v in range(256)]
    return img.point(lut * 3)


# epd7in3e.getbuffer()'s palette, index-for-index (4 is the panel's unused
# slot). Pure RGB, which is also esp32-photoframe's "theoretical" palette.
E6_PALETTE = (0, 0, 0, 255, 255, 255, 255, 255, 0, 255, 0, 0,
              0, 0, 0, 0, 0, 255, 0, 255, 0)


BATTERY_LOW = 20          # at or below: red fill, and frame.php forces a refresh
# Older reports hide the badge rather than lie. Long enough to span the
# overnight gap of FRAME_DAYLIGHT_ONLY's schedule (9:30pm-5am).
BATTERY_MAX_AGE = 12 * 3600
BADGE_FONTS = ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
               "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf")


def read_frame_battery(path, max_age=BATTERY_MAX_AGE, now=None):
    """Latest battery level a frame reported to frame.php, or None.

    frame.php stores the X-Battery-Percentage header esp32-photoframe sends
    on every fetch as "<percent> <unix time>". None when there's no report,
    it's malformed, or it's stale - a frame on USB with no battery never
    sends the header, and one that stopped polling shouldn't keep showing
    its last number."""
    try:
        with open(path) as f:
            pct, ts = f.read().split()
        pct, ts = int(pct), int(ts)
    except (OSError, ValueError):
        return None
    if not 0 <= pct <= 100 or (now or time.time()) - ts > max_age:
        return None
    return pct


def _draw_battery_badge(img, pct):
    """Battery glyph + "NN%" in the lower-right corner, in exact palette
    colours with no anti-aliasing so it survives quantize() crisp."""
    from PIL import ImageFont
    font = None
    for path in BADGE_FONTS:
        try:
            font = ImageFont.truetype(path, 13)
            break
        except OSError:
            pass
    font = font or ImageFont.load_default()
    black, red = (0, 0, 0), (255, 0, 0)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"
    label = f"{pct}%"
    tw = round(d.textlength(label, font=font))
    w, h = img.size
    bw, bh, margin, gap = 22, 11, 12, 5
    by1 = h - margin
    by0 = by1 - bh
    bx1 = w - margin - tw - gap - 2  # 2px for the nub
    bx0 = bx1 - bw
    d.rectangle((bx0, by0, bx1, by1), outline=black)
    d.rectangle((bx1 + 1, by0 + 3, bx1 + 2, by1 - 3), fill=black)
    fill_w = round((bw - 4) * pct / 100)
    if fill_w > 0:
        d.rectangle((bx0 + 2, by0 + 2, bx0 + 2 + fill_w - 1, by1 - 2),
                    fill=red if pct <= BATTERY_LOW else black)
    # Vertically centre the label on the glyph.
    top, bottom = font.getbbox(label)[1::2]
    d.text((w - margin - tw, (by0 + by1) / 2 - (top + bottom) / 2), label,
           fill=black, font=font)
    return img


def e6_panel_image(img, battery=None):
    """Composed portrait -> 800x480 landscape in exact E6 palette colours,
    for microcontroller frames fed by avian/api/frame.php. ``battery`` (a
    percent, or None to omit) adds a badge in the lower-right corner.

    esp32-photoframe skips its own processing (CDR + dither against a
    measured palette, which speckles flat white: its measured white isn't
    neutral) only for a native-size PNG whose every pixel is a palette
    colour. So do what push_panel() does for epd7in3e here instead - snap,
    then getbuffer()'s quantize - and pre-rotate the way the firmware would
    for display_orientation=portrait: native(X, Y) = portrait(Y, 799 - X),
    i.e. 90 deg clockwise. Its 180 deg mount flip is applied at paint time
    either way, so it isn't baked in here.
    """
    pal = Image.new("P", (1, 1))
    pal.putpalette(E6_PALETTE + (0, 0, 0) * 249)
    buf = _snap_near_white(img.convert("RGB"))
    if battery is not None:
        buf = _draw_battery_badge(buf, battery)
    buf = buf.transpose(Image.Transpose.ROTATE_270)
    return buf.quantize(palette=pal).convert("RGB")


def push_panel(img, rotate, saturation, panel=""):
    """Push to the panel. Lazy imports so this module still loads on a
    machine without the panel's driver library installed."""
    if rotate not in (90, 270):
        print(f"rotate must be 90 or 270, not {rotate}; using 90", file=sys.stderr)
        rotate = 90
    if panel == "epd7in3e":
        # Composed portrait (see PANEL_SIZES); rotate to the panel's native
        # landscape buffer ourselves so we control the direction explicitly,
        # rather than relying on getbuffer()'s own dimension-swap-triggered
        # auto-rotate (which is hardcoded to one direction only).
        from waveshare_epd import epd7in3e
        buf = img.rotate(rotate, expand=True)
        if buf.size != (epd7in3e.EPD_WIDTH, epd7in3e.EPD_HEIGHT):
            buf = buf.resize((epd7in3e.EPD_WIDTH, epd7in3e.EPD_HEIGHT), Image.LANCZOS)
        buf = _snap_near_white(buf)
        dev = epd7in3e.EPD()
        dev.init()
        dev.display(dev.getbuffer(buf))
        dev.sleep()
        return
    if panel == "el133uf1":
        from inky.inky_el133uf1 import Inky
        dev = Inky(resolution=(1600, 1200))
    else:
        from inky.auto import auto
        dev = auto()
    buf = img.rotate(rotate, expand=True)
    if buf.size != (dev.width, dev.height):
        buf = buf.resize((dev.width, dev.height), Image.LANCZOS)
    kw = {"saturation": saturation} if "saturation" in inspect.signature(dev.set_image).parameters else {}
    dev.set_image(buf, **kw)
    dev.show()


# --- state ------------------------------------------------------------------
def load_state(path):
    try:
        with open(os.path.expanduser(path)) as f:
            return json.load(f)
    except Exception:
        return {"signature": None, "last_refresh": 0}


def save_state(path, sig, when):
    path = os.path.expanduser(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"signature": sig, "last_refresh": when}, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)  # atomic: a power cut can't leave a half-written file


def in_quiet_hours(cfg, hour):
    s, e = cfg["quiet_start"], cfg["quiet_end"]
    if s == e:
        return False
    return s <= hour < e if s < e else hour >= s or hour < e


# --- run --------------------------------------------------------------------
def obtain_image(cfg, species=None):
    if cfg.get("species_source") == "birdweather":
        from shoot import shoot_birdweather
        if species is None:  # gate skipped (--no-signature): fetch the list to render
            species = fetch_species(cfg, _auth(cfg))
        out = os.path.join(os.path.expanduser(cfg["cache"]), "frame.png")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        shoot_birdweather(out, species, title=cfg["shoot_title"], subtitle=cfg["shoot_subtitle"],
                          top_n=cfg["top_n"], timeout_ms=cfg["timeout"] * 1000)
        return Image.open(out).convert("RGB")
    if cfg["shoot"]:
        from shoot import shoot
        out = os.path.join(os.path.expanduser(cfg["cache"]), "shot.png")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        shoot(cfg["base_url"], out, title=cfg["shoot_title"], subtitle=cfg["shoot_subtitle"],
              headline_px=cfg["shoot_headline_px"], eyebrow_px=cfg["shoot_eyebrow_px"],
              lowercase=cfg["shoot_lowercase"], mat=cfg["shoot_mat"],
              small_floor=cfg["shoot_small_floor"], count_exp=cfg["shoot_count_exp"], top_n=cfg["top_n"],
              timeout_ms=cfg["timeout"] * 1000,
              user=cfg["basic_user"], password=cfg["basic_pass"])
        return Image.open(out).convert("RGB")
    src = cfg["image_url"] or cfg["image"]
    if not src:
        raise ValueError("set image, image_url, or shoot in config")
    return get_image(src, cfg["timeout"], _auth(cfg))


def run(cfg, preview=None, force=False, use_signature=True, mat_box=False):
    global PANEL_W, PANEL_H, A5_H, A5_W
    PANEL_W, PANEL_H = PANEL_SIZES.get(cfg.get("panel", ""), PANEL_SIZES[""])
    A5_H = PANEL_H * 0.7071
    A5_W = A5_H / 1.41421

    now = time.time()
    state = load_state(cfg["state"])
    sig = None
    species = None
    if use_signature:
        try:
            species = fetch_species(cfg, _auth(cfg))
            sig = signature(cap_top_n(species, cfg["top_n"]))
        except Exception as e:
            print(f"signature fetch failed: {e}", file=sys.stderr)  # treat as no change
        if is_image_mode(cfg):
            # Overrides the species-derived sig above with one tied to the
            # actual image we'd fetch - see is_image_mode()'s docstring for
            # why the species signature alone isn't reliable here. Species
            # is still fetched above (best-effort) purely for the "no birds
            # yet" empty-state layout below.
            try:
                sig = image_change_signal(cfg["image_url"] or cfg["image"], cfg["timeout"], _auth(cfg))
            except Exception as e:
                print(f"image change-signal fetch failed: {e}", file=sys.stderr)
    heal_due = now - state.get("last_refresh", 0) >= cfg["heal_hours"] * 3600
    changed = (not use_signature) or (sig is not None and sig != state.get("signature"))
    if not force and not preview:
        if in_quiet_hours(cfg, datetime.now().hour):
            print("quiet hours; skip")
            return
        if not changed and not heal_due:
            print("no change; skip")
            return
        print("refresh:", "changed" if changed else "heal")

    try:
        img = obtain_image(cfg, species)
    except Exception as e:
        print(f"could not get image: {e}", file=sys.stderr)  # keep last panel image
        return
    if cfg.get("layout") == "fill":
        img = fill_panel(img)
    else:
        img = mat_and_center(fit_panel(img), cfg["mat"], empty=(species == []))
    if preview:
        pre = _snap_near_white(img) if cfg.get("panel") == "epd7in3e" else img
        out = quantize_preview(pre, PREVIEW_PALETTES.get(cfg.get("panel", ""), SPECTRA6))
        if mat_box:
            _draw_mat_box(out)
        out.save(preview)
        print(f"wrote preview {preview}")
        return
    try:
        push_panel(img, cfg["rotate"], cfg["saturation"], cfg.get("panel", ""))
    except Exception as e:
        print(f"panel push failed: {e}", file=sys.stderr)
        return
    save_state(cfg["state"], sig if sig is not None else state.get("signature"), now)
    print("panel updated")


def load_config(path):
    cfg = dict(DEFAULTS)
    if path:
        with open(os.path.expanduser(path), "rb") as f:
            cfg.update(tomllib.load(f))
    return cfg


def main():
    ap = argparse.ArgumentParser(description="Push the collage screenshot to the Inky panel.")
    ap.add_argument("--config")
    ap.add_argument("--base-url")
    ap.add_argument("--image")
    ap.add_argument("--image-url")
    ap.add_argument("--preview", help="write a 6-ink preview PNG instead of pushing")
    ap.add_argument("--rotate", type=int)
    ap.add_argument("--force", action="store_true", help="refresh even if unchanged")
    ap.add_argument("--no-signature", action="store_true", help="skip change detection")
    ap.add_argument("--mat-box", action="store_true", help="dev: outline the mat window on the preview")
    args = ap.parse_args()

    cfg = load_config(args.config)
    for key in ("base_url", "image", "image_url"):
        val = getattr(args, key)
        if val:
            cfg[key] = val
    if args.rotate is not None:
        cfg["rotate"] = args.rotate
    run(cfg, preview=args.preview, force=args.force, use_signature=not args.no_signature, mat_box=args.mat_box)


if __name__ == "__main__":
    main()
