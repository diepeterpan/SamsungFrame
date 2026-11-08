#!/bin/bash
cd /samsung

touch clear.jpg
python2 frame-ctrl.py clear.jpg
while :
do
  wkhtmltoimage --zoom 0.834 --width 800 --height 480 --quality 50 "http://intranet.galleon.co.za/local/Webcam2.html" screen.jpg
  python2 frame-ctrl.py screen.jpg
  sleep 10
done
