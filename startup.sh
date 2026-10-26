#!/bin/bash
set -e
export DISPLAY=:1
squid -z 2>/dev/null || true
squid
Xvfb :1 -screen 0 1280x800x24 &
sleep 3
xfce4-session >/dev/null 2>&1 &
sleep 2
x11vnc -display :1 -forever -shared -rfbauth /root/.vncpasswd -rfbport 5900 >/dev/null 2>&1 &
sleep 2
websockify --web /usr/share/novnc 6080 localhost:5900 >/dev/null 2>&1 &
exec python3 /work/health_server.py
