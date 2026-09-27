// m9_web 无头自检：从 index.html 抽出 <script>，验证纯函数与演示数据。
// 跑法：node _selftest.mjs（R5 起 25 → 42 项：+M10-5 三级披露 / dagre 布局质量 / 优先级回归）
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) { console.error("FAIL: 未找到 <script>"); process.exit(1); }

const api = new Function(m[1] + "\n;return {layoutDag, dagSvg, summarize, DEMO,"
  + " kpiCards, overrideCurveSvg, resolveTheme, nextThemePref,"
  + " buildSegmentTree, countCrossings, stepDetailHtml};")();
const { layoutDag, dagSvg, summarize, DEMO,
        kpiCards, overrideCurveSvg, resolveTheme, nextThemePref,
        buildSegmentTree, countCrossings, stepDetailHtml } = api;

let failed = 0;
const ok = (c, msg) => { if (!c) { console.error("FAIL:", msg); failed++; }
                         else console.log("ok  :", msg); };

// 1. summarize
const s = summarize(DEMO);
ok(s.nSteps === 3 && s.nSegs === 3, `summarize：3 steps / 3 segs（got ${s.nSteps}/${s.nSegs}）`);
ok(s.mode === "INCREMENTAL", "mode = INCREMENTAL");
ok(s.dirty.length === 1 && s.dirty[0] === "S3_收尾", "S3_收尾 为唯一脏段");

// 2. layoutDag：分层与坐标
const L = layoutDag(DEMO);
ok(Object.keys(L.pos).length === 3, "3 个节点有坐标");
ok(L.pos["s1"].x < L.pos["s2"].x && L.pos["s2"].x < L.pos["s3"].x, "依赖在左、下游在右");
ok(L.width > 500 && L.height > 100, `画布尺寸合理 ${L.width}×${L.height}`);

// 3. dagSvg：结构完整
const svg = dagSvg(DEMO);
ok(svg.includes("<svg") && svg.includes("</svg>"), "SVG 闭合");
ok((svg.match(/class="node"/g) || []).length === 3, "3 个节点组");
ok((svg.match(/marker-end/g) || []).length === 2, "2 条依赖边");
ok(svg.includes("S2_把手"), "段落名入图");

// 4. state.json 与内置示例同 schema（R4：/1 与 /1.1 都兼容）
const st = JSON.parse(readFileSync(new URL("./state.json", import.meta.url), "utf8"));
ok(/^mug-console-state\/1(\.|$)/.test(st.schema),
   `state.json schema 兼容 /1 与 /1.1（got ${st.schema}）`);
ok(summarize(st).nSteps === 3, "state.json 可被 summarize 消费");
const svg2 = dagSvg(st);
ok((svg2.match(/class="node"/g) || []).length === 3, "state.json 渲染 3 节点");

// 5. M10-4 KPI 带（schema/1.1）
const cards = kpiCards(DEMO);
ok(cards.length === 3, "KPI 三卡");
ok(cards[0].num === "33.3%" && cards[0].cls === "ok",
   `override 率卡 33.3%/ok（got ${cards[0].num}/${cards[0].cls}）`);
ok(cards[1].num === "1" && cards[1].cls === "warn", "dirty 卡 1/warn");
ok(cards[2].num === "1" && cards[2].cls === "bad", "verify 失败卡 1/bad");
const cardsOld = kpiCards({schema:"mug-console-state/1", segments:{}, steps:[]});
ok(cardsOld.every(c => c.num === "—"),
   "向后兼容：/1 旧数据（无 kpis）三卡全 —");
const cardsZero = kpiCards({...DEMO, kpis:{...DEMO.kpis, override_rate:0,
  dirty_segments:0, verify_fails:0}});
ok(cardsZero[0].num === "0" && cardsZero[0].cls === "idle"
   && cardsZero[1].cls === "ok" && cardsZero[2].cls === "ok",
   "全零状态：override 0=idle（无摩擦警示），dirty/verify=ok");

// 6. M10-4 override 率曲线
const curve = overrideCurveSvg(DEMO);
ok(curve.includes("<svg") && curve.includes("<polyline") && curve.includes("</svg>"),
   "曲线 SVG 闭合且含折线");
ok((curve.match(/<circle/g) || []).length === 3, "3 个决策采样点");
const curveEmpty = overrideCurveSvg({schema:"mug-console-state/1"});
ok(curveEmpty.includes("暂无") && !curveEmpty.includes("<svg"),
   "空曲线占位文案（不渲染空 SVG）");
const c3 = DEMO.kpis.override_curve;
ok(c3[2].rate === Math.round((1/3)*10000)/10000, "曲线末点 = 1/3 累计率");

