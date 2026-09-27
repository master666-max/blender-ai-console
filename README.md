**English** | [简体中文](README.zh-CN.md)

<div align="center">

# Blender AI Modeling Console

**LLMs should declare models, not write scripts.**

*A plan–compile–verify console for Blender: the LLM emits plan-JSON, deterministic compilers land it in Geometry Nodes / materials / cameras / rigs, and a machine verifier gates every step.*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Blender](https://img.shields.io/badge/Blender-5.2-orange)](https://www.blender.org/)
[![Runtime](https://img.shields.io/badge/runtime-bpy-blue)](https://docs.blender.org/api/current/)
[![Tests](https://img.shields.io/badge/tests-29_suites_%7E688_assertions-brightgreen)](#verification-status)
[![Stars](https://img.shields.io/github/stars/master666-max/blender-ai-console?style=flat&logo=github)](https://github.com/master666-max/blender-ai-console/stargazers)

[Architecture](#architecture) · [Quick Start](#quick-start) · [Repo Layout](#repo-layout) · [Verification Status](#verification-status) · [Roadmap](#roadmap)

</div>

---

## Architecture

```mermaid
flowchart LR
    subgraph INTENT [Conversation]
        U[User intent] --> L[LLM emits plan-JSON]
    end
    subgraph COMPILE [Deterministic compilation]
        P[Schema + whitelist validation] --> C[M4 compilers<br/>GN · material · rig · camera]
        C --> B[("Blender 5.2 bpy")]
    end
    subgraph VERIFY [Machine verification]
        V[M2 predicate family<br/>M3 render diff + perceptual hash]
    end
    L --> P
    B --> V
    V -- "structured error codes → self-repair / escalate" --> P
    V -- "pass" --> OK["commit · present · rollback anchor"]
    style INTENT fill:#e8f0fe,stroke:#4285f4
    style COMPILE fill:#e6f4ea,stroke:#34a853
    style VERIFY fill:#fef7e0,stroke:#f9ab00
```

Ten modules, each with its own acceptance suite: **M1** data (FlowDAG / WAL + hash chain / step replay), **M2** verification (structure / render / BIM predicates + tiered gates), **M3** rendering (same-camera diff), **M4** compilation (GN / materials incl. procedural / Rigify rigs), **M5** interaction (A/B dual-compile), **M6** experience (preference learning + EMD offline calibration), **M7** director mode, **M8** fusion & release engineering, **M9** conversational frontend, **M10** static web console.

## Quick Start

```bash
git clone https://github.com/master666-max/blender-ai-console.git
cd blender-ai-console

# Live acceptance (needs Blender 5.2's bundled Python / bpy)
python blender_console/m8r4_live.py     # material & presentation suite  20/20
python blender_console/m412b_live.py    # character pipeline integration 17/17

# Web console self-test (no Blender required)
cd m9_web && node _selftest.mjs         # 42/42
```

Pure-Python unit tests (no bpy): `python blender_console/test_upstream_store.py`

All paths in the codebase are derived relative to the repo root — no machine-specific absolute paths.

## Repo Layout

| Path | Content |
|---|---|
| [`blender_console/`](blender_console/) | Console core + 29 `_live.py` machine acceptance suites |
| [`m8_bridge/gn_deploy/`](m8_bridge/gn_deploy/) | Deployment payload (55 py, diff-checked against mainline) |
| [`m9_web/`](m9_web/) | Static web console + flicker diff viewer |
| [`release/`](release/) | Release manifest (147-file five-layer inventory) |
| Work-order / handover / planning ledgers | Kept out of the repo — decision records live outside the codebase |

## Verification Status

M1–M10 mainline green; R7 deep-water AI-actionable items closed. Regression baseline: **29 suites ≈ 688 assertions**.

<details>
<summary><b>Suite highlights (click to expand)</b></summary>

| Suite | Covers |
|---|---|
| `m8r4_live` 20/20 | Procedural wood compile / replay idempotency / structured rejections / presentation rig + 0-drift cross-check |
| `exp5_live` 6/6 | Vertex fingerprint A/B: Gear FastCDC three-way, verdict "fall back to geometric fingerprints" |
| `m412b_live` 17/17 | Character pipeline console integration |
| `m412_live` 6/6 | Rig compiler, deformation quality IoU(128³) = 1.0 |
| `test_bim` 19/19 | BIM predicates (data-level) |
| `exp7_live` 3/3 | Process-gate three-way comparison (left-shift effect) |
| `m6_live` 31/31 | AB → preference learning / override write-back / diversity gate |
| Remaining 20+ suites | M1-M5 / M7 / M9 / M10 regression & smoke |

</details>

## Roadmap

- [x] M1–M10 mainline + release inversion (whl 2.1.0-gn pinned)
- [x] R7 deep water: character pipeline (incl. console integration) / EMD calibration / BIM predicates / material assets / vertex-fingerprint verdict
- [ ] M9-5 flicker vs side-by-side preference A/B (flicker.html ready; needs human experiment)
- [ ] Long-term: annotation back-reference · audio channel · HAMT · ARKit-52 blendshapes · multi-rig coexistence

## Acknowledgments

This project stands on the shoulders of:

- **[mcp-for-blender](https://github.com/ahujasid/blender-mcp)** (MIT, © 2025 Siddharth Ahuja) — the transport layer (sandbox, telemetry, consent and config modules) is vendored under [`m8_bridge/brickfly_mcp_src/`](m8_bridge/brickfly_mcp_src/) and extended with 8 GN tool bindings; its original license notice is preserved in that directory's [LICENSE](m8_bridge/brickfly_mcp_src/LICENSE).
- **[Blender](https://www.blender.org/)** and the bpy community — the substrate everything runs on.

## License

<div align="center">

[MIT](LICENSE) © 2026 · *Treat every pixel with engineering discipline.*

</div>
