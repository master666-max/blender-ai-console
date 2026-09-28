"""bootstrap_blender.py — M8-R2 端到端验证 · Blender 侧引导（后台进程）

职责：factory 空场景 → 注册 fork 插件（属性/类/能力自报）→ 建 gn 测试物体 →
起 BlenderMCPServer（TCP 9876）→ 保活循环（等待客户端 TCP 直连全链测试）。
"""
import importlib.util
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent          # m8_bridge/
GN_DEPLOY = HERE / "gn_deploy"
FORK = HERE / "brickfly_mcp_src"
os.environ["GN_DEPLOY_ROOT"] = str(GN_DEPLOY)   # addon handlers 的部署加载器用
sys.path.insert(0, str(GN_DEPLOY))
sys.path.insert(0, str(FORK))

import bpy  # noqa: E402

bpy.ops.wm.read_factory_settings(use_empty=True)

# 注册 fork 插件（Scene 属性 + 类 + handlers 的宿主）
spec = importlib.util.spec_from_file_location(
    "gn_fork_addon", FORK / "brickfly_mcp" / "bundled" / "addon.py")
addon = importlib.util.module_from_spec(spec)
sys.modules["gn_fork_addon"] = addon
spec.loader.exec_module(addon)
addon.register()

# gn 测试物体（gn_bridge.begin 的附着目标）
bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.active_object
obj.name = "Mug"
obj.data = bpy.data.meshes.new("Mug_Base")

# 起 TCP 服务（handlers 含 9 个 gn_* 工具）
server = addon.BlenderMCPServer("localhost", 9876)
server.start()

print("BOOTSTRAP-READY", flush=True)
print(f"gn_deploy={GN_DEPLOY}", flush=True)

# M8-R2b（fork 改动）：上游命令队列靠 Blender 主线程 timer drain，-b 下 timers 不跑
# （这才是上游拒绝 background 的技术根因）。我们的保活主线程**手动驱动 drain**——
# handlers 在 -b 下已被 8 套离线测试证明可用，drain 交给本循环即可。
print("drain loop active", flush=True)
while True:
    try:
        server._drain_command_queue()
    except Exception as e:                       # noqa: BLE001
        print(f"drain error: {e}", flush=True)
    time.sleep(0.3)