// 7. M10-6 主题三态纯函数
ok(nextThemePref("auto") === "light" && nextThemePref("light") === "dark"
   && nextThemePref("dark") === "auto", "主题循环 auto→light→dark→auto");
ok(resolveTheme("dark", false) === "dark" && resolveTheme("light", true) === "light"
   && resolveTheme("auto", true) === "dark" && resolveTheme("auto", false) === "light",
   "resolveTheme：手动优先，auto 跟随系统");

// 8. M10-5 渐进披露三级：buildSegmentTree（L1 卡源数据 / L2 阶段条）+ stepDetailHtml（L3）
const tree = buildSegmentTree(DEMO);
ok(tree.length === 3 && tree[0].name === "S1_杯体", "L1：三个段落卡（顺序保持）");
ok(tree.every(t => t.nSteps === 1), "L1：计数徽标数据源（每段步数）");
ok(tree[2].dirty === true && tree[0].dirty === false, "L1：dirty 标志透传");
const tStage = buildSegmentTree({
  segments: {"S1_blockout": {steps: ["a"]}},
  steps: [{id: "a", seg: "S1_blockout", deps: []}]});
ok(tStage[0].stages.blockout && tStage[0].stages.blockout.length === 1,
   "L2：stage 推断——段名尾词合法即用");
const tFallback = buildSegmentTree({
  segments: {"S9_杯体": {steps: ["x"]}},
  steps: [{id: "x", seg: "S9_杯体", deps: []}]});
ok(tFallback[0].stages.blockout && tFallback[0].stages.blockout.length === 1,
   "L2：stage 兜底——不合法尾词归 blockout");
const tExplicit = buildSegmentTree({
  segments: {"A": {steps: ["x", "y"]}},
  steps: [{id: "x", seg: "A", deps: [], stage: "blockout"},
          {id: "y", seg: "A", deps: [], stage: "detail"}]});
ok(tExplicit[0].stages.blockout.length === 1 && tExplicit[0].stages.detail.length === 1,
   "L2：显式 stage 字段优先于段名推断");

const dHtml = stepDetailHtml("s2", DEMO.steps[1]);
ok(dHtml.includes("<table>") && dHtml.includes("</table>") && dHtml.includes("</details>"),
   "L3：步详情表结构闭合");
ok(dHtml.includes("Handle_Ring_Radius") && dHtml.includes("Handle_Thickness"),
   "L3：参数行齐全（三元优先级 bug 回归——旧实现被静默吞掉）");
ok(dHtml.includes("假设</td><td>T1"), "L3：假设引用行在场");
const dHtmlNoRef = stepDetailHtml("s1", DEMO.steps[0]);
ok(dHtmlNoRef.includes("Body_Radius") && !dHtmlNoRef.includes("假设"),
   "L3：无假设步——参数保留且不含假设行");
ok(stepDetailHtml("ghost", undefined).includes("0 参数"), "L3：缺步防御（undefined → 空详情）");

// 9. M10-5 dagre 式布局质量（分层 + 重心排序 + 确定性）
ok(countCrossings(DEMO) === 0, "DEMO 链式零交叉");
const crossingCase = {segments: {}, steps: [
  {id: "A", seg: "X", deps: []}, {id: "B", seg: "X", deps: []},
  {id: "C", seg: "Y", deps: ["B"]}, {id: "D", seg: "Y", deps: ["A"]}]};
/* 朴素输入序 [C,D] 有 1 个交叉：A(0)→D(1) 与 B(1)→C(0)；
   重心排序后 D(重心 0) 排前 → A→D、B→C 平行，交叉 = 0 */
ok(countCrossings(crossingCase) === 0, "重心排序消解交叉（朴素序为 1）");
const Lc = layoutDag(crossingCase);
ok(Lc.cols[1][0].id === "D" && Lc.cols[1][1].id === "C", "层内序：D（重心 0）排前");
ok(JSON.stringify(layoutDag(crossingCase).pos) === JSON.stringify(Lc.pos),
   "布局确定性：两次结果逐坐标一致");
const L2 = layoutDag(DEMO);
ok(L2.cols.length === 3 && L2.cols[0][0].id === "s1"
   && L2.cols[2][0].id === "s3", "最长路径分层：s1→s2→s3 三层");
ok(L2.pos.s1.x === 30 && L2.pos.s2.x === 202 && L2.pos.s3.x === 374,
   "层距 172px 均匀（坐标口径不变）");

console.log(failed ? `\nSELFTEST FAIL (${failed})` : "\nSELFTEST PASS");
process.exit(failed ? 1 : 0);
