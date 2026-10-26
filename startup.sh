#!/bin/bash
# ============================================================
# 容器开机串行启动脚本
# 顺序：locale -> Squid 白名单代理 -> Xvfb + Xfce + x11vnc + noVNC
#       -> （可选）自动启动 Agent -> 最后启动健康检测服务
# 健康检测服务是【最后】启动的，它返回 ready = 全部就绪，
# 加载过程中调度器探测到的是 loading，不会下发任务。
# ============================================================
set -e

echo "[startup] 1/6 设置环境"
export LANG=zh_CN.UTF-8 LC_ALL=zh_CN.UTF-8
export DISPLAY=:1

echo "[startup] 2/6 启动 Squid 白名单代理 (127.0.0.1:3128)"
squid -z 2>/dev/null || true
squid || echo "[startup] 警告: squid 启动失败，将重试"

echo "[startup] 3/6 启动虚拟显示与远程桌面 (noVNC :6080)"
Xvfb :1 -screen 0 1280x800x24 &
sleep 3
xfce4-session >/dev/null 2>&1 &
sleep 3
# x11vnc 带密码文件，不知道密码无法进入桌面
x11vnc -display :1 -forever -shared -rfbauth /root/.vncpasswd -rfbport 5900 >/dev/null 2>&1 &
sleep 2
# noVNC 网页入口
websockify --web /usr/share/novnc 6080 localhost:5900 >/dev/null 2>&1 &

echo "[startup] 4/6 编程环境就绪检查"
python3 --version || true
java -version 2>&1 | head -1 || true
which google-chrome chromium-browser chromium 2>/dev/null || true

echo "[startup] 5/6 Agent 启动模式"
# AGENT_AUTOSTART=1 时，开机自动启动浏览器 Agent（默认不自动，人工/消息触发才跑）
if [ "$AGENT_AUTOSTART" = "1" ]; then
  echo "[startup]   自动模式：启动浏览器 Agent"
  mkdir -p /work/agent
  nohup python3 /work/agent/main.py > /work/agent/agent.log 2>&1 &
else
  echo "[startup]   手动模式：Agent 不自动启动，由人工或调度器触发"
fi

echo "[startup] 6/6 健康检测服务启动（全部加载完成后才返回 ready）"
exec python3 /work/health_server.py
