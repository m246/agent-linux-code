#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
health_server.py — 容器内健康检测 + 任务接收服务（端口 8000）

接口：
  GET  /health  返回 {"status": "ready"|"loading", "services": {...}}
                ready = squid/Xvfb/noVNC/浏览器/Python/Java 全部就绪
                loading = 还有组件未加载完（此时调度器不会下发任务）
  GET  /        服务说明
  POST /task    接收调度器下发的一条任务，写入 /work/tasks/inbox.json
                （容器内 Agent 从此文件读取任务执行）

可选：BRANCH_AGENT_AUTOSTART=1 时，容器一就绪就自动拉 GitHub 代码并启动 Agent，
      否则完全由人工/调度器触发（默认关闭，符合你的手动逻辑）。
"""
import json
import os
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("HEALTH_PORT", "8000"))
AGENT_AUTOSTART = os.environ.get("AGENT_AUTOSTART", "0") == "1"
AGENT_REPO = os.environ.get("AGENT_REPO", "")   # 如 "yourname/agent"（可选，自动拉代码用）

SERVICES = ["squid", "xvfb", "novnc", "chrome", "python", "java"]


def _pgrep(pattern: str) -> bool:
    return subprocess.run(["pgrep", "-f", pattern],
                          capture_output=True).returncode == 0


def check(name: str) -> bool:
    """检查单个服务是否就绪"""
    if name == "squid":
        return _pgrep("squid")
    if name == "xvfb":
        return _pgrep("Xvfb")
    if name == "novnc":
        return _pgrep("websockify")
    if name == "chrome":
        return (shutil.which("google-chrome") is not None
                or shutil.which("chromium-browser") is not None
                or shutil.which("chromium") is not None)
    if name == "python":
        return shutil.which("python3") is not None
    if name == "java":
        return shutil.which("java") is not None
    return False


def all_ready() -> dict:
    return {s: check(s) for s in SERVICES}


def pull_and_start_agent():
    """（可选）就绪后自动拉取 GitHub 代码并启动 Agent"""
    if AGENT_AUTOSTART and AGENT_REPO:
        os.makedirs("/work/agent", exist_ok=True)
        if not os.path.exists("/work/agent/.git"):
            subprocess.Popen(
                ["git", "clone", f"https://github.com/{AGENT_REPO}.git", "/work/agent"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.Popen(
            ["bash", "-c", "cd /work/agent && git pull && nohup python3 main.py > agent.log 2>&1 &"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def start_autostart_thread():
    """就绪后延迟 3 秒触发 Agent 自动启动（一次性）"""
    if AGENT_AUTOSTART and AGENT_REPO:
        threading.Timer(3.0, pull_and_start_agent).start()


class Handler(BaseHTTPRequestHandler):

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            state = all_ready()
            ready = all(state.values())
            self._send_json({"status": "ready" if ready else "loading",
                             "services": state})
        elif self.path == "/":
            self._send_json({
                "app": "container-agent",
                "health": "GET /health",
                "task": "POST /task",
            })
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/task":
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                data = json.loads(raw.decode("utf-8", "ignore"))
            except Exception:
                data = {"task": raw.decode("utf-8", "ignore")}
            # 写入待办队列，容器内 Agent 从这里消费
            os.makedirs("/work/tasks", exist_ok=True)
            with open("/work/tasks/inbox.json", "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
            self._send_json({"ok": True, "saved": "/work/tasks/inbox.json",
                             "task": data})
        else:
            self._send_json({"error": "not found"}, 404)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"[health] listening on :{PORT}", flush=True)
    start_autostart_thread()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
