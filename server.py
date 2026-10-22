#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import time
import threading
import importlib
from pathlib import Path
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = Path(__file__).resolve().parent
OUT = BASE / "docs" / "data"
OUT.mkdir(parents=True, exist_ok=True)

POLL_SECONDS = 30
PORT = int(os.environ.get("PORT", "10000"))

RUN_LOCK = threading.Lock()
STATUS = {
    "started_at": datetime.now(timezone.utc).isoformat(),
    "last_run": None,
    "last_error": None,
    "running": True
}


def update_once():
    results = {}

    with RUN_LOCK:
        for key, name in [
            ("low", "lowest"),
            ("high", "highest")
        ]:
            try:
                module = importlib.import_module(name)

                module.STATE = OUT / (key + ".json")
                module.S = module.load()

                result = module.action("start")
                data = module.snapshot()
                data["message"] = result["message"]

                results[key] = {
                    "ok": True,
                    "message": result["message"]
                }

            except Exception as exc:
                results[key] = {
                    "ok": False,
                    "error": str(exc)
                }
                data = {"last_error": str(exc)}

            path = OUT / (key + "_view.json")
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

        now = datetime.now(timezone.utc).isoformat()

        health = {
            "updated_at": now,
            "results": results
        }

        (OUT / "health.json").write_text(
            json.dumps(health, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        STATUS["last_run"] = now
        STATUS["last_error"] = {
            k: v.get("error")
            for k, v in results.items()
            if not v["ok"]
        } or None

        print(json.dumps(health, ensure_ascii=False), flush=True)


def worker():
    while True:
        try:
            update_once()
        except Exception as exc:
            STATUS["last_error"] = str(exc)
            print("自动更新失败:", exc, flush=True)

        time.sleep(POLL_SECONDS)


class Handler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/health":
            body = json.dumps(
                STATUS,
                ensure_ascii=False
            ).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"Not Found")


if __name__ == "__main__":
    threading.Thread(
        target=worker,
        daemon=True
    ).start()

    print(
        f"加拿大3D双方案云端服务启动，端口 {PORT}",
        flush=True
    )

    server = ThreadingHTTPServer(
        ("0.0.0.0", PORT),
        Handler
    )

    server.serve_forever()
