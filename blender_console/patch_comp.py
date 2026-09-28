# patch_comp.py — compositor 段 try/except 防护（写文件方式避 bash 转义）
p = 'konbini_build.py'
src = open(p, encoding='utf-8').read()
old = """    # compositor 辉光（动画夜景的灵魂）
    sc.use_nodes = True
    nt = sc.node_tree
    nt.nodes.clear()
    rl = nt.nodes.new("CompositorNodeRLayers")
    gl = nt.nodes.new("CompositorNodeGlare")
    gl.glare_type = 'BLOOM'
    gl.threshold = 0.9
    gl.size = 8
    gl.mix = -0.6
    comp = nt.nodes.new("CompositorNodeComposite")
    nt.links.new(rl.outputs["Image"], gl.inputs["Image"])
    nt.links.new(gl.outputs["Image"], comp.inputs["Image"])"""
new = """    # compositor 辉光（5.2 API 兼容尝试——失败不阻塞帧渲染）
    try:
        sc.use_nodes = True
        nt = sc.node_tree
        nt.nodes.clear()
        rl = nt.nodes.new("CompositorNodeRLayers")
        gl = nt.nodes.new("CompositorNodeGlare")
        gl.glare_type = 'BLOOM'
        gl.threshold = 0.9
        gl.size = 8
        gl.mix = -0.6
        comp = nt.nodes.new("CompositorNodeComposite")
        nt.links.new(rl.outputs["Image"], gl.inputs["Image"])
        nt.links.new(gl.outputs["Image"], comp.inputs["Image"])
        print("[konbini] compositor bloom OK")
    except Exception as _ce:
        print("[konbini] compositor skip:", repr(_ce)[:120])"""
assert old in src, 'comp anchor'
src = src.replace(old, new)
open(p, 'w', encoding='utf-8', newline='\n').write(src)
import ast
ast.parse(src)
print('compositor guarded')
