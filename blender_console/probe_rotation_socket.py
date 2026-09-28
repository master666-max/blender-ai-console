"""probe_rotation_socket.py — 探明 Blender 5.2 GeometryNodeTransform 的 Rotation socket 形态"""
import bpy

bpy.ops.wm.read_factory_settings(use_empty=True)
tree = bpy.data.node_groups.new("probe", "GeometryNodeTree")
tree.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
tree.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
tin = tree.nodes.new("NodeGroupInput")
tout = tree.nodes.new("NodeGroupOutput")
tf = tree.nodes.new("GeometryNodeTransform")
tree.links.new(tin.outputs[0], tf.inputs["Geometry"])
tree.links.new(tf.outputs["Geometry"], tout.inputs[0])

rot = tf.inputs["Rotation"]
print("socket name:", rot.name)
print("socket type:", rot.type)
print("socket bl_idname:", rot.bl_idname)
dv = rot.default_value
print("default_value type:", type(dv).__name__)
try:
    print("len:", len(dv), "values:", list(dv))
except Exception as e:
    print("not iterable:", e)

# 依次尝试赋值形态
for label, val in [("euler3_rad", (0.7853981633974483, 0.0, 0.0)),
                   ("quat4", (0.7071067811865476, 0.7071067811865476, 0.0, 0.0))]:
    try:
        rot.default_value = val
        print(f"assign {label}: OK ->", list(rot.default_value))
    except Exception as e:
        print(f"assign {label}: FAIL ->", repr(e)[:120])

# RotateEuler 节点是否存在
try:
    n = tree.nodes.new("FunctionNodeRotateEuler")
    print("FunctionNodeRotateEuler EXISTS; inputs:", [i.name for i in n.inputs])
except Exception as e:
    print("FunctionNodeRotateEuler missing:", repr(e)[:100])
