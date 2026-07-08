Vendored, unmodified, from Waveshare's RPi Zero PhotoPainter demo bundle
(`RPi_Zero_PhotoPainter/7in3_e-Paper_E/python/lib/waveshare_epd/`), downloaded from
https://files.waveshare.com/wiki/RPi_Zero_PhotoPainter/Demo/RPi_Zero_PhotoPainter.zip
per https://www.waveshare.com/wiki/RPi_Zero_PhotoPainter

Only `__init__.py`, `epd7in3e.py`, and `epdconfig.py` are kept - the `.pyc`/`__pycache__`
files and the `DEV_Config_*.so` blobs (an alternate GPIO backend for non-Raspberry-Pi
boards) aren't needed; `epdconfig.py`'s `RaspberryPi` class (spidev + gpiozero) is what
runs here, auto-selected at import time from `/proc/cpuinfo`.

No modifications needed for this board: `epdconfig.py`'s `PWR_PIN = 27` already matches
this specific product's wiring (Waveshare's generic epd7in3e demo elsewhere on their
wiki needs manual correction for this - the PhotoPainter-specific bundle used here
does not).
