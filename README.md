# render-agent-cloud 部署说明

这套文件实现你要求的完整逻辑：
**发消息给 Agent -> 容器自动唤醒 -> 等待 30 秒 -> 就绪后才允许执行 -> 未就绪则本地模型兜底**

## 文件清单
| 文件 | 作用 |
|---|---|
| `scheduler.py` | **HTTP 唤醒调度器**（跑在你本地/Termux/任意常驻环境） |
| `Dockerfile` | 云桌面镜像：Ubuntu + noVNC + Chrome + Python + Java + Squid |
| `startup.sh` | 容器开机串行加载脚本（健康服务最后启动） |
| `health_server.py` | 容器内健康检测 `/health` + 任务接收 `/task` |
| `squid/squid.conf` | 白名单代理配置（只放行指定站点） |

## 部署步骤（Render 为例）

### 1. 容器侧（Render）
1. 登录 [render.com](https://render.com)（GitHub 账号，免实名免卡）
2. New + → **Blueprint / Web Service** → 关联本文件夹所在 GitHub 仓库
3. 构建方式选 **Dockerfile**
4. 环境变量设置：
   - `VNC_PASSWD` = 你的桌面登录密码（构建参数）
   - `HEALTH_PORT` = `8000`
   - `AGENT_AUTOSTART` = `0`（保持手动，不自动跑 Agent）
5. 部署完成拿到公网地址 `https://xxx.onrender.com`
6. 规则：**连续 15 分钟无外部请求自动休眠；任一 HTTP 访问自动唤醒**

### 2. 调度器侧（本地）
```bash
export RENDER_URL="https://xxx.onrender.com"   # 你的容器地址
export WAIT_SECONDS="30"
export GITHUB_TOKEN="你的GitHub Token"           # 可选
export GITHUB_REPO="你的用户名/仓库名"            # 可选
python3 scheduler.py "帮我查一下这个任务的执行情况"
```

### 3. 手动接管（人工）
浏览器打开 `https://xxx.onrender.com:6080`（或按平台端口转发规则访问 noVNC），
输入 VNC 密码进入可视化桌面。**别人没有密码进不去。**

## 白名单站点（squid.conf 里已配置）
github.com / gitlab.com / gitea.io / pypi.org / maven.org /
apkpure.com / 常见数据库官网 / leetcode.com 等；其余全部拦截。

## 已知限制
- 免费档 512M 内存：开 Chrome + Agent 会卡，建议任务轻量化
- 免费版无持久盘：每次唤醒重置环境 → Agent 代码放 GitHub，启动时 `git pull`
- Android SDK 默认不加（体积/内存），需要时 `--build-arg WITH_ANDROID_SDK=1` 重新构建
