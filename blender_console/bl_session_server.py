"""bl_session_server.py — 在 Blender 内启动持久 JSON-socket 服务（BlenderMCP 协议兼容）
================================================================================
由 blender 启动：blender --background --python bl_session_server.py
协议：{"type": "execute_code"|"get_scene_info"|"save_blend", "params": {...}}
响应：{"status": "success"|"error", "result"|"message": ...}
端口：9876（占用则 9877 递增）
"""
import bpy
import json
import socket
import threading

PORT = 9876


def _handle(code: str):
    ns = {"bpy": bpy, "math": __import__("math"),
          "Path": __import__("pathlib").Path}
    exec(code, ns)                                # noqa: S102 受控上游
    return "ok"


def _dispatch(req: dict) -> dict:
    t = req.get("type")
    p = req.get("params", {})
    if t == "execute_code":
        out = _handle(p.get("code", ""))
        return {"status": "success", "result": str(out)[:200]}
    if t == "get_scene_info":
        objs = [{"name": o.name, "type": o.type}
                for o in bpy.data.objects]
        return {"status": "success",
                "result": {"objects": objs, "count": len(objs)}}
    if t == "save_blend":
        bpy.ops.wm.save_as_mainfile(filepath=p.get("path"))
        return {"status": "success", "result": "saved"}
    return {"status": "error", "message": f"unknown type {t!r}"}


def _serve():
    """主线程 serve——dispatch 在主线程执行，bpy.ops/渲染全安全
    （非主线程调 ops 会崩溃——2026-09-29 实测）。"""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", PORT))
    srv.listen(4)
    print(f"[bl_session] serving on 127.0.0.1:{PORT}", flush=True)
    while True:
        conn, _ = srv.accept()
        try:
            buf = b""
            while True:
                chunk = conn.recv(1 << 16)
                if not chunk:
                    break
                buf += chunk
                try:
                    req = json.loads(buf.decode("utf-8"))
                    break
                except json.JSONDecodeError:
                    continue
            try:
                resp = _dispatch(req)
            except Exception as exc:              # noqa: BLE001
                resp = {"status": "error",
                        "message": f"{type(exc).__name__}: {exc}"[:400]}
            conn.sendall(json.dumps(resp).encode("utf-8"))
        except Exception as exc:                  # noqa: BLE001
            print("[bl_session] conn err:", exc, flush=True)
        finally:
            conn.close()


_serve()
