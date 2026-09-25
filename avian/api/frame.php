<?php
// AvianVisitors - e-ink frame image for microcontroller panels.
//
// Serves the collage render_frame.sh writes to
// $HOME/BirdSongs/Extracted/frame.png, with an ETag taken from its
// frame.sig sidecar rather than from the PNG itself. Aimed at firmware
// that polls a URL and honours If-None-Match / 304 - e.g.
// aitjcize/esp32-photoframe on a Waveshare ESP32-S3-PhotoPainter, with
// its Auto Rotate URL set to http://birdnet.local/avian/api/frame.php.
//
// Why not just point the panel at /frame.png: Caddy's ETag for a static
// file changes on every render, and the render's pixels differ even
// when the birds don't (see image_change_signal() in frame/display.py).
// The panel would then do a ~25s flickering full refresh every time.
// frame.sig only changes when the species roster does, so a 304 lets
// the panel skip decode + refresh entirely and go back to sleep.
//
//   ?heal=N  - also change the ETag every N hours (default 24, 0 = off),
//              matching display.py's heal_hours forced refresh.
//   ?raw=1   - serve frame.png as rendered, skipping frame-e6.png.
//
// Prefers frame-e6.png when render_frame.sh has written one for the
// current render: the same image already rotated to the panel's native
// 800x480 and dithered to exact E6 palette colours (display.py's
// e6_panel_image), which esp32-photoframe displays untouched. Left to
// the firmware, its own dither speckles the whole white background.
// Done at render time because PHP here has no GD.
//
// Battery badge: esp32-photoframe sends X-Battery-Percentage on every
// fetch (only when it has a valid reading). It's stored in
// frame-battery.txt as "<percent> <unix time>" for render_frame.sh to
// draw into the next frame-e6.png. The badge doesn't change the ETag -
// a full ~30s refresh just to update a number would spend the battery
// it's reporting - so it updates whenever the panel refreshes anyway
// (roster change, daily heal). Exception: once the level drawn in
// frame-e6.png (frame-e6.batt) is at or below 20%, the ETag gains
// "-low", forcing one refresh so the warning shows promptly. Switched off
// in settings (FRAME_BATTERY_BADGE=0), frame-e6.batt reads "off" and the
// ETag gains "-nb" so the badge's removal reaches the panel too.
//
// Daylight-only schedule (FRAME_DAYLIGHT_ONLY=1 in birdnet.conf, from the
// settings page): every 200 response carries the frame's rotate_cron in
// X-Config-Payload, which esp32-photoframe merges into its own config.
// It ignores the payload on a 304, so the setting is also in the ETag
// ("-dl") - toggling it costs one refresh to deliver. This makes the
// settings page the source of truth for the frame's schedule: a schedule
// set in the frame's own web UI is overwritten on its next refresh.
//
// Race: render_frame.sh writes frame.png, then frame.sig a few seconds
// later. A fetch landing in between pairs the new image with the old
// signature; the next fetch sees the new signature and refreshes once
// more. Harmless - one extra refresh, same image.
//
// Default LAN deploy: no auth. Forwarded deploy: set AV_REQUIRE_AUTH=1
// and gate /avian/api/ in Caddy - see avian/forwarding/.

declare(strict_types=1);

if (getenv('AV_REQUIRE_AUTH') === '1' && empty($_SERVER['HTTP_AUTHORIZATION'])) {
    http_response_code(401);
    echo 'unauthorized';
    exit;
}

// Path layout: /home/{USER}/BirdNET-Pi/avian/api/frame.php
//   dirname(__DIR__, 3) -> /home/{USER}
$EXTRACTED = dirname(__DIR__, 3) . '/BirdSongs/Extracted';
$PNG = "$EXTRACTED/frame.png";
$SIG = "$EXTRACTED/frame.sig";

