#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scheduler.py — HTTP 唤醒调度器（主控制器）

职责（对应你的规则）：
  1. 收到一条用户消息
  2. 先调用【本地模型】生成兜底回答（不依赖容器）
  3. 判断需要远程容器能力（浏览器/白名单站点）时：
     - 探测容器 /health
     - 离线/加载中 -> 发 HTTP GET 访问 Render 服务地址触发唤醒 -> 等待 30 秒 -> 重试
     - 重试仍未 ready -> 本次只返回本地模型回答 + 提示
  4. ready 后把任务发给容器内 Agent（POST /task），并把任务写入 GitHub 仓库留痕（可选）

运行方式：
  python3 scheduler.py "你要下发的任务消息"
  echo "任务" | python3 scheduler.py

环境变量（全部可选，均有默认值）：
  RENDER_URL        容器公网地址，默认 https://your-app.onrender.com
  WAIT_SECONDS      唤醒后等待秒数，默认 30
  GITHUB_TOKEN      用于把任务写入 GitHub 仓库（可空=不写仓库）
  GITHUB_REPO       仓库名，如 "yourname/repo"（可空=不写仓库）
  LOCAL_MODEL_URL   本地模型地址，默认 Ollama http://127.0.0.1:11434/api/generate
  LOCAL_MODEL_NAME  本地模型名，默认 qwen2.5:7b
  ALWAYS_USE_CONTAINER  1=每条消息都尝试容器；0=只本地模型（默认 1）
