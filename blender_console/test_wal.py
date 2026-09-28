"""test_wal.py — 批次② WAL 语义修复单元测试（A1/A2/R5/R6 + SnapshotStore）。

跑法：python test_wal.py
对应：零损失交接文档 §7-3/§7-4 + 技能4 A1/A2 + 技能1 R5/R6。
红→绿：红阶段 SnapshotStore 未实现/compact 旧语义（撞名+无守卫+返回 int），
修复后全绿。R5 的 fsync 为系统调用不可纯 Python 断言——以实现 + 注释声明取舍，
本文件 [7] 段只测「落盘即时可见」这一可断言面（回归护栏）。
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from m1_core import SnapshotStore, WALLog  # noqa: E402  ← 红阶段 SnapshotStore 缺失

ROWS: list[dict] = []


def check(name, fn, expect=True):
    try:
        val = fn()
        if val != expect:
            raise AssertionError(f"期望 {expect!r}，实得 {val!r}")
        ROWS.append({"case": name, "ok": True})
        print(f"  PASS  {name}")
    except Exception as exc:  # noqa: BLE001
        ROWS.append({"case": name, "ok": False, "detail": repr(exc)[:160]})
        print(f"  FAIL  {name}  {exc!r}")


tmp = Path(tempfile.mkdtemp())

# ── [1] A2：kind 命名空间拆分（"checkpoint" 不再是 compact 截断边界）──
print("[1] A2 kind 拆分")
p1 = tmp / "wal1.jsonl"
w1 = WALLog(p1)
w1.append("param", {"i": 0})
w1.append("checkpoint", {"name": "cp1"})   # console 回退点（旧撞名 kind）
w1.append("param", {"i": 1})
r1 = w1.compact()
check("checkpoint 不再触发 compact 截断", lambda: r1["dropped"], 0)
check("事件全保留", lambda: len(w1.replay()), 3)

# ── [2] A1 守卫：边界行 payload 缺 snapshot_ref → 拒绝压缩 ──
print("\n[2] A1 快照引用守卫")
p2 = tmp / "wal2.jsonl"
w2 = WALLog(p2)
w2.append("param", {"i": 0})
w2.append("compaction_barrier", {"name": "b1"})   # 缺 snapshot_ref
w2.append("param", {"i": 1})
r2 = w2.compact()
check("边界行缺 snapshot_ref → 拒绝压缩", lambda: r2["dropped"], 0)
check("拒绝时事件不丢", lambda: len(w2.replay()), 3)

# ── [3] A1 绿路径：有效快照引用 + resolver 确认 → 正常压缩 ──
print("\n[3] A1 正常压缩路径")
store = SnapshotStore(tmp / "snapshots")
ref = store.put({"mesh": "snap-data-1"})
p3 = tmp / "wal3.jsonl"
w3 = WALLog(p3)
w3.append("param", {"i": 0})
w3.append("compaction_barrier", {"name": "b1", "snapshot_ref": ref})
w3.append("param", {"i": 1})
r3 = w3.compact(snapshot_resolver=store.has)
check("带有效快照引用 → 正常压缩", lambda: r3["dropped"], 1)
check("压缩后保留 barrier 之后", lambda: len(w3.replay()), 2)
check("压缩后链自洽", lambda: w3.verify(), True)

# ── [4] A1 深守卫：snapshot_ref 不可解析（快照文件缺失）→ 拒绝 ──
print("\n[4] A1 快照缺失守卫")
p4 = tmp / "wal4.jsonl"
w4 = WALLog(p4)
w4.append("param", {"i": 0})
w4.append("compaction_barrier", {"name": "b1", "snapshot_ref": "deadbeefdeadbeef"})
w4.append("param", {"i": 1})
r4 = w4.compact(snapshot_resolver=lambda r: False)
check("快照引用不可解析 → 拒绝压缩", lambda: r4["dropped"], 0)
check("拒绝时全量保留", lambda: len(w4.replay()), 3)

# ── [5] R6：compact 返回新旧 hash 映射 ──
print("\n[5] R6 hash 映射")
p5 = tmp / "wal5.jsonl"
w5 = WALLog(p5)
for i in range(4):
    w5.append("param", {"i": i})
ref5 = store.put({"i": "cp"})
w5.append("compaction_barrier", {"snapshot_ref": ref5})
w5.append("param", {"i": 99})
before = [r["hash"] for r in w5.replay()]
r5 = w5.compact(snapshot_resolver=store.has)
check("返回 dict 含 dropped/hash_map",
      lambda: isinstance(r5, dict) and "hash_map" in r5, True)
check("hash_map 键覆盖压缩前全部行", lambda: set(r5["hash_map"]) == set(before), True)
check("映射值均为 64 位 hash",
      lambda: all(isinstance(v, str) and len(v) == 64 for v in r5["hash_map"].values()),
      True)

# ── [6] SnapshotStore：内容寻址落盘 ──
print("\n[6] SnapshotStore 内容寻址")
s1 = store.put({"a": 1})
check("put→ref 可 has", lambda: store.has(s1), True)
check("get 还原原对象", lambda: store.get(s1), {"a": 1})
check("同内容同 ref（内容寻址幂等）", lambda: store.put({"a": 1}), s1)
check("落盘文件存在", lambda: (tmp / "snapshots" / f"{s1}.json").exists(), True)
s2 = store.put({"a": 2})
check("异内容异 ref", lambda: s2 != s1, True)
check("未知 ref → has False", lambda: store.has("ffffffffffffffff"), False)

# ── [7] R5 可断言面：append 落盘即时可见（fsync 本体靠实现+注释，见 m1_core）──
print("\n[7] append 落盘即时性（R5 回归护栏）")
p7 = tmp / "wal7.jsonl"
w7 = WALLog(p7)
w7.append("x", {"a": 1})
last = json.loads(p7.read_text(encoding="utf-8").splitlines()[-1])
check("append 后磁盘末行即新事件", lambda: last["payload"], {"a": 1})

failed = [r for r in ROWS if not r["ok"]]
print(f"\nWAL UNIT: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
for f in failed:
    print("  FAILED:", f["case"], "->", f.get("detail"))
sys.exit(1 if failed else 0)
