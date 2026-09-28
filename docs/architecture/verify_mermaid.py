#!/usr/bin/env python3
"""verify_mermaid.py — 从 architecture_diagrams.md 提取 mermaid 块生成渲染测试页"""
import re, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
md = (HERE / "architecture_diagrams.md").read_text(encoding="utf-8")
blocks = re.findall(r"```mermaid\n(.*?)```", md, re.S)
print("extracted %d mermaid blocks" % len(blocks))

html = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<style>body{font-family:sans-serif;background:#fff;padding:16px}
.err{color:#c00;font-weight:bold}
.ok{color:#080}
.diagram{border:1px solid #ccc;margin:12px 0;padding:8px}</style>
</head><body>
<div id="report">rendering...</div>
<div id="out"></div>
<script>
const BLOCKS = %s;
const REPORT = [];
mermaid.initialize({startOnLoad: false, securityLevel: 'loose'});
(async () => {
  const out = document.getElementById('out');
  for (let i = 0; i < BLOCKS.length; i++) {
    const div = document.createElement('div');
    div.className = 'diagram';
    div.id = 'd' + i;
    out.appendChild(div);
    try {
      const {svg} = await mermaid.render('m' + i, BLOCKS[i]);
      div.innerHTML = svg;
      REPORT.push({block: i, ok: true});
    } catch (e) {
      div.innerHTML = '<span class="err">SYNTAX ERROR: ' + String(e).slice(0, 200) + '</span>';
      REPORT.push({block: i, ok: false, err: String(e).slice(0, 200)});
    }
  }
  document.getElementById('report').textContent = 'RESULT:' + JSON.stringify(REPORT);
  document.title = 'MERMAID_VERIFY_DONE';
})();
</script></body></html>""" % json.dumps(blocks, ensure_ascii=False)

out_html = HERE / "verify_mermaid.html"
out_html.write_text(html, encoding="utf-8")
print("wrote", out_html)