"""
import json
import os
import sys
import time
import base64
import urllib.request
import urllib.error

# ----------------------------------------------------------------------------
# 配置（从环境变量读取，无则用默认值）
# ----------------------------------------------------------------------------
RENDER_URL = os.environ.get("RENDER_URL", "https://your-app.onrender.com").rstrip("/")
HEALTH_URL = RENDER_URL + "/health"          # 容器内健康检测接口
TASK_URL   = RENDER_URL + "/task"            # 容器内任务接收接口

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")   # GitHub API Token
GITHUB_REPO  = os.environ.get("GITHUB_REPO", "")    # 如 "yourname/repo"

WAIT_SECONDS    = int(os.environ.get("WAIT_SECONDS", "30"))       # 唤醒后等待
LOCAL_MODEL_URL = os.environ.get("LOCAL_MODEL_URL", "http://127.0.0.1:11434/api/generate")
LOCAL_MODEL_NAME = os.environ.get("LOCAL_MODEL_NAME", "qwen2.5:7b")
ALWAYS_USE_CONTAINER = os.environ.get("ALWAYS_USE_CONTAINER", "1") != "0"

USER_AGENT = "scheduler/1.0"


# ----------------------------------------------------------------------------
# HTTP 基础工具
# ----------------------------------------------------------------------------
def http_get(url: str, timeout: int = 15):
    """GET 请求；成功返回 (状态码, 文本)，网络错误返回 (None, None)"""
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")
    except Exception:
        return None, None


def http_post(url: str, payload: dict, timeout: int = 120):
    """POST JSON 请求"""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")
    except Exception as e:
        return None, str(e)


# ----------------------------------------------------------------------------
# 容器状态探测 / 唤醒
# ----------------------------------------------------------------------------
def container_status() -> str:
    """返回 offline / loading / ready 三种状态"""
    code, body = http_get(HEALTH_URL, timeout=10)
    if code is None:
        return "offline"          # 请求不通 = 容器休眠中（或未部署）
    try:
        return json.loads(body).get("status", "loading")
    except Exception:
        return "loading"          # 有响应但格式不对 = 还在加载


def wake_container():
    """
    触发唤醒：向容器根路径发一次 GET 请求。
    Render 免费版规则：只要收到外部 HTTP 请求，休眠中的容器会自动开机。
    """
    return http_get(RENDER_URL, timeout=20)


# ----------------------------------------------------------------------------
# 本地模型（兜底层，与容器完全解耦）
# ----------------------------------------------------------------------------
def local_model(message: str) -> str:
    """优先本地模型回答；没有本地模型时给出占位提示"""
    if not LOCAL_MODEL_URL:
        return "[本地模型未配置，请设置 LOCAL_MODEL_URL]"
    payload = json.dumps({
        "model": LOCAL_MODEL_NAME,
        "prompt": message,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        LOCAL_MODEL_URL, data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
            return data.get("response", "")
    except Exception as e:
        return f"[本地模型调用失败：{e}]"


# ----------------------------------------------------------------------------
# GitHub API：把任务写入仓库（可选，留痕用）
# ----------------------------------------------------------------------------
def push_task_to_github(message: str) -> bool:
    if not (GITHUB_TOKEN and GITHUB_REPO):
        return False
    path = "tasks/todo.json"
    api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "User-Agent": USER_AGENT}

    # 1) 读取旧文件，拿到 sha 与内容
    old_sha, old_content = None, "[]"
    try:
        req = urllib.request.Request(api, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            old = json.loads(r.read().decode("utf-8"))
            old_sha = old.get("sha")
            old_content = base64.b64decode(old.get("content", "")).decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            return False

    # 2) 追加任务
    try:
        tasks = json.loads(old_content)
    except Exception:
        tasks = []
    tasks.append({
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "message": message,
    })

    # 3) 写回仓库
    body = {
        "message": "scheduler: add task",
        "content": base64.b64encode(json.dumps(tasks, ensure_ascii=False).encode()).decode(),
    }
    if old_sha:
        body["sha"] = old_sha
    req = urllib.request.Request(
        api, data=json.dumps(body).encode(), method="PUT",
        headers={**headers, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status in (200, 201)
    except Exception:
        return False


# ----------------------------------------------------------------------------
# 下发任务给容器内 Agent
# ----------------------------------------------------------------------------
def send_task_to_container(message: str):
    """容器 ready 后调用；返回 (状态码, 响应文本)"""
    return http_post(TASK_URL, {"task": message})


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def main():
    # 取消息：命令行参数优先，其次 stdin
    message = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read().strip()
    if not message:
        print("用法: python3 scheduler.py \"任务消息\" 或 echo 消息 | python3 scheduler.py")
        sys.exit(1)

    print(f"[1/7] 收到消息：{message[:60]}...", flush=True)

    # 兜底：先跑本地模型，保证任何情况下都有回答
    print("[2/7] 本地模型兜底回答中...", flush=True)
    local_answer = local_model(message)
    print(f"      本地回答（前100字）：{local_answer[:100]}", flush=True)

    # 不需要容器时，直接返回本地结果
    if not ALWAYS_USE_CONTAINER:
        print("[3/7] ALWAYS_USE_CONTAINER=0，本次仅本地模型回答。", flush=True)
        print("\n=== 最终回答 ===\n" + local_answer)
        return

    # 探测容器状态
    print("[3/7] 探测容器状态...", flush=True)
    status = container_status()
    print(f"      状态：{status}", flush=True)

    if status == "ready":
        print("[4/7] 容器已就绪，直接下发任务。", flush=True)
        code, body = send_task_to_container(message)
        final = local_answer + f"\n\n--- 容器执行结果 ---\n{body}" if body else local_answer
        print("\n=== 最终回答 ===\n" + final)
        return

    # 离线/加载中：发送 HTTP 唤醒请求
    print(f"[5/7] 容器{status}，发送 HTTP 唤醒请求 -> {RENDER_URL}", flush=True)
    wake_container()
    push_task_to_github(message)          # 可选：任务写入 GitHub 仓库留痕
    print(f"[6/7] 等待 {WAIT_SECONDS} 秒，让容器开机加载...", flush=True)
    time.sleep(WAIT_SECONDS)

    # 30 秒后重试探测
    status2 = container_status()
    print(f"      重试状态：{status2}", flush=True)
    if status2 == "ready":
        print("[7/7] 容器就绪，下发任务。", flush=True)
        code, body = send_task_to_container(message)
        final = local_answer + f"\n\n--- 容器执行结果 ---\n{body}" if body else local_answer
        print("\n=== 最终回答 ===\n" + final)
    else:
        print(f"[7/7] 容器仍不可用（{status2}），本次仅本地模型回答。", flush=True)
        print("\n=== 最终回答 ===\n" + local_answer +
              "\n\n⚠️ 远程容器未就绪（唤醒失败或仍在加载），本次仅本地模型回复。")


if __name__ == "__main__":
    main()
