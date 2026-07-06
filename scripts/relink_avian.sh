#!/usr/bin/env bash
# Recreates the AvianVisitors overlay symlinks into BirdNET-Pi's Caddy
# webroot ($EXTRACTED). install_services.sh calls this once at install
# time; it also needs to be callable standalone afterward, because
# upstream's clear_all_data.sh rebuilds $EXTRACTED from scratch knowing
# only about its own (non-AvianVisitors) symlink set - without re-running
# this, the site silently reverts to the stock BirdNET-Pi homepage. The
# admin overlay's "clear ALL data" button runs this right after
# clear_all_data.sh for exactly that reason.
set -euo pipefail
source /etc/birdnet/birdnet.conf
USER="${BIRDNET_USER}"
HOME="/home/${BIRDNET_USER}"
MY_DIR="${HOME}/BirdNET-Pi"

if [ ! -d "$MY_DIR/avian" ]; then
  echo "no avian/ overlay at $MY_DIR/avian - nothing to link"
  exit 0
fi

sudo -u "${USER}" ln -fs "$MY_DIR/avian"                       "${EXTRACTED}/avian"
sudo -u "${USER}" ln -fs "$MY_DIR/avian/frontend/index.html"   "${EXTRACTED}/index.html"
sudo -u "${USER}" ln -fs "$MY_DIR/avian/frontend/styles.css"   "${EXTRACTED}/styles.css"
sudo -u "${USER}" ln -fs "$MY_DIR/avian/frontend/apt.js"       "${EXTRACTED}/apt.js"
sudo -u "${USER}" ln -fs "$MY_DIR/avian/frontend/masks.json"   "${EXTRACTED}/masks.json"
sudo -u "${USER}" ln -fs "$MY_DIR/avian/frontend/dims.json"    "${EXTRACTED}/dims.json"
sudo -u "${USER}" ln -fs "$MY_DIR/avian/assets/favicon.png"    "${EXTRACTED}/favicon.png"
sudo -u "${USER}" ln -fs "$MY_DIR/avian/assets/favicon.png"    "${EXTRACTED}/favicon.ico"
echo "avian overlay relinked into ${EXTRACTED}"
