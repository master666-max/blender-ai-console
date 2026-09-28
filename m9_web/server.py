"""m9_web/server.py — Blender 5.2 内嵌 HTTP 服务器（Console API + 静态文件）"""
import bpy, json, sys, time, traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

M9 = Path(__file__).resolve().parent
PROJ = M9.parent / "blender_console"
sys.path.insert(0, str(PROJ))
PORT = 8377

bpy.ops.wm.read_factory_settings(use_empty=True)
mesh = bpy.data.meshes.new("tiger_root")
obj = bpy.data.objects.new("tiger_root", mesh)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj

from gn_adapter import GNAdapter
from console import Console
from m1_core import export_state
from experience import ExperienceLibrary

ad = GNAdapter()
console = Console(ad, obj, workdir=str(PROJ / "tiger_work"))
lib = ExperienceLibrary(PROJ / "experience_library.json")
LOG = []

lt_path = PROJ / "logic_trees" / "tiger_tank.json"
lt_obj = {}
try:
    lt_obj = json.loads(lt_path.read_text(encoding="utf-8"))
    from logic_tree import to_plan
    plan = to_plan(lt_obj)
    for sec in plan["sections"]:
        try:
            r = console.compile(sec)
            LOG.append({"action": "compile", "id": sec["id"], "ok": r.ok})
        except Exception as exc:
            LOG.append({"action": "compile", "id": sec["id"], "ok": False, "error": str(exc)[:200]})
except Exception as exc:
    LOG.append({"action": "preload", "error": str(exc)[:200]})
print("[server] pre-compile done, LOG entries:", len(LOG))


def _snapshot():
    r = console.export_state()
    if hasattr(r, "to_tool_return"):
        return json.loads(r.to_tool_return())
    if hasattr(r, "result") and isinstance(r.result, dict):
        d = r.result
        return d.get("data", d)
    return {"error": "unexpected type"}


def _log(action, **kw):
    LOG.append({"action": action, "ts": time.strftime("%H:%M:%S"), **kw})


class Handler(BaseHTTPRequestHandler):
    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            if self.path == "/api/state":
                self._json(_snapshot())
            elif self.path == "/api/log":
                self._json(LOG[-50:])
            elif self.path == "/api/tree":
                self._json(lt_obj)
            else:
                fp = M9 / self.path.lstrip("/").split("?")[0]
                if not fp.is_file():
                    fp = M9 / "index.html"
                if fp.is_file():
                    ct = {".html": "text/html", ".json": "application/json",
                          ".mjs": "text/javascript"}.get(fp.suffix, "text/plain")
                    body = fp.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", ct + "; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_error(404)
        except Exception as exc:
            traceback.print_exc()
            self._json({"ok": False, "error": str(exc)[:300]}, code=500)

    def do_POST(self):
        try:
            self._handle_post()
        except Exception as exc:
            traceback.print_exc()
            self._json({"ok": False, "error": str(exc)[:300]}, code=500)

    def _handle_post(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        if self.path == "/api/compile":
            r = console.compile(body)
            _log("compile", id=body.get("id"), ok=r.ok)
            self._json(r.to_tool_return())
        elif self.path == "/api/checkpoint":
            r = console.checkpoint(body.get("name", "GP"))
            _log("checkpoint", name=body.get("name"))
            self._json(r.to_tool_return())
        elif self.path == "/api/revert":
            r = console.revert_to_checkpoint(body.get("name", ""))
            _log("revert", name=body.get("name"))
            self._json(r.to_tool_return())
        elif self.path == "/api/pop":
            r = console.pop_layer()
            _log("pop")
            self._json(r.to_tool_return())
        elif self.path == "/api/verify":
            r = console.verify(body.get("label", ""))
            _log("verify", ok=r.ok)
            self._json(r.to_tool_return())
        elif self.path == "/api/render":
            r = console.render_diff(body.get("label", ""))
            _log("render", ok=r.ok)
            self._json(r.to_tool_return())
        elif self.path == "/api/accept":
            r = console.accept(body.get("note", ""))
            _log("accept")
            self._json(r.to_tool_return())
        elif self.path == "/api/override":
            r = console.override(body.get("note", ""))
            _log("override")
            self._json(r.to_tool_return())
        elif self.path == "/api/set_param":
            r = console.set_param(body["seg"], body["param"], body["value"])
            _log("set_param", seg=body["seg"])
            self._json(r.to_tool_return())
        else:
            self.send_error(404)
            return
        try:
            (M9 / "state.json").write_text(
                json.dumps(_snapshot(), ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass


print("[server] http://127.0.0.1:8377 ready")
HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
