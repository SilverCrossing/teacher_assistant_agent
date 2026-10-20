"""便携版入口：内置 Python 与网页资源，教师双击 exe 即可。"""
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

import httpx

from grading_assistant.main import main

URL = "http://127.0.0.1:8765"


def running():
    try:
        with httpx.Client(timeout=1, trust_env=False) as client:
            data = client.get(URL + "/api/health").json()
            return data.get("status") == "ok" and data.get("schema_version") == "1"
    except Exception:
        return False


def main_desktop():
    # 浏览器内核由学校维护者随发布包分发，不使用教师日常浏览器的账号数据。
    root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    browsers = root / "browsers"
    if browsers.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers)
    config = root / "config/local.json"
    if config.exists():
        os.environ.setdefault("GRADING_CONFIG", str(config))
    if running():
        if not os.environ.get("GRADING_NO_BROWSER"):
            webbrowser.open(URL)
        return

    def open_when_ready():
        for _ in range(60):
            if running():
                webbrowser.open(URL)
                return
            time.sleep(0.5)
    if not os.environ.get("GRADING_NO_BROWSER"):
        threading.Thread(target=open_when_ready, daemon=True).start()
    print("阅卷助手正在运行。使用结束后关闭此窗口即可退出。")
    main()


if __name__ == "__main__":
    main_desktop()
