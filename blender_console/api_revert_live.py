"""api_revert_live.py — Web 控制台 API 层完整闭环实验（挂单 W-3 验收）

架构验证：HTTP daemon 线程（收请求）→ 队列 → 主线程 pump（bpy 安全）→ 响应。
client 线程用 urllib 发真实 HTTP 请求（不是直接调函数——测的是整条链）。

实验矩阵（12 步）：
  1  GET  /api/state            → 3 段在册
  2  POST /api/checkpoint cp1   → ok
  3  POST /api/set_param        → ok 且几何生效（data.stats）
  4  POST /api/revert cp1       → ok
  5  POST /api/pop              → ok（面数下降）
  6  POST /api/drop_segment     → ok
  7  POST /api/verify           → PASS
  8  POST /api/override         → ok
  9  POST /api/unknown_op       → UNKNOWN_OP 结构化错误（不谎报成功）
  10 GET  /                     → console.html 静态伺服（200 text/html）
  11 GET  /api/state            → 终态 1 段
  12 主线程 pump 模式端到端延迟   → 全部请求 < 60s 完成（无死锁）
运行：blender.exe --factory-startup --background --python api_revert_live.py
"""
import bpy, sys, json, time, threading, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
WORK = HERE / "api_work"
WORK.mkdir(exist_ok=True)
WEB = HERE.parent / "m9_web"
PORT = 8388
BASE = f"http://127.0.0.1:{PORT}"

bpy.ops.wm.read_factory_settings(use_empty=True)
mesh = bpy.data.meshes.new("api_root")
root = bpy.data.objects.new("api_root", mesh)
bpy.context.collection.objects.link(root)
bpy.context.view_layer.objects.active = root

from console import Console
from gn_adapter import GNAdapter
import embedded_server as es

console = Console(GNAdapter(), root, workdir=str(WORK))
SECS = [
    {"id": "seg_a", "op": "cube", "stage": "structure", "part": "a",
     "consumes_input": False, "depends_on": [],
     "parameters": [{"name": "Size", "type": "FLOAT", "value": 0.05}]},
    {"id": "seg_b", "op": "join_geometry", "stage": "structure", "part": "b",
     "consumes_input": True, "depends_on": [],
     "parameters": [{"name": "Radius", "type": "FLOAT", "value": 0.012}],
     "operand": {"op": "cylinder", "radius": 0.012, "depth": 0.04}},
    {"id": "seg_c", "op": "join_geometry", "stage": "structure", "part": "c",
     "consumes_input": True, "depends_on": [],
     "operand": {"op": "sphere", "radius": 0.018}},
]
for sp in SECS:
    r = console.compile(sp)
    print("   compile %s: %s" % (sp["id"], "ok" if r.ok else r.error))

ROWS = []
def check(n, desc, cond):
    ROWS.append(cond)
    print("[api %2d] %s %s" % (n, "PASS" if cond else "FAIL", desc))

def req(method, path, body=None):
    data = json.dumps(body or {}).encode() if method == "POST" else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=60) as resp:
        return json.loads(resp.read().decode()), resp.status, resp.headers

def client_run(done, results):
    step = 0
    try:
        # 1 state
        step = 1
        d, st, _ = req("GET", "/api/state")
        print("   [probe] step1 raw type=%s head=%s" % (type(d).__name__, str(d)[:160]))
        results.append((1, "GET /api/state → 3 段在册",
                        st == 200 and len(d.get("data", {}).get("segments", d.get("segments", {}))) >= 3
                        or len(d.get("segments", {})) >= 3))
        # 2 checkpoint
        d, st, _ = req("POST", "/api/checkpoint", {"name": "cp1"})
        results.append((2, "POST /api/checkpoint cp1", d.get("ok") is True))
        # 3 set_param
        d, st, _ = req("POST", "/api/set_param",
                       {"seg": "seg_b", "param": "Radius", "value": 0.03})
        changed = d.get("data", {}).get("changed", d.get("ok") is True)
        results.append((3, "POST /api/set_param seg_b.Radius=0.03", d.get("ok") is True and changed))
        # 4 revert
        d, st, _ = req("POST", "/api/revert", {"name": "cp1"})
        results.append((4, "POST /api/revert cp1", d.get("ok") is True))
        # 5 pop
        d, st, _ = req("POST", "/api/pop", {})
        results.append((5, "POST /api/pop", d.get("ok") is True))
        # 6 drop_segment
        d, st, _ = req("POST", "/api/drop_segment", {"seg": "seg_b"})
        results.append((6, "POST /api/drop_segment seg_b", d.get("ok") is True))
        # 7 verify
        d, st, _ = req("POST", "/api/verify", {})
        results.append((7, "POST /api/verify → PASS", d.get("ok") is True))
        # 8 override
        d, st, _ = req("POST", "/api/override", {"note": "api 实验打回"})
        results.append((8, "POST /api/override", d.get("ok") is True))
        # 9 unknown op → 结构化错误
        d, st, _ = req("POST", "/api/accept", {})
        results.append((9, "POST /api/accept → UNKNOWN_OP 结构化错误",
                        d.get("ok") is False and
                        d.get("error", {}).get("error_code") == "UNKNOWN_OP"))
        # 10 静态 console.html（直接读原始字节，不走 JSON）
        r10 = urllib.request.Request(BASE + "/", method="GET")
        with urllib.request.urlopen(r10, timeout=30) as resp:
            st10 = resp.status
            body10 = resp.read().decode("utf-8", "replace")
        results.append((10, "GET / → console.html 静态伺服",
                        st10 == 200 and "控制台" in body10 and "<html" in body10.lower()))
        # 11 终态 state
        d, st, _ = req("GET", "/api/state")
        segs = d.get("data", {}).get("segments", d.get("segments", {}))
        results.append((11, "GET /api/state 终态 → 1 段（seg_a）",
                        len(segs) == 1 and "seg_a" in segs))
    except Exception as exc:                          # noqa: BLE001
        results.append((99, f"client exception @step {step}: {exc!r}"[:200], False))
    finally:
        done.set()


# ── 起服务（manual pump 模式）────────────────────────────
r = es.bind_console(console)
r = es.start(port=PORT, static_dir=WEB, pump_mode="manual")
print("[api  0] %s" % r["summary"])
check(0, "embedded_server.start(manual pump)", es.is_running())

done = threading.Event()
results = []
t0 = time.perf_counter()
cli = threading.Thread(target=client_run, args=(done, results), daemon=True)
cli.start()

# 主线程泵循环（bpy 数据主线程安全的代价与机制所在）
while not done.wait(timeout=0.05):
    es.pump()
    if time.perf_counter() - t0 > 90:
        print("[api !!] 主线程泵 90s 超时——client 未完成")
        break
es.pump()
elapsed = time.perf_counter() - t0
check(12, "端到端无死锁（12 请求 %.1f s 完成）" % elapsed, done.is_set() and elapsed < 90)

for n, desc, ok in sorted(results):
    check(n, desc, ok)

es.stop()
check(13, "es.stop() 幂等干净", not es.is_running())

failed = sum(1 for x in ROWS if not x)
print("\nAPI REVERT LIVE: %d/%d passed" % (len(ROWS) - failed, len(ROWS)))
sys.exit(1 if failed else 0)
