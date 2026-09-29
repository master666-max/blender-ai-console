"""mcp_bridge.py — BlenderMCP (127.0.0.1:9875) 桥接客户端
用法：from mcp_bridge import bl_exec, bl_call
"""
import json
import socket


def bl_call(payload: dict, timeout: float = 300.0) -> dict:
    s = socket.create_connection(("127.0.0.1", 9876), timeout=timeout)
    s.sendall(json.dumps(payload).encode("utf-8"))
    buf = b""
    try:
        while True:
            chunk = s.recv(1 << 16)
            if not chunk:
                break
            buf += chunk
            try:
                return json.loads(buf.decode("utf-8"))
            except json.JSONDecodeError:
                continue
    finally:
        s.close()
    raise RuntimeError("no response")


def bl_exec(code: str, timeout: float = 300.0) -> dict:
    """在用户 Blender 主线程执行代码（GUI 实时可见）。"""
    return bl_call({"type": "execute_code", "params": {"code": code}}, timeout)


if __name__ == "__main__":
    r = bl_call({"type": "get_scene_info"})
    print(json.dumps(r, ensure_ascii=False)[:1500])
