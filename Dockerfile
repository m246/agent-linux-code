FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive LANG=zh_CN.UTF-8 LC_ALL=zh_CN.UTF-8 DISPLAY=:1 HEALTH_PORT=8000
ARG VNC_PASSWD=changeme
RUN apt-get update && apt-get install -y --no-install-recommends \
 locales fonts-noto-cjk xvfb x11vnc xfce4 xfce4-terminal novnc websockify \
 python3 python3-pip openjdk-17-jdk-headless squid \
 wget ca-certificates procps \
 libxss1 libgtk-3-0 libasound2 libgbm1 \
 && locale-gen zh_CN.UTF-8 \
 && wget -q -O /tmp/c.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
 && apt-get install -y /tmp/c.deb && rm -f /tmp/c.deb \
 && mkdir -p /root/.vnc && printf '%s\n%s\n' "$VNC_PASSWD" "$VNC_PASSWD" | x11vnc -storepasswd /root/.vncpasswd \
 && rm -rf /var/lib/apt/lists/*
COPY startup.sh health_server.py /work/
COPY squid/squid.conf /etc/squid/squid.conf
RUN chmod +x /work/startup.sh
EXPOSE 6080 8000
WORKDIR /work
CMD ["/work/startup.sh"]
