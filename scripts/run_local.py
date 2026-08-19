"""本机一键启动（无 Docker）：engine + studio(report serve / bot / cron) 四进程。

用法:
    python scripts/run_local.py            # 真实模式全量启动
    python scripts/run_local.py --mock     # 引擎 mock(3 秒假跑,管道调试用)
    python scripts/run_local.py --no-bot   # 不起飞书 bot(避免与服务器抢消息)

前置（一次性）:
    python -m venv .venv && .venv\\Scripts\\activate
    pip install -e ./vendor/astock -e ./engine -e ./studio
    cp .env.example .env                   # 填百炼 key、飞书凭据
    cp studio/studio.yaml.example studio.yaml

⚠️ 飞书长连接全局只允许单实例（多实例随机投递）。本机起 bot 前请停掉服务器端:
    ssh polytact "cd /opt/polytact-morning && docker compose stop studio"
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_env_file(path: Path) -> dict[str, str]:
    """解析 .env 进 dict（不覆盖已有环境变量）。"""
    kv: dict[str, str] = {}
    if not path.exists():
        return kv
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        kv[k.strip()] = v.strip().strip('"').strip("'")
    return kv


def build_base_env(mock: bool) -> dict[str, str]:
    """组装所有子进程共享的环境：.env + 本机默认值 + UTF-8。"""
    env = dict(os.environ)
    for k, v in load_env_file(REPO_ROOT / ".env").items():
        env.setdefault(k, v)

    env["PYTHONUTF8"] = "1"            # Windows 中文控制台 GBK 会炸 rich 输出
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"

    data_dir = env.get("TA_DATA_DIR", "").strip()
    if not data_dir or data_dir == "/data":
        # /data 是容器内路径；本机默认仓库下 data/（已 gitignore）
        data_dir = str(REPO_ROOT / "data")
        env["TA_DATA_DIR"] = data_dir
    if mock:
        env["POLYTACT_ENGINE_MOCK"] = "1"

    # 报告链接前缀：本机报告服务只绑 localhost；.env 里若写的是服务器地址，
    # 本机跑的报告在服务器上不存在（且两边 token 密钥不同），必须指回本机。
    prefix = env.get("REPORT_URL_PREFIX", "").strip()
    if not prefix or "101.200.180.180" in prefix:
        env["REPORT_URL_PREFIX"] = "http://localhost:8890"

    # 本机联调友好化：占位 secret 自动换成进程内随机串（不污染 .env；
    # 重启后旧报告链接失效，对本机调试无碍）
    import secrets as _secrets

    for key in ("REPORT_TOKEN_SECRET", "JWT_SECRET", "ENGINE_PASSWORD"):
        val = env.get(key, "").strip()
        if not val or val.startswith("填"):
            env[key] = _secrets.token_hex(24)
            print(f"[init] {key} 未配置，已生成本机临时随机串", flush=True)

    # studio 侧：配置文件与引擎地址
    env.setdefault("STUDIO_CONFIG", str(REPO_ROOT / "studio.yaml"))
    env["STUDIO__API__BASE_URL"] = "http://127.0.0.1:8000"
    env["STUDIO__DATA__TA_DIR"] = data_dir  # 引擎落盘根（只读视角）
    return env


def ensure_studio_yaml() -> None:
    target = REPO_ROOT / "studio.yaml"
    if target.exists():
        return
    src = REPO_ROOT / "studio" / "studio.yaml.example"
    target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"[init] 已从 {src.name} 生成 studio.yaml，请按需检查修改", flush=True)


def pipe_output(name: str, proc: subprocess.Popen) -> None:
    """子进程输出加前缀转发（在线程里跑）。"""
    assert proc.stdout is not None
    for line in proc.stdout:
        try:
            print(f"[{name}] {line}", end="", flush=True)
        except UnicodeEncodeError:
            print(f"[{name}] {line.encode('utf-8', 'replace').decode('utf-8', 'replace')}",
                  end="", flush=True)


def kill_tree(proc: subprocess.Popen) -> None:
    """杀进程树（Windows taskkill /T 连子孙一起；POSIX 先 terminate）。"""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True)
        else:
            proc.terminate()
    except OSError:
        pass


def main() -> int:
    # 主进程自身的 stdout 也可能是 GBK 控制台（PYTHONUTF8 只对子进程生效）
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    mock = "--mock" in sys.argv
    no_bot = "--no-bot" in sys.argv
    env = build_base_env(mock)
    ensure_studio_yaml()

    if not no_bot:
        print("⚠️  飞书长连接只允许单实例：若服务器上的 studio 在跑，请先 "
              "`ssh polytact \"cd /opt/polytact-morning && docker compose stop studio\"`", flush=True)

    engine_port = int(env.get("ENGINE_PORT", "8000"))
    report_port = int(env.get("STUDIO_REPORT_PORT", "8890"))

    procs: list[tuple[str, subprocess.Popen]] = []
    started_at: dict[int, float] = {}
    bot_cmd = [sys.executable, "-m", "studio", "bot", "run"]

    def spawn(name: str, args: list[str], cwd: Path) -> None:
        proc = subprocess.Popen(
            args, cwd=str(cwd), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace",
        )
        procs.append((name, proc))
        started_at[proc.pid] = time.time()
        threading.Thread(target=pipe_output, args=(name, proc), daemon=True).start()
        print(f"[run] {name} 已启动 (pid={proc.pid})", flush=True)

    spawn("engine", [sys.executable, "-m", "uvicorn", "engine.main:app",
                     "--host", "127.0.0.1", "--port", str(engine_port)],
          REPO_ROOT / "engine")
    # engine 是命脉：起不来（如端口被占）则快速失败，不留下半个系统
    time.sleep(4)
    if procs and procs[0][1].poll() is not None:
        print(f"[run] ✗ engine 启动失败（端口 {engine_port} 被占？），已退出。"
              f"查占用：netstat -ano | findstr :{engine_port}", flush=True)
        return 1
    spawn("report", [sys.executable, "-m", "studio", "report", "serve",
                     "--port", str(report_port)], REPO_ROOT)
    if not no_bot:
        spawn("bot", bot_cmd, REPO_ROOT)
    spawn("cron", [sys.executable, "-m", "studio", "cron"], REPO_ROOT)

    print(f"[run] 全部就绪（mock={mock}）。Ctrl+C 停止全部进程。", flush=True)
    try:
        while True:
            time.sleep(1)
            for name, proc in procs[:]:  # 副本迭代：循环内会增删 procs
                if proc.poll() is not None:
                    procs.remove((name, proc))
                    lived = time.time() - started_at.pop(proc.pid, time.time())
                    print(f"[run] ⚠ {name} 已退出 (code={proc.returncode})，"
                          f"日志见上。", flush=True)
                    # bot 长连接运行一段时间后断开（网络抖动等）→ 自动重连；
                    # 启动即败（如缺凭据）不重启，避免刷屏
                    if name == "bot" and not no_bot and lived > 10:
                        print("[run] bot 运行异常断开，5 秒后自动重连…", flush=True)
                        time.sleep(5)
                        spawn("bot", bot_cmd, REPO_ROOT)
    except KeyboardInterrupt:
        print("\n[run] 正在停止全部进程…", flush=True)
        for name, proc in procs:
            kill_tree(proc)
        for name, proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        return 0
    finally:
        # 兜底：任何异常退出路径都不留孤儿进程（Windows 无 PDEATHSIG）
        for name, proc in procs:
            if proc.poll() is None:
                kill_tree(proc)


if __name__ == "__main__":
    sys.exit(main())
