"""embedded_server.py — Blender 内嵌 API 服务器（挂单 W-3 落地）

架构（bpy 数据只许主线程碰，HTTP 在 daemon 线程收）：
  HTTPServer daemon 线程：收请求 → 封装 job → 投递队列 → event.wait(30s)
  主线程泵：每 tick 取 job → fn() → 结果塞回 → event.set()
  双泵模式：
    pump="timers"  GUI 模式：bpy.app.timers 自动 tick（persistent=True）
    pump="manual"  后台脚本模式：宿主主循环调 embedded_server.pump()
                   （--background 下脚本占用主线程，timers 不 tick——实测结论）

用法（Blender Python 内）：
  import embedded_server as es
  es.bind_console(console)                    # 绑定 Console 实例
  es.start(port=8377, static_dir="../m9_web", pump="timers")
  es.stop()                                   # 幂等可重启

API（与 m9_web/console.html 契约对齐，响应 {ok, summary, error?, data?}）：
  GET  /api/state     → console.export_state()
  POST /api/verify    → console.verify()
  POST /api/render    → console.render_diff()
  POST /api/pop       → console.pop_layer()
  POST /api/checkpoint {name}   → console.checkpoint(name)
  POST /api/revert    {name}   → console.revert_to_checkpoint(name)
  POST /api/set_param {seg,param,value} → console.set_param(...)
  POST /api/override  {note?}  → console.override(note)
  POST /api/drop_segment {seg} → console.drop_segment(seg)
  其余 op → 结构化 UNKNOWN_OP（不谎报成功）
"""
import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# ── 状态 ────────────────────────────────────────────────────
_console = None            # Console 实例（主线程使用）
_static_dir = None         # m9_web 目录（静态兜底）
_port = 8377
_httpd = None
_thread = None
_timer_key = None          # timers 返回句柄
_jobs = queue.Queue()      # job: {"fn", "res", "evt"}
_started = False


def bind_console(console) -> None:
    """绑定 Console 实例（必须在 start 前调用）。"""
    global _console
    _console = console


def _jsonable(x):
    """ConsoleResult / 任意对象 → JSON 安全结构（str 兜底，不静默丢错）。"""
    if x is None or isinstance(x, (bool, int, float, str)):
        return x
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if hasattr(x, "to_tool_return"):
        return _jsonable(x.to_tool_return())
    if hasattr(x, "__dict__"):
        out = {}
        for k, v in vars(x).items():
            if k.startswith("_"):
                continue
            try:
                json.dumps(v)
                out[k] = v
            except (TypeError, ValueError):
                out[k] = str(v)[:200]
        return out
    return str(x)[:400]


def _result(r):
    """ConsoleResult → {ok, summary, error?, data?}（console.html 契约）。
    2026-09-29 真机探针：_route 已返回契约 dict 时不得再包一层——
    dict 落到 _jsonable 兜底会变 repr 字符串（双重编码炸前端）。"""
    if r is None:
        return {"ok": False, "summary": "handler returned None"}
    if isinstance(r, dict):
        return r
    if hasattr(r, "ok"):
        out = {"ok": bool(r.ok), "summary": getattr(r, "summary", "") or ""}
        if getattr(r, "error", None):
            out["error"] = _jsonable(r.error)
        if getattr(r, "data", None):
            out["data"] = _jsonable(r.data)
        return out
    return _jsonable(r)


# ── 主线程泵 ────────────────────────────────────────────────
def pump() -> None:
    """处理队列中全部 job（主线程调用；manual 模式由宿主循环调）。"""
    while True:
        try:
            job = _jobs.get_nowait()
        except queue.Empty:
            return
        try:
            job["res"] = _result(job["fn"]())
        except Exception as exc:                      # noqa: BLE001 响亮失败进响应
            job["res"] = {"ok": False,
                          "summary": f"handler exception: {exc!r}"[:300]}
        job["evt"].set()


def _tick():
    pump()
    return 0.1 if _started else None


def _submit(fn, timeout=30.0):
    """任意线程投递 job → 阻塞等主线程执行完。"""
    job = {"fn": fn, "res": None, "evt": threading.Event()}
    _jobs.put(job)
    if not job["evt"].wait(timeout):
        return {"ok": False, "summary": f"main-thread timeout after {timeout}s"}
    return job["res"]


