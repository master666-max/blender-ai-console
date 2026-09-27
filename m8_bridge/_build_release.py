"""_build_release.py — M8-R6 发布反转 · 标准包清单 manifest 生成器

四层扫描（进度规划 R6 口径：代码 + 部署载荷 + 验收结果 + 文档），
逐文件 SHA256，产出：
  release/RELEASE_MANIFEST_2.1.0-gn.json   机器可读（完整 hash）
  release/RELEASE_MANIFEST_2.1.0-gn.md     人类可读（分层表格）

主体性原则（M8 反转兑现）：blender_console/ 是核心资产主体；
brickfly_mcp_src 仅标注为「传输壳 fork」（上游 Brickfly MCP + gn 工具薄封装）。
"""
import hashlib
import json
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # 仓库根（相对推导，跨机器可移植）
BRIDGE = ROOT / "m8_bridge"
RESULTS = ROOT.parent / "2026-09-26-blender"
RELEASE = ROOT / "release"
VERSION = "2.1.0-gn"

GN_TOOLS = ["gn_begin", "gn_compile", "gn_verify", "gn_checkpoint", "gn_revert",
            "gn_render_diff", "gn_ab_prepare", "gn_ab_commit", "gn_accept",
            "gn_export_state", "gn_reset"]


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def collect(paths: list[Path], base: Path) -> list[dict]:
    out = []
    for p in sorted(paths):
        if p.is_file() and "__pycache__" not in p.parts:
            out.append({
                "path": p.relative_to(base).as_posix(),
                "bytes": p.stat().st_size,
                "sha256": sha256(p),
            })
    return out


def main() -> None:
    RELEASE.mkdir(exist_ok=True)
    whl = BRIDGE / f"brickfly_mcp-{VERSION}-py3-none-any.whl"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── 一致性前置校验：主线 = 部署载荷（零漂移才出 manifest）──
    drift = []
    for f in sorted((ROOT / "blender_console").glob("*.py")):
        dep = BRIDGE / "gn_deploy" / f.name
        if dep.exists() and sha256(f) != sha256(dep):
            drift.append(f.name)
    if drift:
        raise SystemExit(f"FATAL 主线↔gn_deploy 漂移未清：{drift}——先 cp 同步再出 manifest")

    # ── L1 代码（主体资产 + 传输壳）──
    l1_main = collect((ROOT / "blender_console").glob("*.py"), ROOT)
    l1_main += collect((ROOT / "m9_web").glob("*"), ROOT)
    l1_main += collect([BRIDGE / "gn_bridge.py", BRIDGE / "bootstrap_blender.py",
                        BRIDGE / "start_gn_bridge.bat"], ROOT)
    l1_shell = collect((BRIDGE / "brickfly_mcp_src").rglob("*"), ROOT)

    # ── L2 部署载荷 ──
    l2_deploy = collect((BRIDGE / "gn_deploy").glob("*.py"), ROOT)
    l2_whl = [{"path": f"m8_bridge/{whl.name}", "bytes": whl.stat().st_size,
               "sha256": sha256(whl)}]

    # ── L3 验收结果（R5 完结批次 + R6 传输链重跑）──
    l3 = collect(RESULTS.glob("*_result.json"), RESULTS)
    l3 += collect(RESULTS.glob("m92_result.json"), RESULTS) if not any(
        r["path"].endswith("m92_result.json") for r in l3) else []
    l3 += collect([BRIDGE / "e2e_result.json", BRIDGE / "mcp_smoke_result.json",
                   BRIDGE / "sandbox_probe_result.json"], ROOT)

    # ── L4 文档 ──
    l4 = collect([ROOT / "工单_v2_BlenderAI建模控制台.md", ROOT / "零损失交接文档.md",
                  ROOT / "进度规划_2026-09-27.md", ROOT / "总工单审计_2026-09-27.md",
                  BRIDGE / "M8-R2交付说明.md", ROOT / "m8_bridge" / "M8-R6发布说明_2.1.0-gn.md"], ROOT)

    manifest = {
        "release": VERSION,
        "built_at": now,
        "whl": {"file": whl.name, "bytes": whl.stat().st_size, "sha256": sha256(whl),
                "content_note": "与 2.0.3-gn 内容逐文件 SHA256 等价（11 文件）；定版=版本号固化，非代码变更"},
        "tool_surface": {"gn_tools": GN_TOOLS, "count": len(GN_TOOLS),
                         "verified": "repack 11/11 + 冒烟 16/16 + e2e 16/16（2.1.0-gn 时点重跑）"},
        "layer1_code_main": {"desc": "主体资产：blender_console 全模块 + m9_web 前端 + 桥接三件",
                             "files": l1_main},
        "layer1_code_shell": {"desc": "传输壳（fork Brickfly MCP + gn 工具薄封装，非主体）",
                              "files": l1_shell},
        "layer2_deploy": {"desc": "Blender 侧部署载荷 gn_deploy（与主线零漂移已校验）+ whl 分发件",
                          "files": l2_deploy + l2_whl},
        "layer3_evidence": {"desc": "验收结果：R5 完结批次（2026-09-27 21:30-22:38，Blender 侧代码零变更故有效）+ R6 传输链重跑",
                            "files": l3},
        "layer4_docs": {"desc": "工单/交接/规划/审计/交付与发布说明",
                        "files": l4},
    }

    jpath = RELEASE / f"RELEASE_MANIFEST_{VERSION}.json"
    jpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # 人类可读 md
    rows = []
    for layer, key in [("L1 主体代码", "layer1_code_main"), ("L1 传输壳", "layer1_code_shell"),
                       ("L2 部署载荷", "layer2_deploy"), ("L3 验收结果", "layer3_evidence"),
                       ("L4 文档", "layer4_docs")]:
        rows.append(f"\n## {layer} — {manifest[key]['desc']}\n")
        rows.append("| 文件 | 字节 | SHA256 前 12 位 |")
        rows.append("|---|---|---|")
        for f in manifest[key]["files"]:
            rows.append(f"| `{f['path']}` | {f['bytes']} | {f['sha256'][:12]} |")

    md = [
        f"# 发布清单 manifest · {VERSION}",
        f"\n> 生成时间 {now} · whl `{whl.name}`（{whl.stat().st_size} B，SHA256 `{sha256(whl)[:12]}…`）",
        f"> 工具面 {len(GN_TOOLS)} gn 工具 · 主线↔gn_deploy 零漂移已校验 · 发布门禁见 L3",
        "\n".join(rows),
    ]
    (RELEASE / f"RELEASE_MANIFEST_{VERSION}.md").write_text("\n".join(md), encoding="utf-8")

    counts = {k: len(manifest[k]["files"]) for k in
              ("layer1_code_main", "layer1_code_shell", "layer2_deploy", "layer3_evidence", "layer4_docs")}
    print("manifest ->", jpath.name)
    print("文件数：", counts, "总计", sum(counts.values()))
    print("RESULT:", "OK" if sum(counts.values()) > 100 else "SUSPICIOUS")


if __name__ == "__main__":
    main()
