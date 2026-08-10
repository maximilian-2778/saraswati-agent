"""Single-process Windows launcher for the packaged Saraswati Agent."""

from __future__ import annotations

import argparse
import socket
import threading
import time
import urllib.request
import webbrowser

import uvicorn


def available_port(preferred: int = 8010) -> int:
    for port in (preferred, 0):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", port))
                return int(probe.getsockname()[1])
        except OSError:
            continue
    raise RuntimeError("无法分配本机端口。")


def open_when_ready(url: str) -> None:
    health_url = f"{url}/api/health"
    for _ in range(120):
        try:
            with urllib.request.urlopen(health_url, timeout=0.5) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except Exception:
            time.sleep(0.25)


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 Saraswati Agent")
    parser.add_argument("--port", type=int, default=8010, help="首选监听端口")
    parser.add_argument("--no-browser", action="store_true", help="不要自动打开浏览器")
    args = parser.parse_args()

    port = available_port(args.port)
    url = f"http://127.0.0.1:{port}"
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()

    print("Saraswati Agent 正在启动……")
    print(f"应用地址：{url}")
    print("关闭此窗口或按 Ctrl+C 即可停止服务。")

    from backend.main import create_app

    uvicorn.run(
        create_app(), host="127.0.0.1", port=port,
        log_level="warning", access_log=False,
    )


if __name__ == "__main__":
    main()