# ── 路由 ────────────────────────────────────────────────────
def _route(method: str, path: str, body: dict) -> dict:
    """主线程内执行（HTTP 线程经 _submit 进入）。返回 JSON dict。"""
    if method == "GET" and path == "/api/state":
        return _result(_console.export_state())

    if method != "POST" or not path.startswith("/api/"):
        return {"ok": False, "summary": f"unsupported {method} {path}"}

    op = path[len("/api/"):].strip("/")

    def _need(*keys):
        missing = [k for k in keys if k not in body]
        if missing:
            raise ValueError(f"missing body keys: {missing}")

    fns = {
        "verify":       lambda: _console.verify(body.get("label", "api")),
        "render":       lambda: _console.render_diff(body.get("label", "")),
        "pop":          lambda: _console.pop_layer(),
        "override":     lambda: _console.override(str(body.get("note", ""))),
        "checkpoint":   lambda: (_need("name"),
                                 _console.checkpoint(str(body["name"])))[1],
        "revert":       lambda: (_need("name"),
                                 _console.revert_to_checkpoint(str(body["name"])))[1],
        "set_param":    lambda: (_need("seg", "param", "value"),
                                 _console.set_param(str(body["seg"]),
                                                    str(body["param"]),
                                                    body["value"]))[1],
        "drop_segment": lambda: (_need("seg"),
                                 _console.drop_segment(str(body["seg"])))[1],
    }
    fn = fns.get(op)
    if fn is None:
        return {"ok": False,
                "summary": f"UNKNOWN_OP {op!r}（known: {sorted(fns)}）",
                "error": {"error_code": "UNKNOWN_OP", "failed_node": op}}
    return fn()


# ── HTTP 层（daemon 线程）───────────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):                # noqa: A003 静默访问日志
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send(self, code: int, payload: dict):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self._cors()
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):                             # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):                                 # noqa: N802
        if self.path.startswith("/api/"):
            if _console is None:
                self._send(503, {"ok": False, "summary": "console not bound"})
                return
            self._send(200, _submit(lambda: _route("GET", self.path, {})))
            return
        # 静态兜底（console.html / state.json / 渲染图）
        self._static()

    def do_POST(self):                                # noqa: N802
        if not self.path.startswith("/api/"):
            self._send(404, {"ok": False, "summary": "not found"})
            return
        if _console is None:
            self._send(503, {"ok": False, "summary": "console not bound"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except (ValueError, json.JSONDecodeError) as exc:
            self._send(400, {"ok": False, "summary": f"bad json: {exc!r}"[:200]})
            return
        self._send(200, _submit(lambda: _route("POST", self.path, body)))

    def _static(self):
        if _static_dir is None:
            self._send(404, {"ok": False, "summary": "no static dir bound"})
            return
        rel = self.path.lstrip("/") or "console.html"
        target = (Path(_static_dir) / rel).resolve()
        try:
            target.relative_to(Path(_static_dir).resolve())
        except ValueError:
            self._send(403, {"ok": False, "summary": "path traversal"})
            return
        if not target.is_file():
            self._send(404, {"ok": False, "summary": f"no such file {rel}"})
            return
        raw = target.read_bytes()
        ctype = ("text/html; charset=utf-8" if target.suffix == ".html"
                 else "application/json" if target.suffix == ".json"
                 else "image/png" if target.suffix == ".png"
                 else "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self._cors()
        self.end_headers()
        self.wfile.write(raw)


# ── 生命周期 ────────────────────────────────────────────────
def start(port: int = 8377, static_dir: str | Path | None = None,
          pump_mode: str = "timers") -> dict:
    """启动（幂等：已启动则先停再起）。pump_mode: "timers" | "manual"。"""
    global _httpd, _thread, _static_dir, _port, _started, _timer_key
    if _started:
        stop()
    _console  # noqa: B018 绑定检查放路由层（503），这里允许先起服务后绑
    _static_dir = str(Path(static_dir).resolve()) if static_dir else None
    _port = int(port)
    _httpd = HTTPServer(("127.0.0.1", _port), _Handler)
    _httpd.daemon_threads = True
    _thread = threading.Thread(target=_httpd.serve_forever,
                               kwargs={"poll_interval": 0.2}, daemon=True)
    _thread.start()
    _started = True
    if pump_mode == "timers":
        import bpy
        _timer_key = bpy.app.timers.register(_tick, persistent=True)
    return {"ok": True, "summary": f"embedded API on 127.0.0.1:{_port} "
                                   f"(pump={pump_mode}, static={_static_dir})"}


def stop() -> dict:
    """停止（幂等）。"""
    global _httpd, _thread, _started, _timer_key
    if not _started:
        return {"ok": True, "summary": "already stopped"}
    _started = False
    if _timer_key is not None:
        try:
            import bpy
            bpy.app.timers.unregister(_tick)
        except Exception:                             # noqa: BLE001
            pass
        _timer_key = None
    if _httpd is not None:
        _httpd.shutdown()
        _httpd.server_close()
        _httpd = None
    if _thread is not None:
        _thread.join(timeout=3)
        _thread = None
    return {"ok": True, "summary": "stopped"}


def is_running() -> bool:
    return _started and _httpd is not None
