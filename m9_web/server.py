"""m9_web/server.py — 虎式流程轴控制台（纯 Python，零 bpy 依赖）
运行：python server.py （任何 Python 3.8+ 均可）
端口：8377
"""
import json, os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)

class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

print("[server] http://127.0.0.1:8377 — 虎式流程轴控制台")
print("[server] state.json segments:", end=" ")
d = json.load(open("state.json", encoding="utf-8"))
print(len(d.get("segments", {})), "| mode:", d.get("mode"))
HTTPServer(("0.0.0.0", 8377), Handler).serve_forever()
