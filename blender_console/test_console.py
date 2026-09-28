"""test_console.py — console.py 结构契约测试（D1 缺口补齐 · 批次④）。

跑法：python test_console.py
背景：console.py（~1000 行，全链入口）是 import bpy 的真机依赖文件，离线不可
import——技能3 D1 判定「零直接测试，交付前第一优先级」。本套件用 AST 解析
（不执行模块体、零 bpy 环境要求）锁住**结构契约**：

  * 语法完整性（ast.parse 全文）
  * Console 公开方法清单（checkpoint/revert/compile/set_param/…）
  * WAL kind 契约：restore_point 在场（A1/A2 修复）+ 旧 "checkpoint" kind 零残留
  * checkpoint payload 携带 snapshot_ref（A1 回归护栏）
  * import 契约：SnapshotStore 从 m1_core 导入
  * ConsoleResult 结果形态字段

边界声明（诚实边界）：行为正确性（bpy mesh 操作、编译链）仍走真机 _live 验收，
本套件只锁「不改就会静默破坏 A1/A2 修复」的结构面。
"""
import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = (HERE / "console.py").read_text(encoding="utf-8")

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


tree = ast.parse(SRC)          # [1] 语法完整性——挂了后面全无意义
cls = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
console_cls = cls.get("Console")
result_cls = cls.get("ConsoleResult")


def methods_of(node: ast.ClassDef) -> set[str]:
    return {m.name for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}


def src_of(node: ast.ClassDef, meth: str) -> str:
    for m in node.body:
        if isinstance(m, ast.FunctionDef) and m.name == meth:
            return ast.get_source_segment(SRC, m) or ""
    return ""


# ── [1] 语法与顶层结构 ────────────────────────────────────────
print("[1] 语法与顶层结构")
check("console.py 全文可 AST 解析", lambda: isinstance(tree, ast.Module), True)
check("Console 类在场", lambda: console_cls is not None, True)
check("ConsoleResult 类在场", lambda: result_cls is not None, True)

# ── [2] Console 公开方法清单（D1：入口契约锁面）─────────────
print("\n[2] Console 方法清单")
REQUIRED = {"compile", "recompile", "set_param", "verify", "checkpoint",
            "revert_to_checkpoint", "pop_layer", "drop_segment", "drop_part",
            "impact_preview", "render_diff", "ab_prepare", "ab_commit",
            "export_state"}
ms = methods_of(console_cls) if console_cls else set()
check("9+ 公开方法在场", lambda: REQUIRED <= ms, True)
check("checkpoint 方法在场（M3 回退层）", lambda: "checkpoint" in ms, True)
check("revert_to_checkpoint 在场", lambda: "revert_to_checkpoint" in ms, True)

# ── [3] WAL kind 契约（A2 回归护栏）──────────────────────────
print("\n[3] WAL kind 契约")
check('回退点 kind = "restore_point"', lambda: 'wal.append("restore_point"' in SRC, True)
check('旧 "checkpoint" kind 零残留', lambda: 'wal.append("checkpoint"' in SRC, False)
kinds = set()
for n in ast.walk(tree):
    if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "append" and isinstance(n.func.value, ast.Attribute)
            and n.func.value.attr == "wal" and n.args
            and isinstance(n.args[0], ast.Constant)):
        kinds.add(n.args[0].value)
check("WAL kind 字符串字面量 ≥ 8 类", lambda: len(kinds) >= 8, True)

# ── [4] A1 回归护栏：checkpoint payload 携快照引用 ───────────
print("\n[4] A1 快照引用护栏")
cp_src = src_of(console_cls, "checkpoint") if console_cls else ""
check("checkpoint 方法带 snapshot_ref", lambda: "snapshot_ref" in cp_src, True)
check("checkpoint 走 snapshots.put", lambda: "self.snapshots.put(" in cp_src, True)
check("__init__ 接线 snapshots", lambda: "self.snapshots = SnapshotStore(" in SRC, True)
check("import 契约：SnapshotStore ← m1_core",
      lambda: "SnapshotStore" in SRC.split("from m1_core import")[1][:200], True)

# ── [5] ConsoleResult 形态 ───────────────────────────────────
print("\n[5] ConsoleResult 形态")
res_fields = ({s.target.id for s in result_cls.body
               if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)}
              if result_cls else set())
def _is_dc_dec(d):
    """装饰器形态兼容：@dataclass（Name）与 @dataclass(frozen=True)（Call）。"""
    if isinstance(d, ast.Name):
        return d.id == "dataclass"
    return (isinstance(d, ast.Call) and isinstance(d.func, ast.Name)
            and d.func.id == "dataclass")

check("ConsoleResult 是 dataclass 装饰（Name/Call 双形态兼容）",
      lambda: result_cls is not None
      and any(_is_dc_dec(d) for d in result_cls.decorator_list), True)
check("frozen=True（结果不可变——L50 实锤 @dataclass(frozen=True)）",
      lambda: result_cls is not None and any(
          isinstance(d, ast.Call) and any(
              k.arg == "frozen" and isinstance(k.value, ast.Constant)
              and k.value.value is True for k in d.keywords)
          for d in result_cls.decorator_list), True)
check("结果字段含 action/ok/data", lambda: {"action", "ok", "data"} <= res_fields, True)

failed = [r for r in ROWS if not r["ok"]]
print(f"\nCONSOLE STRUCT UNIT: {len(ROWS) - len(failed)}/{len(ROWS)} passed")
for f in failed:
    print("  FAILED:", f["case"], "->", f.get("detail"))
sys.exit(1 if failed else 0)
