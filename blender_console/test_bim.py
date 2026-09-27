"""test_bim.py — M2-8 BIM 语义谓词单元测试（纯 Python，秒级）。

跑法：python test_bim.py
覆盖：三谓词正反例（工单 M2-8 验收口径"正例 + 反例各 1"逐谓词加码）：
  ① Pset 完备性（外墙缺 pset/None/空串拒；内墙不要求）
  ② 关系一致性（door/window 悬空 host 拒；存在引用过）
  ③ 材料层（层和≠壁厚拒 / 空层表拒 / 负层厚拒 / 有层无壁厚拒 / 键缺失跳过）
  结构错误（model 非 dict / 墙缺 id / door 缺 host）+ fail-fast 语义。
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from bim_predicates import (BIM_HOST_MISSING, BIM_LAYER_MISMATCH,  # noqa: E402
                            BIM_MODEL_INVALID, BIM_PSET_INCOMPLETE, check_bim)

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


def codes(model):
    return sorted(i["code"] for i in check_bim(model))


GOOD_WALL = {"id": "W1", "is_external": True, "thickness": 0.24,
             "psets": {"Pset_WallCommon": {"IsExternal": True}},
             "material_layers": [{"name": "brick", "thickness": 0.12},
                                 {"name": "insulation", "thickness": 0.12}]}
GOOD_MODEL = {"walls": [GOOD_WALL],
              "doors": [{"id": "D1", "host_wall": "W1"}],
              "windows": [{"id": "Win1", "host_wall": "W1"}]}

print("M2-8 BIM 谓词测试")

# 正例
check("①正例：完整模型全过", lambda: codes(GOOD_MODEL), [])

# ① Pset 完备性
check("①反例a：外墙缺 psets",
      lambda: BIM_PSET_INCOMPLETE in codes(
          {"walls": [{"id": "W1", "is_external": True}]}), True)
check("①反例b：IsExternal=None",
      lambda: BIM_PSET_INCOMPLETE in codes(
          {"walls": [{"id": "W1", "is_external": True,
                      "psets": {"Pset_WallCommon": {"IsExternal": None}}}]}), True)
check("①反例c：IsExternal=空串",
      lambda: BIM_PSET_INCOMPLETE in codes(
          {"walls": [{"id": "W1", "is_external": True,
                      "psets": {"Pset_WallCommon": {"IsExternal": "  "}}}]}), True)
check("①边界：内墙无 pset 不报",
      lambda: codes({"walls": [{"id": "W2", "is_external": False}]}), [])

# ② 关系一致性
check("②反例a：door 悬空 host",
      lambda: BIM_HOST_MISSING in codes(
          {"walls": [GOOD_WALL], "doors": [{"id": "D9", "host_wall": "W9"}]}), True)
check("②反例b：window 缺 host_wall",
      lambda: BIM_MODEL_INVALID in codes(
          {"walls": [GOOD_WALL], "windows": [{"id": "Win9"}]}), True)
check("②边界：无门窗模型合法", lambda: codes({"walls": [GOOD_WALL]}), [])

# ③ 材料层
def _wall(layers=None, thickness=0.24, keep_key=True):
    w = {"id": "W1", "is_external": True,
         "psets": {"Pset_WallCommon": {"IsExternal": True}}}
    if thickness is not None:
        w["thickness"] = thickness
    if keep_key:
        w["material_layers"] = layers
    return {"walls": [w]}

LAY = [{"name": "a", "thickness": 0.12}, {"name": "b", "thickness": 0.12}]
check("③反例a：层和 0.23 ≠ 壁厚 0.24",
      lambda: BIM_LAYER_MISMATCH in codes(
          _wall([{"name": "a", "thickness": 0.11},
                 {"name": "b", "thickness": 0.12}])), True)
check("③反例b：空层表 + 壁厚>0",
      lambda: BIM_LAYER_MISMATCH in codes(_wall([])), True)
check("③反例c：负层厚",
      lambda: BIM_LAYER_MISMATCH in codes(
          _wall([{"name": "a", "thickness": 0.3},
                 {"name": "b", "thickness": -0.06}])), True)
check("③反例d：有层表无壁厚",
      lambda: BIM_LAYER_MISMATCH in codes(_wall(LAY, thickness=None)), True)
check("③反例e：层厚缺失",
      lambda: BIM_LAYER_MISMATCH in codes(
          _wall([{"name": "a", "thickness": 0.24}, {"name": "b"}])), True)
check("③边界：material_layers 键缺失跳过",
      lambda: codes(_wall(keep_key=False)), [])
check("③精度：0.12+0.12 == 0.24（float32 噪声容差内）",
      lambda: codes(_wall(LAY)), [])

# 结构错误 + fail-fast
check("结构a：model 非 dict",
      lambda: codes([1, 2]), [BIM_MODEL_INVALID])
check("结构b：墙缺 id",
      lambda: BIM_MODEL_INVALID in codes({"walls": [{"is_external": True}]}), True)
check("结构c：INVALID 时 fail-fast（结构坏不再出语义错）",
      lambda: len(codes({"walls": "not-a-list",
                         "doors": [{"id": "D", "host_wall": "X"}]})), 1)
check("收口：BIM_PREDICATE_CODES 四码齐",
      lambda: sorted([BIM_MODEL_INVALID, BIM_PSET_INCOMPLETE,
                      BIM_HOST_MISSING, BIM_LAYER_MISMATCH]),
      sorted(["BIM_MODEL_INVALID", "BIM_PSET_INCOMPLETE",
              "BIM_HOST_MISSING", "BIM_LAYER_MISMATCH"]))

n_ok = sum(1 for r in ROWS if r["ok"])
print(f"\nM2-8 BIM TEST: {n_ok}/{len(ROWS)} passed")
if n_ok != len(ROWS):
    sys.exit(1)
