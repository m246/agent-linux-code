# ============================================================
# Render / 任何支持 Docker 的平台（免费容器）云桌面镜像
# 内容：
#   Ubuntu 22.04 + Xfce 桌面 + noVNC（网页远程桌面，密码登录）
#   + Chromium(Google Chrome) 谷歌浏览器
#   + Python3 + OpenJDK 17
#   + Squid 白名单代理（只放行指定站点）
#   + 健康检测服务（全部加载完成才返回 ready）
# 说明：
#   - Android SDK 默认不加：体积大、免费档 512M 内存跑不动，
#     需要时把下面 WITH_ANDROID_SDK 打开重新构建。
#   - 构建时可指定 VNC 密码：--build-arg VNC_PASSWD=你的密码
# ============================================================
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=zh_CN.UTF-8 \
    LC_ALL=zh_CN.UTF-8 \
    DISPLAY=:1

# ---------- 1. 基础系统 + 中文 + 桌面 + VNC ----------
RUN apt-get update && apt-get install -y --no-install-recommends \
        locales language-pack-zh-hans fonts-noto-cjk \
        xvfb x11vnc xfce4 xfce4-terminal tigervnc-standalone-server \
        novnc websockify \
        curl wget git ca-certificates procps \
    && locale-gen zh_CN.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

# ---------- 2. 编程环境：Python + Java ----------
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        openjdk-17-jdk-headless \
    && rm -rf /var/lib/apt/lists/*

# ---------- 3. 代理：Squid ----------
RUN apt-get update && apt-get install -y --no-install-recommends squid \
    && rm -rf /var/lib/apt/lists/*

# ---------- 4. 谷歌浏览器（Chromium 内核） ----------
# 优先装 Google Chrome 稳定版；下载失败则回退系统 chromium 包
RUN (wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
     && apt-get update \
     && apt-get install -y /tmp/chrome.deb \
     && rm -f /tmp/chrome.deb) \
    || (apt-get update && apt-get install -y --no-install-recommends chromium-browser || true) \
    || true
# 补充 Chrome 在容器里运行所需的依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
        libxss1 libappindicator1 libindicator7 libgtk-3-0 libasound2 libgbm1 \
    || true

# ---------- 5.（可选）Android SDK ----------
# 默认关闭。需要时：docker build --build-arg WITH_ANDROID_SDK=1
ARG WITH_ANDROID_SDK=0
RUN if [ "$WITH_ANDROID_SDK" = "1" ]; then \
        apt-get update && apt-get install -y --no-install-recommends \
            unzip openjdk-17-jdk \
        && mkdir -p /opt/android-sdk \
        && wget -q -O /tmp/cmdline.zip https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip \
        && unzip -q /tmp/cmdline.zip -d /opt/android-sdk/cmdline-tools \
        && mv /opt/android-sdk/cmdline-tools/cmdline-tools /opt/android-sdk/cmdline-tools/latest \
        && rm -f /tmp/cmdline.zip; \
    fi
ENV ANDROID_HOME=/opt/android-sdk \
    ANDROID_SDK_ROOT=/opt/android-sdk

# ---------- 6. VNC 密码（构建时指定，防止别人随便进桌面） ----------
ARG VNC_PASSWD=changeme
RUN mkdir -p /root/.vnc \
    && printf '%s\n%s\n' "$VNC_PASSWD" "$VNC_PASSWD" | x11vnc -storepasswd /root/.vncpasswd \
    && chmod 600 /root/.vncpasswd

# ---------- 7. 拷贝应用文件 ----------
COPY startup.sh        /work/startup.sh
COPY health_server.py  /work/health_server.py
COPY squid/squid.conf  /etc/squid/squid.conf
RUN chmod +x /work/startup.sh

# ---------- 8. 端口 ----------
# 6080 = noVNC 网页远程桌面 | 3128 = Squid 白名单代理 | 8000 = 健康检测/任务接口
EXPOSE 6080 3128 8000

WORKDIR /work
CMD ["/work/startup.sh"]