$batt = (string)($_SERVER['HTTP_X_BATTERY_PERCENTAGE'] ?? '');
if (preg_match('/^\d{1,3}$/', $batt) && (int)$batt <= 100) {
    // Temp file + rename so render_frame.sh never reads a partial write.
    $tmp = "$EXTRACTED/frame-battery.txt." . getmypid();
    if (@file_put_contents($tmp, (int)$batt . ' ' . time() . "\n") !== false) {
        @rename($tmp, "$EXTRACTED/frame-battery.txt");
    }
}

if (!is_file($PNG) || filesize($PNG) < 1024) {
    http_response_code(404);
    header('Content-Type: text/plain');
    echo 'no frame rendered yet (is birdframe-shoot.timer running?)';
    exit;
}

// Signature from the sidecar. Missing or empty (not rendered by
// render_frame.sh, or caught mid-write) falls back to the PNG's
// mtime + size - same as a static file, but never worse.
$sig = is_file($SIG) ? trim((string)@file_get_contents($SIG)) : '';
if (!preg_match('/^[0-9a-f]{8,64}$/', $sig)) {
    $sig = 'm' . dechex((int)filemtime($PNG)) . '-' . dechex((int)filesize($PNG));
}

// Only trust frame-e6.png if it's from this render, not a previous one
// whose snap step succeeded where this one's failed.
$E6 = "$EXTRACTED/frame-e6.png";
$serve = $PNG;
if (empty($_GET['raw']) && is_file($E6) && filesize($E6) >= 1024
        && filemtime($E6) >= filemtime($PNG)) {
    $serve = $E6;
    $sig .= '-e6b';  // bump when frame-e6.png's format changes, to bust cached ETags
    // 20 matches BATTERY_LOW in frame/display.py.
    $drawn = trim((string)@file_get_contents("$EXTRACTED/frame-e6.batt"));
    if ($drawn !== '' && ctype_digit($drawn) && (int)$drawn <= 20) {
        $sig .= '-low';
    } elseif ($drawn === 'off') {
        $sig .= '-nb';
    }
}

// Same file config.php (the settings page) writes. A plain grep rather
// than config.php's read_conf() - one key, and frame.php stays standalone.
$daylight = false;
$conf = @file(dirname(__DIR__, 2) . '/birdnet.conf', FILE_IGNORE_NEW_LINES);
foreach ($conf ?: [] as $line) {
    if (preg_match('/^\s*FRAME_DAYLIGHT_ONLY\s*=\s*"?1"?\s*$/', $line)) {
        $daylight = true;
        break;
    }
}
if ($daylight) $sig .= '-dl';
// Cron is "minute hour day-of-week" in the frame's own timezone.
$cron = $daylight ? ['*/30 5-21 *'] : ['*/15 * *'];

$healHours = (int)($_GET['heal'] ?? 24);
if ($healHours < 0 || $healHours > 24 * 30) $healHours = 24;
if ($healHours > 0) {
    $sig .= '-h' . intdiv(time(), $healHours * 3600);
}
$etag = "\"$sig\"";

header('ETag: ' . $etag);
// Always revalidate: the ETag is the whole point, don't let anything
// between here and the panel answer from a stale copy.
header('Cache-Control: no-cache');

// If-None-Match may be "*", a single tag, or a comma list, with or
// without W/ prefixes (RFC 7232 weak comparison).
$inm = (string)($_SERVER['HTTP_IF_NONE_MATCH'] ?? '');
if ($inm !== '') {
    foreach (explode(',', $inm) as $tag) {
        $tag = trim($tag);
        if (strncmp($tag, 'W/', 2) === 0) $tag = substr($tag, 2);
        if ($tag === '*' || $tag === $etag) {
            http_response_code(304);
            exit;
        }
    }
}

header('X-Config-Payload: ' . json_encode(
    ['config' => ['auto_rotate' => true, 'rotate_cron' => $cron]],
    JSON_UNESCAPED_SLASHES));
header('Content-Type: image/png');
header('Content-Length: ' . (string)filesize($serve));
readfile($serve);
