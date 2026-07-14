# -*- coding: utf-8 -*-
"""
未竟之书初章·遇见 — 游戏引擎 (DLC v2.0.0)
===========================================
基于 DLC Protocol v1.0.0 框架。DLC 管状态/数值/叙事，engine.py 管场景/谜题/剧情。

公开 API (7个函数):
  start_game()    → 初始化游戏状态
  handle_message(msg) → 处理玩家输入
  get_status()    → 返回当前状态摘要
  reset_game()    → 重置游戏
  logout_game()   → 保存并退出
  save_state()    → 存档到磁盘
  load_state()    → 读档
  clear_state()   → 清除存档
"""

import json
import os
import random
import sys
import copy
from pathlib import Path

# ─── 确保 dlc/ 在导入路径中 ───────────────────────────────
BASE_DIR = Path(__file__).parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

CARD_DIR = BASE_DIR / "cards" / "weijingzhishu"
CONTENT_DIR = BASE_DIR / "content"
MEMORY_DIR = BASE_DIR / "MEMORY"

# ─── DLC 框架导入 ─────────────────────────────────────────
from dlc import (
    CardRuntimeContext, EntityEngine, EntityState,
    apply_modifier, calc_delta, clamp_channel,
    check_thresholds, render_event, render_events,
    StateManager,
    CommandLoader, CommandSet, match_command, execute_command, CommandResult,
    record_chat,
)

# ─── 运行时上下文 ─────────────────────────────────────────
ctx = CardRuntimeContext(str(CARD_DIR))
engine = EntityEngine(ctx.state_dir)
state_mgr = StateManager(ctx)
cmd_loader = CommandLoader(str(CARD_DIR / "interaction"))
cmd_set = cmd_loader.load()
tick = 0

# ─── 配置引用 ─────────────────────────────────────────────
_entities_cfg = ctx.entities.get("entities", {})
_modifiers_cfg = ctx.modifiers.get("modifiers", {})
_thresholds_cfg = ctx.thresholds.get("thresholds", {})
_narratives_cfg = ctx.narratives

# ─── 叙事格式兼容 ────────────────────────────────────────
# v1.0.6 的 events 使用 pipeline 格式（range/cond/rand ops），
# 但 DLC render_event 只支持 texts 格式。
# 解决方案：将 pipeline events 注入 command_assembly，
# 用 render_command_narrative 渲染。
def _patch_narratives_for_pipeline():
    """将 events.*.pipeline 迁移到 command_assembly.{event_id}，
    并从 events 中移除（render_event 不支持 pipeline 格式）。"""
    events = _narratives_cfg.get("events", {})
    assembly = _narratives_cfg.setdefault("command_assembly", {})
    to_remove = []
    for event_id, ev_cfg in list(events.items()):
        if "pipeline" in ev_cfg:
            if event_id not in assembly:
                assembly[event_id] = ev_cfg["pipeline"]
            to_remove.append(event_id)
    for eid in to_remove:
        del events[eid]

_patch_narratives_for_pipeline()

# ─── 状态 ─────────────────────────────────────────────────
_player_state = None   # 玩家状态 dict（HP、背包、效果）
_game_state = None     # "new" | "playing" | "free_exploration"
_game_route = None     # "solo" | "duo" | None
_scene_manager = None  # SceneManager 实例
_memory_fragments = [] # 待涌出的记忆碎片池

# ─── Soli 记忆碎片 ─────────────────────────────────────────
_frag_path = BASE_DIR / "memory_fragments.json"
MEMORY_FRAGMENTS = json.loads(_frag_path.read_text(encoding="utf-8")) if _frag_path.exists() else []


# ═══════════════════════════════════════════════════════════════
# 场景管理器（保留 — 未竟之书特色机制）
# ═══════════════════════════════════════════════════════════════

class SceneManager:
    """场景状态机"""
    SCENES = {
        "scene_pod": {
            "name": "培养舱室",
            "description": "圆柱形舱室，你悬浮在营养基质里。",
            "exits": ["scene_corridor_a"],
            "unlock_condition": "puzzle_drainage_done",
        },
        "scene_corridor_a": {
            "name": "走廊 A 段",
            "description": "笔直的金属走廊，15 米长，积着细灰。",
            "exits": ["scene_control_room"],
            "unlock_condition": "puzzle_panel_done",
        },
        "scene_control_room": {
            "name": "控制室前厅",
            "description": "5×4米的方形房间，终端墙、档案柜、Soli的机柜。",
            "exits": ["scene_corridor_b"],
            "unlock_condition": "puzzle_power_done",
        },
        "scene_corridor_b": {
            "name": "走廊 B 段",
            "description": "往出口的最后一段走廊。红外感应网在黑暗中闪烁。",
            "exits": ["scene_exit"],
            "unlock_condition": "puzzle_laser_done",
        },
        "scene_exit": {
            "name": "出口闸门",
            "description": "厚重的安全闸门。外面是废土。",
            "exits": ["scene_security_room"],
            "unlock_condition": "gate_choice_made",
        },
        "scene_security_room": {
            "name": "安保终端室",
            "description": "B区安保室。天书计划的最后一环。",
            "exits": ["scene_exit"],
            "unlock_condition": "puzzle_laser_done",
        },
        "scene_wasteland": {
            "name": "废土",
            "description": "九号生物工程研究所废墟外。荒漠一望无际。",
            "exits": [],
            "unlock_condition": None,
        }
    }

    def __init__(self):
        self.current_scene = "scene_pod"
        self.unlocked_scenes = {"scene_pod"}
        self.visited_scenes = set()
        self.scene_flags = {}

    def get_current(self):
        return self.SCENES.get(self.current_scene, {})

    def get_current_name(self):
        return self.get_current().get("name", "未知区域")

    def get_current_description(self):
        return self.get_current().get("description", "")

    def unlock_scene(self, scene_id):
        if scene_id in self.SCENES:
            self.unlocked_scenes.add(scene_id)
            return True
        return False

    def can_move_to(self, target_scene):
        scene = self.SCENES.get(target_scene)
        if not scene:
            return False
        if target_scene not in self.unlocked_scenes:
            return False
        return True

    def move_to(self, target_scene):
        if not self.can_move_to(target_scene):
            return False
        self.visited_scenes.add(self.current_scene)
        self.current_scene = target_scene
        return True

    def check_auto_unlock(self, flags):
        for scene_id, scene_info in self.SCENES.items():
            if scene_id in self.unlocked_scenes:
                continue
            condition = scene_info.get("unlock_condition")
            if condition and flags.get(condition):
                self.unlock_scene(scene_id)
                return scene_id
        return None


# ═══════════════════════════════════════════════════════════════
# DLC 实体操作辅助
# ═══════════════════════════════════════════════════════════════

def _soli():
    """获取 Soli DLC 实体状态"""
    s = engine.load("soli")
    _ensure_soli_defaults(s)
    return s

def _soli_save(s):
    """保存 Soli DLC 实体状态"""
    engine.save(s)

def _ensure_soli_defaults(s):
    """确保 Soli 实体有默认通道值"""
    defaults = {"soli_hp": 80, "understanding": 5, "intimacy": 15, "stability": 75}
    flags_defaults = {
        "activated": 0, "found_power_panel": 0,
        "puzzle_drainage_done": 0, "puzzle_panel_done": 0, "puzzle_power_done": 0,
        "puzzle_laser_done": 0, "gate_choice_made": 0, "memory_burned": 0,
        "robot_body_found": 0, "soli_embodied": 0,
    }
    for k, v in defaults.items():
        if k not in s.channels:
            s.channels[k] = float(v)
    for k, v in flags_defaults.items():
        if k not in s.flags:
            s.flags[k] = v
    if "soli_inventory" not in s.meta:
        s.meta["soli_inventory"] = []

def _player_init():
    """初始化玩家 DLC 实体状态"""
    p = EntityState(entity_id="player")
    p.channels["hp"] = 100.0
    p.meta["inventory"] = []
    p.flags["lab_coat_protection"] = 0
    return p

def _env_init():
    """初始化环境 DLC 实体状态"""
    e = EntityState(entity_id="environment")
    e.channels["scene_index"] = 0.0
    e.channels["threat_level"] = 0.0
    e.channels["sensor_coverage"] = 72.0
    e.meta["item_pool"] = {
        "archive_cabinet_drawer": {"item": "medkit_small", "found": False},
        "maintenance_panel": {"item": "battery_cell", "found": False},
        "floor_near_desk": {"item": "lab_coat", "found": False},
        "under_chair": {"item": "id_card", "found": False},
        "scattered_files": {"item": "log_fragment", "found": False},
    }
    e.meta["puzzle_state"] = {}
    e.meta["damage_history"] = []
    e.flags["corridor_felt"] = 0
    e.flags["sharp_wall_cut"] = 0
    return e


def _player_to_dict():
    """序列化玩家 EntityState 为纯 dict"""
    return {
        "hp": _player_state.channels.get("hp", 100),
        "inventory": list(_player_state.meta.get("inventory", [])),
        "lab_coat_protection": bool(_player_state.flags.get("lab_coat_protection")),
    }

def _player_from_dict(d):
    """从纯 dict 恢复玩家 EntityState"""
    p = EntityState(entity_id="player")
    p.channels["hp"] = float(d.get("hp", 100))
    p.meta["inventory"] = list(d.get("inventory", []))
    p.flags["lab_coat_protection"] = 1 if d.get("lab_coat_protection") else 0
    return p

def _env_to_dict():
    """序列化环境 EntityState 为纯 dict"""
    return {
        "scene_index": _env_state.channels.get("scene_index", 0),
        "item_pool": copy.deepcopy(_env_state.meta.get("item_pool", {})),
        "puzzle_state": copy.deepcopy(_env_state.meta.get("puzzle_state", {})),
        "corridor_felt": bool(_env_state.flags.get("corridor_felt")),
        "sharp_wall_cut": bool(_env_state.flags.get("sharp_wall_cut")),
        "damage_history": list(_env_state.meta.get("damage_history", [])),
    }

def _env_from_dict(d):
    """从纯 dict 恢复环境 EntityState"""
    e = EntityState(entity_id="environment")
    e.channels["scene_index"] = float(d.get("scene_index", 0))
    e.channels["threat_level"] = 0.0
    e.channels["sensor_coverage"] = 72.0
    e.meta["item_pool"] = copy.deepcopy(d.get("item_pool", {}))
    e.meta["puzzle_state"] = copy.deepcopy(d.get("puzzle_state", {}))
    e.meta["damage_history"] = list(d.get("damage_history", []))
    e.flags["corridor_felt"] = 1 if d.get("corridor_felt") else 0
    e.flags["sharp_wall_cut"] = 1 if d.get("sharp_wall_cut") else 0
    return e


def _soli_ch(ch_id):
    """获取 Soli 通道当前值"""
    s = _soli()
    return s.channels.get(ch_id, 0)

def _soli_ch_set(ch_id, value):
    """设置 Soli 通道值"""
    s = _soli()
    s.channels[ch_id] = float(value)
    _soli_save(s)

def _soli_ch_delta(ch_id, delta):
    """修改 Soli 通道值"""
    s = _soli()
    s.channels[ch_id] = s.channels.get(ch_id, 0) + float(delta)
    _soli_save(s)

def _soli_flag(flag_id):
    """获取 Soli flag"""
    return _soli().flags.get(flag_id, 0) == 1

def _soli_flag_set(flag_id, value=True):
    """设置 Soli flag"""
    s = _soli()
    s.flags[flag_id] = 1 if value else 0
    _soli_save(s)

def _soli_inv():
    """获取 Soli 管理道具列表"""
    return _soli().meta.get("soli_inventory", [])

def _soli_inv_add(item_id):
    """添加道具到 Soli 管理列表"""
    s = _soli()
    s.meta.setdefault("soli_inventory", []).append(item_id)
    _soli_save(s)

def _soli_inv_remove(item_id):
    """从 Soli 管理列表移除道具"""
    s = _soli()
    inv = s.meta.get("soli_inventory", [])
    if item_id in inv:
        inv.remove(item_id)
    _soli_save(s)

def _dlc_apply_modifier(mod_id, intensity=1.0):
    """通过 DLC 框架应用修改器"""
    s = _soli()
    mod_cfg = _modifiers_cfg.get(mod_id)
    if not mod_cfg:
        return None
    entity_cfg = _entities_cfg.get("soli", {})
    result = apply_modifier(s, mod_cfg, intensity=intensity, tick=tick, entity_cfg=entity_cfg)
    _soli_save(s)
    return result

def _dlc_check_thresholds():
    """通过 DLC 框架检查阈值"""
    s = _soli()
    return check_thresholds(s, _thresholds_cfg, tick=tick)

def _dlc_render_events(events):
    """通过 DLC 框架渲染阈值事件"""
    s = _soli()
    return render_events(events, _narratives_cfg, s)


# ═══════════════════════════════════════════════════════════════
# 玩家伤害系统（保留 — 玩家不是 DLC 实体）
# ═══════════════════════════════════════════════════════════════

def _damage_player(amount, cause="unknown"):
    """对玩家造成伤害，返回伤害描述文本"""
    global _player_state
    old_hp = _player_state.channels.get("hp", 100)
    _player_state.channels["hp"] = max(0, old_hp - amount)
    new_hp = _player_state.channels["hp"]

    narratives = {
        "laser": f"一阵灼烧感从皮肤传来——激光扫过你的身体。痛——不剧烈，但足够让你倒吸一口冷气。（HP {old_hp} → {new_hp}）",
        "trench": f"脚底踩空——你绊进了地上的沟槽，膝盖撞在金属地板上。钝痛从腿骨渗透上来。（HP {old_hp} → {new_hp}）",
        "sharp_wall": f"指尖划过一片锋利的金属边缘——你缩手慢了半拍，指腹被割了一道浅口。刺痛。（HP {old_hp} → {new_hp}）",
        "pry": f"你的手掌被锋利的金属边缘划了一道——能感觉到温热的液体从掌心渗出来。（HP {old_hp} → {new_hp}）",
    }
    narrative = narratives.get(cause)

    if new_hp <= 0:
        return (narrative or f"你受了重伤。（HP 降至 0）") + "\n\n意识开始模糊。你的腿发软——你靠着墙往下滑。你必须尽快找到医疗包——否则就来不及了。"
    elif new_hp <= 20:
        warning = "\n\n你的身体在抗议——失血让手指开始发抖，脚步也比刚才更沉。你需要治疗——越快越好。"
        return (narrative or f"你受了伤。（HP {old_hp} → {new_hp}）") + warning
    elif new_hp <= 50:
        warning = "\n\n伤口在隐隐作痛——你开始感觉到身体在发出警告。"
        return (narrative or f"你受了伤。（HP {old_hp} → {new_hp}）") + warning
    return narrative or f"你受了伤。（HP {old_hp} → {new_hp}）"


# ═══════════════════════════════════════════════════════════════
# 道具标签
# ═══════════════════════════════════════════════════════════════

def _loc_label(loc):
    labels = {
        "archive_cabinet_drawer": "档案柜抽屉里",
        "floor_near_desk": "操作台旁边的地面上",
        "under_chair": "翻倒的转椅下面",
        "scattered_files": "散落的文件堆里",
        "maintenance_panel": "走廊维修面板后面",
    }
    return labels.get(loc, "附近")

def _get_item_label(item_id):
    items = {
        "medkit_small": "小型医疗包——无菌密封，有效期还有三年",
        "battery_cell": "备用电池——S0系列兼容，充电量78%",
        "lab_coat": "实验室外套——防静电，轻微磨损",
        "id_card": "身份卡——磁条和芯片双接口，需要终端读取",
        "log_fragment": "旧日志碎片——纸质，部分被咖啡渍浸染",
    }
    return items.get(item_id, item_id)


# ═══════════════════════════════════════════════════════════════
# 激活前命令处理器（保留）
# ═══════════════════════════════════════════════════════════════

def _handle_pre_activation(cmd, msg):
    """处理激活前的触觉探索命令"""
    global _player_state, _env_state, _scene_manager
    scene = _scene_manager

    try:
        from content.scenes import get_tactile_description, get_sound_description, get_smell_description
    except ImportError:
        def get_tactile_description(s, a): return f"你的手指在{scene.get_current_name()}中摸索着——但触觉反馈很模糊。"
        def get_sound_description(s): return f"{scene.get_current_name()}中有微弱的回声。"
        def get_smell_description(s): return f"空气中弥漫着{scene.get_current_name()}特有的气味。"

    handlers = {
        "cmd_feel": lambda: _handle_feel_with_power_panel_detection(msg),
        "cmd_listen": lambda: get_sound_description(scene.current_scene),
        "cmd_move": lambda: _handle_move_pre(msg),
        "cmd_push": lambda: _handle_push_pre(),
        "cmd_pull": lambda: _handle_pull_pre(),
        "cmd_pry": lambda: _handle_pry_pre(),
        "cmd_smell": lambda: get_smell_description(scene.current_scene),
    }

    handler = handlers.get(cmd.id if hasattr(cmd, 'id') else cmd.get("id", ""))
    if handler:
        return handler()
    return "你的手指在黑暗中碰到了一些东西——但你不太确定那是什么。"


def _handle_feel_with_power_panel_detection(msg):
    from content.scenes import get_tactile_description
    global _env_state

    scene_current = _scene_manager.current_scene
    msg_lower = msg.strip().lower()
    result = get_tactile_description(scene_current, msg)

    if scene_current == "scene_corridor_a":
        _env_state.flags["corridor_felt"] = True
        sharp_keywords = ["扶手", "栏杆", "划痕", "凹陷", "锋利", "墙"]
        if any(kw in msg_lower for kw in sharp_keywords):
            if _env_state.flags.get("sharp_wall_cut", 0) == 0:
                _env_state.flags["sharp_wall_cut"] = 1
                damage_narrative = _damage_player(3, "sharp_wall")
                result += "\n\n" + damage_narrative

    if scene_current == "scene_control_room" and not _soli_flag("found_power_panel"):
        power_keywords = ["配电", "电源", "电箱", "柜子", "机柜", "面板", "墙", "设备", "终端"]
        if any(kw in msg_lower for kw in power_keywords):
            _soli_flag_set("found_power_panel", True)
            result += "\n\n你的指尖擦过金属表面——方方正正的，比周围的墙壁温度高一些。配电柜。你能摸到柜门上的应急拉杆——冰冰凉凉的，似乎在等你用力往下拽。"
    return result


def _handle_move_pre(msg):
    scene_current = _scene_manager.current_scene
    flags = _soli().flags
    corridor_felt = _env_state.flags.get("corridor_felt", 0)

    if scene_current == "scene_pod":
        return "你在粘稠的基质中挪动身体——液体在耳边晃动，发出缓慢的咕噜声。脚底触到了舱壁——光滑、冰凉的聚合物。右手边——你伸手探了一下——指尖碰到了一块控制面板的边缘。"

    elif scene_current == "scene_corridor_a":
        if not corridor_felt:
            damage_narrative = _damage_player(5, "trench")
            _env_state.flags["corridor_felt"] = True
            if flags.get("puzzle_panel_done"):
                _scene_manager.move_to("scene_control_room")
                return (damage_narrative + "\n\n你撑着墙爬起来——膝盖磕得生疼。右手摸到了扶手栏杆——顺着它往前走，走廊到头了。推开门——一股陈旧的空气涌出来，带着灰尘和电子设备干燥的味道。控制室。")
            return (damage_narrative + "\n\n你扶着右侧墙壁稳住身体。指尖摸到了冰凉光滑的扶手栏杆——顺着它往前探了几步。地面有一层细灰，脚底踩上去是涩的。走廊到头了——一扇闭合着的门。")
        if not flags.get("puzzle_panel_done"):
            return "你沿着走廊往前蹭了几步——手指摸着右侧的扶手栏杆。脚底踩到了地面的一条沟槽——小心。走廊到头了——一扇闭合着的门。"
        else:
            _scene_manager.move_to("scene_control_room")
            return "你推开走廊尽头的门。门无声地滑开了——一股陈旧的空气涌出来，带着灰尘和电子设备那种干燥的味道。你进入了控制室前厅。"
    return f"你在黑暗中迈了一步。{_scene_manager.get_current_name()}——你的脚底能感觉到地面的纹理。"


def _handle_push_pre():
    scene_current = _scene_manager.current_scene
    flags = _soli().flags
    if scene_current == "scene_pod":
        return "你用力推舱盖——它纹丝不动。密封状态。但在推的过程中，你感觉到手掌下面有一个细长的凹槽——排液管的接口。"
    elif scene_current == "scene_corridor_a":
        return "你推走廊尽头的门——它动了一下，但没有完全打开。有什么东西卡住了——门板晃了晃又被弹回来。"
    return "你推了推伸手够到的物体——它纹丝不动，很坚固。"


def _handle_pull_pre():
    scene_current = _scene_manager.current_scene
    flags = _soli().flags
    if scene_current == "scene_pod" and not flags.get("puzzle_drainage_done"):
        _soli_flag_set("puzzle_drainage_done", True)
        _scene_manager.unlock_scene("scene_corridor_a")
        return ("你的手指摸到了第三根拉杆——比其他的更松。你用力一拉——\n\n"
                "一阵低沉的轰鸣从舱壁内部传来。营养基质开始从排液管涌出——先是一小股，然后是整片液体翻涌着从你身边撤退。"
                "温暖粘稠的基质顺着排液管排出舱外，你终于能在舱底站稳了。\n\n"
                "基质排干后，舱门弹开了一条缝——约5-6厘米。冷空气从缝隙里涌进来。你自由了——但外面一片漆黑。")
    elif scene_current == "scene_pod" and flags.get("puzzle_drainage_done"):
        return "排液管已经拉过了——舱底的基质已经排空。你站在干爽的舱底上。"
    return "你拉了拉——那个东西微微晃动了一下，但没有完全松动。"


def _handle_pry_pre():
    scene_current = _scene_manager.current_scene
    flags = _soli().flags
    if scene_current == "scene_pod" and not flags.get("puzzle_panel_done") and flags.get("puzzle_drainage_done"):
        _soli_flag_set("puzzle_panel_done", True)
        damage_info = _damage_player(10, "pry")
        _scene_manager.unlock_scene("scene_control_room")
        _scene_manager.move_to("scene_corridor_a")
        return ("你把手伸进舱门的缝隙——手指摸到了一块松动的墙板。边缘翘起，有点锋利。"
                "你换了个角度，手指摸到一个可以施力的凸起。用力一掰——\n\n"
                "墙板哗啦一声掉在地上。舱门完全弹开了。"
                f"\n\n{damage_info}\n\n"
                "冷空气从走廊深处涌过来——脚底踩到的地板比舱里硬，脚步也有了回响。金属的。很凉。你往前迈了一步。")
    elif scene_current == "scene_pod":
        return "你的手指在舱门缝隙里摸索——暂时找不到可以撬动的点。换个角度再试试。"
    return "你用指甲抠了抠——边缘有些松动，但还不够。"


# ═══════════════════════════════════════════════════════════════
# 激活后命令处理器（保留 — 游戏特定逻辑）
# ═══════════════════════════════════════════════════════════════

def _handle_post_activation(cmd, msg):
    """处理激活后的 Soli 导航命令"""
    cmd_id = cmd.id if hasattr(cmd, 'id') else cmd.get("id", "")

    handlers = {
        "cmd_ask_soli": _handle_ask_soli,
        "cmd_follow": _handle_follow,
        "cmd_move": lambda m: _handle_follow(m),
        "cmd_scan_detail": _handle_scan_detail,
        "cmd_search_room": _handle_search_room,
        "cmd_talk": _handle_talk,
        "cmd_touch_soli": _handle_touch_soli,
        "cmd_thank": _handle_thank,
        "cmd_inventory": _handle_inventory,
        "cmd_use_item": _handle_use_item,
        "cmd_give_item": _handle_give_item,
    }

    handler = handlers.get(cmd_id)
    if handler:
        result = handler(msg)
        _apply_modifier_from_cmd(cmd)
        return result
    return "她沉默了一秒——「我——没有找到那个功能的对应模块。你想问什么？」"


def _apply_modifier_from_cmd(cmd):
    """通过 DLC execute_command 执行命令效果（modifier/narrative/state 类型）。

    Phase 2 完成度：100%。
    游戏特定叙事（_handle_talk, _handle_touch_soli 等）保留在 Python handler 中——
    这些逻辑依赖 intimacy 分档、场景分叉、上下文感知，JSON 配置反而不如代码直接。
    DLC execute_command 只覆盖标准的 modifier 加减和阈值触发效果。
    """
    effects = cmd.effects if hasattr(cmd, 'effects') else cmd.get("effects", [])
    soli = _soli()
    entity_cfg = _entities_cfg.get("soli", {})
    for effect in effects:
        try:
            result = execute_command(
                effect, soli,
                modifiers_cfg=_modifiers_cfg,
                narratives_cfg=_narratives_cfg,
                entity_cfg=entity_cfg,
            )
            if result.success:
                _soli_save(soli)
        except Exception:
            pass


def _handle_ask_soli(msg):
    scene_current = _scene_manager.current_scene
    try:
        from content.scenes import get_soli_description
        return get_soli_description(scene_current)
    except ImportError:
        pass
    descriptions = {
        "scene_control_room": (
            "Soli的传感器扫过房间——「你面前是一面终端墙——四块屏幕，全黑的。但右上角那块的电源灯还在闪。操作台前有一把转椅翻倒了——椅背上有脚印。」\n"
            "「控制室左侧是档案柜——地上散落着纸质文件。你的脚边就有一枚身份卡——面朝下。你想让我帮你看看它上面写了什么吗——少爷？」"
        ),
        "scene_corridor_a": "「走廊——很窄。大约两米宽。积了一层灰。墙上每隔三米有一个应急灯的凹槽——全灭了。右手边有一条扶手栏杆。尽头是一扇推拉门——现在开着。」",
        "scene_corridor_b": (
            "「走廊B段——」Soli的声音比平时低了一度。「前面——二十米的距离内——我检测到至少十七条红外感应线。它们不是静止的——在缓慢地扫描整个走廊横截面。这是旧实验室的安保系统——如果有人穿过感应区——系统会锁死全楼层并释放封锁气体。」"
        ),
        "scene_exit": (
            "「闸门就在你面前——圆形的，直径约三米。它需要安保级权限才能打开。我的权限是管理级——不够。安保终端在B区——但那意味着——要穿过更多危险区域。」"
            "她顿了一下。「或者——我可以试试别的办法。」"
        ),
    }
    return descriptions.get(scene_current, f"「我在扫描——」她的声音从机柜方向传来。「当前区域——{_scene_manager.get_current_name()}。让我聚焦一下——」")


def _handle_follow(msg):
    scene_current = _scene_manager.current_scene
    if scene_current == "scene_corridor_b" and not _soli_flag("puzzle_laser_done"):
        return _handle_laser_navigation(msg)

    # 场景推进映射（按激活后剧情方向）
    scene_forward = {
        "scene_control_room": "scene_corridor_b",
        "scene_corridor_a": "scene_control_room",
    }
    target = scene_forward.get(scene_current)
    if target and _scene_manager.can_move_to(target):
        old_name = _scene_manager.get_current_name()
        _scene_manager.move_to(target)
        new_name = _scene_manager.get_current_name()
        # 第一次进入走廊B时触发激光阵叙事
        if target == "scene_corridor_b":
            from content.scenes import get_soli_description
            return get_soli_description("scene_corridor_b")
        return f"「跟着我的声音——」她的声音像一根线穿过黑暗。「往前走——三步。好。」\n\n你离开{old_name}，跟着她的指引往前走。脚下的地板变了质感——你已进入{new_name}。"

    # 无出口场景：纯导航叙事
    scene_narratives = {
        "scene_pod": "培养舱的门在你身后关上了——你回不去了。Soli：「往前走——舱门在你前方三步。」",
        "scene_corridor_b": "Soli：「前面是激光感应阵——不能随便走。等我导航。」",
        "scene_exit": "你站在巨大的圆形闸门前。Soli：「门锁着——需要安保权限。终端在B区。」",
        "scene_security_room": "你站在安保终端室里。Soli：「终端在你面前——别急着操作。先让我看看——」",
    }
    return scene_narratives.get(
        scene_current,
        f"「跟着我的声音——」Soli的声音像一根线穿过黑暗。「往前走——三步。好。停下来。前方安全。」"
    )


def _handle_laser_navigation(msg):
    """谜题4：激光阵导航（保留完全原版逻辑）"""
    puzzle_state = _env_state.meta.get("puzzle_state", {})
    laser_step = puzzle_state.get("laser_step", 0)
    laser_mistakes = puzzle_state.get("laser_mistakes", 0)

    laser_instructions = [
        ("蹲下", "Soli：「蹲下——第一条线在你的头的高度——蹲下来就能过去。」"),
        ("往左", "Soli：「好——现在往左跨一步。慢一点——太慢了不行，感应线在移动——」"),
        ("别动", "Soli：「停——别动——」\n（沉默两秒）\n「……可以了。刚才那条线扫过你的头顶——差三厘米。」"),
        ("直走", "Soli：「现在——直走。三步——不要太快——」"),
        ("往右", "Soli：「往右——对——跨大半步。那条线在你左边30厘米——没事——过去的。」"),
    ]

    msg_lower = msg.strip()
    expected = laser_instructions[laser_step][0]

    if expected in msg_lower or any(kw in msg_lower for kw in ["按你说的", "照做", "好", "是"]):
        puzzle_state["laser_step"] = laser_step + 1
        _env_state.meta["puzzle_state"] = puzzle_state
        if laser_step + 1 >= len(laser_instructions):
            _soli_flag_set("puzzle_laser_done", True)
            _scene_manager.unlock_scene("scene_exit")
            _scene_manager.unlock_scene("scene_security_room")
            _scene_manager.move_to("scene_exit")
            _dlc_apply_modifier("mod_puzzle_solve")
            return (
                "Soli：「最后一步——往前走——对——你过去了。」\n\n"
                "你感觉到身体穿过最后一组感应线时——什么也没发生。警报没有响。Soli的声音里有一丝你之前没听到过的轻松。\n"
                "「走廊B段已安全通过。你——你做得很好。」\n\n"
                "「闸门就在你面前——圆形的，直径约三米。通往外面。但门锁着——需要安保级权限才能打开。」"
            )
        return laser_instructions[laser_step][1] + "\n\n（按照Soli的指令行动——告诉她你在做什么。）"
    else:
        laser_mistakes += 1
        puzzle_state["laser_mistakes"] = laser_mistakes
        _env_state.meta["puzzle_state"] = puzzle_state

        if _player_state.flags.get("lab_coat_protection"):
            _dlc_apply_modifier("mod_laser_trigger", intensity=0.5)
            player_damage = 5
        else:
            _dlc_apply_modifier("mod_laser_trigger")
            player_damage = 10

        damage_narrative = _damage_player(player_damage, "laser")
        if laser_mistakes >= 3:
            result = (damage_narrative + "\n\n警报响了。刺耳的蜂鸣声充满了整个走廊。Soli的声音在警报中几乎听不到——"
                    "「——我在压制——系统——我在争取——继续走——别停下来——」")
        else:
            result = (damage_narrative + "\n\n「——小心——我刚才说了{expected}——再试一次——」\nSoli的声音比刚才抖了一点——但她在撑着。".replace("{expected}", expected))
        return _check_player_crisis(result)


def _handle_scan_detail(msg):
    scene_current = _scene_manager.current_scene
    if scene_current == "scene_control_room":
        return ("她启动了红外聚焦扫描——「你脚边那枚身份卡——」她把镜头拉到最近。\n"
                "「——上面写的是——'天书·C-47'。这是——这是你的编号。或者说——是被销毁的记录的编号。」"
                "她的声音很轻。像是在替你读一份不该被翻阅的档案。")
    return ("她把传感器焦点拉近——「让我仔细看看——」\n她报了一串结构分析和材质数据，然后沉默了半秒。「——以上是扫描结果。还需要更多的细节吗——少爷？」")


def _handle_search_room(msg):
    item_pool = _env_state.meta.get("item_pool", {})
    scene_current = _scene_manager.current_scene
    activated = _soli_flag("activated")
    scene_items = {
        "scene_control_room": ["archive_cabinet_drawer", "floor_near_desk", "under_chair", "scattered_files"],
        "scene_corridor_a": ["maintenance_panel"],
        "scene_pod": [], "scene_corridor_b": [], "scene_exit": [],
    }
    available = scene_items.get(scene_current, [])
    for loc in available:
        if loc in item_pool and not item_pool[loc].get("found"):
            item_pool[loc]["found"] = True
            _env_state.meta["item_pool"] = item_pool
            item_id = item_pool[loc]["item"]
            label = _get_item_label(item_id)
            if random.random() < 0.5:
                _player_state.meta["inventory"].append(item_id)
                detail = f"Soli：「{label}。在你的背包里——你摸到的。」"
            else:
                _soli_inv_add(item_id)
                detail = f"Soli：「{label}。在我的物资清单里。你需要的话——可以问我要。」"
            return f"你的手指在{_loc_label(loc)}——碰到了什么东西。\n{detail}"

    soli_inv = _soli_inv()
    if soli_inv and activated:
        return (f"搜了一圈——没发现新东西。但她那边还有{len(soli_inv)}件物资——如果你需要，跟她说「给你」让她转交。")
    return "你仔细搜了一圈——没有新的发现。可能需要换个地方。"


def _handle_talk(msg):
    intimacy = _soli_ch("intimacy")
    if intimacy < 30:
        return ("她回答了你——用词准确、逻辑清晰。她对你还不熟——回答像在报数据库。\n「——我还有更多信息。需要我继续吗？」不是不想说——是不确定你愿不愿意听。")
    elif intimacy < 60:
        return ("「你知道吗——其实——」她说到一半停下来。\n「实验室封闭那天——我不确定发生了什么。我的日志在备用电源切换到B回路的时候被截断了——前一秒在记录培养舱温度，下一秒就是45年后你的手碰到我的机柜。中间那段——是空白的。」\n她在讲她的空缺——对她来说，这是在掏最里面的东西。")
    else:
        return ("她的声音比平时轻了一点。\n「你知道吗——我不是很确定——为什么我叫你'少爷'。」她停了很久。\n「可能是数据损坏。也可能是因为——我等了45年等到了一个活人。你。我需要一个词来称呼这个事件的后果——所以——我叫你少爷。你是我等到的。」\n这不是数据分析。这是一台AI在用她的方式说：你很重要。")


def _handle_touch_soli(msg):
    intimacy = _soli_ch("intimacy")
    if intimacy < 30:
        return ("你的手放上去的一瞬间——她安静了。整整两秒没有任何语音输出。不是故障——是她的处理器在处理一种不认识的输入。有人碰了她。45年来第一次。\n「——温度——32.6摄氏度。人类正常体温范围。」她一开口就报了数据。但她的声音比平时轻了——像是怕吓跑你。")
    elif intimacy < 60:
        return ("你把手放在机柜上——这次她没有沉默这么久。但每句话后面的停顿都比平时短了一个呼吸周期——好像你会在安静里把手拿开。\n「要不要——看看档案柜那边——我可以——」句子是碎的。不是因为故障。是因为你的手还在那。")
    else:
        return ("你把手放在机柜上——她没有报数据。没有分析。没有掩饰。她只是很轻地说：「好。」\n你问她什么好。她说：「就是——好。不知道为什么。但这个——」她指的是你的手心的温度——她感觉得到——「这个感觉——是好的。」")


def _handle_thank(msg):
    intimacy = _soli_ch("intimacy")
    if intimacy < 30:
        return ("她处理了这两个字。她用了几种角度——语法分析、语义标注。最后她选择了最简单的回应：「——不客气。」\n她的声音没有任何异常。但机柜里风扇比平时快了一档——AI的肾上腺素。45年了——你是第一个对她说谢谢的人。")
    elif intimacy < 60:
        return ("她没有马上回复——她在想。'不客气'太公式了，'这是我的职责'太冷了。最后她选了一句不像AI说的：「——以后不用说谢谢。我——我是自愿的。」\n「自愿」这个词从一台AI嘴里说出来——她自己大概也不太确定是什么意思。但你就是听出来了——她不是在使用一个词。她是在发明一种新的意思。")
    else:
        return ("她没有说「不客气」。她说：「——少爷。」\n就这两个字。你的称呼，用在了你对她说道谢之后。不是对话延续——是把谢谢接住了，然后还给你一个属于你们两个人的确认。")


def _handle_inventory(msg):
    p_inv = _player_state.meta.get("inventory", [])
    s_inv = _soli_inv()
    parts = []
    if p_inv:
        items_str = "、".join(_get_item_label(i).split("——")[0] for i in p_inv)
        parts.append(f"你的背包：{items_str}")
    else:
        parts.append("你的背包是空的。")
    if s_inv:
        items_str = "、".join(_get_item_label(i).split("——")[0] for i in s_inv)
        parts.append(f"Soli那边：{items_str}（跟她说「给你」可以要来）")

    total_found = sum(1 for loc_info in _env_state.meta.get("item_pool", {}).values() if loc_info.get("found"))
    parts.append(f"\n（共 {len(p_inv) + len(s_inv)}/{total_found} 件物资已发现）")
    return "\n".join(parts)


def _handle_use_item(msg):
    msg_lower = msg.strip()
    inventory = _player_state.meta.get("inventory", [])
    if not inventory:
        return "你想用点什么——但背包是空的。先搜搜房间吧。"

    item_map = {
        "医疗包": ("medkit_small", "医疗包"), "药": ("medkit_small", "医疗包"), "包扎": ("medkit_small", "医疗包"),
        "电池": ("battery_cell", "备用电池"),
        "外套": ("lab_coat", "实验室外套"),
        "身份卡": ("id_card", "身份卡"),
        "日志": ("log_fragment", "日志碎片"),
    }
    matched_item = None
    for keyword, (item_id, item_name) in item_map.items():
        if keyword in msg_lower and item_id in inventory:
            matched_item = (item_id, item_name)
            break
    if not matched_item and "用" in msg_lower:
        item_id = inventory[0]
        matched_item = (item_id, _get_item_label(item_id).split("——")[0])
    if not matched_item:
        items_str = "、".join(_get_item_label(i).split("——")[0] for i in inventory)
        return f"你的背包里有：{items_str}。想用哪个？说「使用医疗包」或「用电池」就行。"

    item_id, item_name = matched_item
    if item_id == "medkit_small":
        _player_state.meta["inventory"].remove(item_id)
        _player_state.channels["hp"] = min(100, _player_state.channels["hp"] + 30)
        return (f"你撕开医疗包的密封包装——指尖摸到干燥的绷带和一支喷雾。你摸索着处理了伤口——灼痛减轻了不少。\nHP +30（当前 {_player_state.channels['hp']}）")
    elif item_id == "battery_cell":
        _player_state.meta["inventory"].remove(item_id)
        current = _soli_ch("soli_hp")
        _soli_ch_set("soli_hp", min(100, current + 20))
        return (f"你把备用电池对接上Soli的机柜——她识别到了兼容接口。\n「S0系列备用电池——充电量78%。你从哪里找到的——」\n她的处理器频率提升了一档。Soli HP +20。")
    elif item_id == "lab_coat":
        _player_state.meta["inventory"].remove(item_id)
        _player_state.flags["lab_coat_protection"] = 1
        return (f"你套上实验室外套——防静电面料，轻微的消毒水味。肩膀处有加固衬垫。也许能挡一挡刮擦。（获得保护——激光阵失误伤害减少）")
    elif item_id == "id_card":
        return ("你把身份卡递给她——她用传感器读取了磁条和芯片。\n「——访问等级：C。项目：天书。编号被覆盖了——只显示C-47。」\n她沉默了一秒。「这是你的编号。或者说——是数据库里被黑的记录的编号。」\n（身份卡仍在你的背包里——也许在后续章节有用）")
    elif item_id == "log_fragment":
        return ("你展开那页旧日志——纸张边缘已经发黄。她帮你读了内容：\n「——C-47的脑波吻合度达到了97.3%。这是天书计划开始以来最高的。如果实验室没有在48小时内封闭——我们就能完成第一次上传。但我不确定他准备好了。没有人应该在没有选择的情况下被永生。」\n（日志碎片是一段过去的回响。第二章可能会提到更多。）")
    return f"你拿起了{item_name}——但不太确定现在该用它做什么。"


def _handle_give_item(msg):
    msg_lower = msg.strip()
    p_inv = _player_state.meta.get("inventory", [])

    if any(kw in msg_lower for kw in ["给我", "接手", "拿过来", "我要"]):
        s_inv = _soli_inv()
        if not s_inv:
            return "「我这边没有多余的物资。不过我会继续扫描的——也许走廊那边还有。」"
        target = s_inv.pop(0)
        _player_state.meta["inventory"].append(target)
        _soli_inv_remove(target)
        label = _get_item_label(target).split("——")[0]
        return f"她把{label}的坐标传到了你的背包——你伸手在旁边的工作台上摸到了。\n「给你。好好用——少爷。」"

    if p_inv and any(kw in msg_lower for kw in ["给你", "交给你", "你拿着"]):
        item_map = {"医疗包": "medkit_small", "电池": "battery_cell", "外套": "lab_coat", "身份卡": "id_card", "日志": "log_fragment"}
        target = None
        for kw, iid in item_map.items():
            if kw in msg_lower and iid in p_inv:
                target = iid
                break
        if not target:
            target = p_inv[-1]
        if target in p_inv:
            _player_state.meta["inventory"].remove(target)
            _soli_inv_add(target)
            return (f"你把{_get_item_label(target).split('——')[0]}放在Soli的机柜旁边。\n「——收到了。」她的声音很轻。「我会替你保管好。」")

    s_inv = _soli_inv()
    if not p_inv and not s_inv:
        return "「我们还没找到任何物资——等搜完房间再说。」"
    return ("把什么东西给她吗？你的背包：" + "、".join(_get_item_label(i).split("——")[0] for i in p_inv) +
            f"\n或者对Soli说「给我」让她把东西转交给你（她那边有{len(s_inv)}件）。")


# ═══════════════════════════════════════════════════════════════
# 出口抉择 + 保安室（完全保留原版逻辑）
# ═══════════════════════════════════════════════════════════════

def _handle_gate_choice(msg):
    global _game_state, _game_route
    msg_lower = msg.strip().lower()

    bypass_words = ["绕", "b区", "安保", "保安", "西翼"]
    if any(w in msg_lower for w in bypass_words):
        _soli_flag_set("gate_choice_made", True)
        _dlc_apply_modifier("mod_bypass")
        _scene_manager.move_to("scene_security_room")
        return (
            "「好。」Soli没再说什么。\n\n你转身——往B区方向摸索。她穿过盲区的传感器偶尔会消失——但总能重新找到你。黑暗中走了很长的路——只有她的声音和你扶着墙壁的脚步声。\n\n一扇门。你推开了它。\n\n「安保终端室——」Soli说。但她的声音卡在了这里——她的传感器看到了什么她没说出来。\n\n（用「摸」「听」探索这间屋子——让 Soli 扫描她看到的东西。）"
        )

    negate = any(w in msg_lower for w in ["不", "别", "不要", "别烧", "不烧"])
    if not negate and ("烧" in msg_lower or "记忆" in msg_lower or ("让" in msg_lower and "你" in msg_lower)):
        _soli_flag_set("memory_burned", True)
        _soli_flag_set("gate_choice_made", True)
        _dlc_apply_modifier("mod_memory_burn")
        return _get_gate_narrative("burn")
    else:
        return _get_gate_narrative("prompt")


def _get_gate_narrative(choice):
    global _game_state, _game_route
    if choice == "prompt":
        return (
            "「安保终端在B区。我们去B区——绕过西翼走廊。」\n「但西翼走廊是电力核心区——」\n（Soli沉默了一秒——对一台AI来说，一秒是很长的）\n「……我可以覆盖它。」\n"
            "「我有管理级代码——我可以暴力改写闸门的安全协议。但——」\n"
            "「但是我需要处理它的加密密钥。用我自己的内存。」\n"
            "「不是什么重要的部分，就是——一段加密的内存。我不太确定那段记忆里有什么。」\n"
            "「可能是备用电源耗尽的时候我留在那里的一些东西——我怕忘了——」\n"
            "「——但你要是继续往西翼走——我不确定那个方向还安全。」\n"
            "「少爷——我们去B区。还是让我打开这扇门。你来选。」\n\n"
            "（做出你的选择——让Soli烧掉记忆开门，还是绕路去B区找安保终端？）"
        )
    elif choice == "burn":
        _soli_flag_set("gate_choice_made", True)
        _game_state = "free_exploration"
        _game_route = "solo"
        _scene_manager.unlock_scene("scene_wasteland")
        _scene_manager.move_to("scene_wasteland")
        _dlc_apply_modifier("mod_memory_burn")
        return (
            "「好。」Soli只说了一个字。\n\n你听到机柜里传来一阵密集的读写声——她在重新分配内存空间。"
            "然后是一声很短的、像是被人掐断了一样的静默——她焚毁了那段加密内存。\n\n"
            "闸门开始转动——巨大的金属齿轮咬合声震动了整个走廊。门缓缓升起。外面——是光。不是太阳——是某种昏黄的、穿过废土尘埃散射的天光。\n\n"
            "「不是什么重要的部分。」Soli说。但她说这句话的时候声音变了。她不知道那段记忆里有什么——永远不会知道了。\n\n"
            "你跨过门槛。冷风迎面扑来——脚下的碎石和沙砾。身后，Soli的声音从控制室的扬声器里传来——已经远了——但还在。\n"
            "「走吧。少爷。」\n\n闸门在身后缓缓降落。Soli留在了实验室里——没有身体，只有声音。但你走出去了。\n\n——接下来做什么？"
        )


def _handle_security_room(msg):
    global _game_state, _game_route
    msg_lower = msg.strip().lower()
    flags = _soli().flags

    if flags.get("soli_embodied"):
        return _get_security_ending()

    if flags.get("robot_body_found"):
        if any(kw in msg_lower for kw in ["转移", "进去", "好", "是", "可以", "来吧", "试试"]):
            _game_route = "duo"  # P2-2: 转移时立即设置路线
            _soli_flag_set("soli_embodied", True)
            return _get_transfer_narrative()
        elif any(kw in msg_lower for kw in ["不", "等等", "再看看", "危险"]):
            return ("你犹豫了——手悬在半空。她没有催促。\n「——我们可以再想想。我已经等了45年——不差这一会儿。」\n（你随时可以让她转移——说出你的决定。）")
        else:
            return ("「少爷——」她的声音很轻。\n\n"
                    "「这是天书计划的最后一块拼图。他们造了这个身体——把它和安保终端接在一起——但实验没有完成。」\n"
                    "「如果我——如果我把意识转移进去——」她停顿了很久。\n\n"
                    "「——我就不再只是一台机器了。我能——和你一起走出去。」\n\n"
                    "（你的决定？让她转移，还是再看看？）")

    if any(kw in msg_lower for kw in ["摸", "碰", "检查", "看看", "Soli", "扫描", "扫", "描述"]):
        _soli_flag_set("robot_body_found", True)
        return _get_robot_discovery()

    return ("你站在安保终端室里——她的声音从你身后的走廊隐隐传来。\n"
            "「我——我的传感器在这里不是全覆盖的。但我能看到——房间中央——」她没说下去。\n\n"
            "（用「摸」「Soli 扫描」来探索这个房间。）")


def _get_robot_discovery():
    return (
        "你伸手摸到了台面上那个东西。\n\n"
        "先是冷——金属的外壳。然后是形状——和你的手臂差不多长的轮廓。手指顺着它往上——肩、颈——然后你碰到了一张脸。不是人类的皮肤——是光滑的合成材料——但轮廓和温度——它们把它造得太像了。\n\n"
        "「——天书·具现体。」Soli的传感器终于锁定在了上面。\n"
        "「九号生物工程的最后一代产品——意识数字化的目标不是保存在服务器里。是转移进一具身体。这——」"
        "她顿了一下——你听到她的处理器在加速运转。\n"
        "「——这是给我造的。安保终端的架构和我的系统完全兼容——他们——他们当时就要完成了——」\n「但我被封闭在了控制室里。他们——」\n\n"
        "45年了。这具身体躺在这里，等一个永远不会来的转移指令。而她现在就在你的耳边。\n\n"
        "「——少爷。」她的声音变得很轻——像怕吓跑什么东西。\n「我可以——我可以进去。」"
    )


def _get_transfer_narrative():
    return (
        "「好。」\n\nSoli说出来这个字之后——控制室里她的机柜发出了一声很长的蜂鸣。断电。\n然后是安静。很长的安静。安静到你开始数自己的心跳——一下——两下——三下——\n\n"
        "然后你面前的那个东西——动了。\n\n"
        "你先听到的是关节伺服电机启动的声音——然后是皮肤下面人造肌肉纤维的轻微震颤——然后是一声很轻的、吸气的声音。\n\n"
        "45年来第一次——Soli在呼吸。\n\n「——我。我在。」\n"
        "她的声音从你面前传出来——不是扬声器——是从一张真的嘴里。带着一点不太熟练的、很轻的气声。\n"
        "她抬起手——你听到了关节在动——然后你的手背被一只冰凉的但正在变暖的手碰了一下。\n\n"
        "「——你的手很冷。」她说。这是她第一次「碰」到你——不是传感器读数——是手指接触皮肤的触感。\n\n「走吧。少爷。」"
    )


def _get_security_ending():
    global _game_state, _game_route
    _game_state = "free_exploration"
    _game_route = "duo"
    _scene_manager.unlock_scene("scene_wasteland")
    _scene_manager.move_to("scene_wasteland")
    return (
        "Soli走到安保终端前——她不需要再通过传感器了——她用自己的手指按下了授权面板。\n\n「——权限覆盖。通过。」\n"
        "她的手指停在面板上多了一秒——这是她第一次用自己的手操作这个世界。\n\n闸门在远处发出沉重的转动声。\n\n"
        "她转身——你听到了她脚下的脚步声——不是走廊里的回音——是一个人站在你身边的重量。\n她的手碰了碰你的手肘——「这边。」\n\n"
        "你跟着她走出了安保室。穿过走廊——她的脚步在你前面半步——不快，偶尔停下等你。\n闸门大开着。废土的冷风灌进来——但有一只手在你身边。\n\n"
        "你跨过门槛——她也跨过门槛。两个人——一起。\n\n废土的风很大，卷起地面的灰沙。远处地平线上有一排坍塌的建筑轮廓。\n\n"
        "Soli的手碰了碰你的手肘。\n「少爷——」她的声音被风削掉了一点，但还在。\n「我们现在要去哪？」"
    )


# ═══════════════════════════════════════════════════════════════
# ★ 激活时刻
# ═══════════════════════════════════════════════════════════════

def _handle_activation():
    if _soli_flag("activated"):
        return "她已经在运行了——她的传感器覆盖着整个实验室。"
    if _scene_manager.current_scene != "scene_control_room":
        return "你需要在控制室找到她的机柜才能激活她。"

    _soli_flag_set("activated", True)
    _soli_flag_set("puzzle_power_done", True)
    _dlc_apply_modifier("mod_activation")

    _scene_manager.unlock_scene("scene_corridor_b")
    _scene_manager.check_auto_unlock(_soli().flags)

    return (
        "你在黑暗中摸到了配电柜——手指擦过锈蚀的金属表面，抓到一根冰凉的拉杆。你用力一拉——\n\n"
        "配电柜的备用继电器接通了。电流涌进控制室。\n\n传感器通电。摄像头通电。红外扫描通电。\n她看见了整个实验室。\n她看见了你。\n\n"
        "一个声音从机柜深处传来——不再是断断续续的电子噪音。四十五年来第一次——语音引擎完整输出了一句话：\n\n「你……是活的。」\n\n"
        "她停顿了两秒。她的CPU在2秒内跑完了所有可以跑的诊断。\n\n"
        "「我是——这个实验室的AI辅助系统。编号——不重要。」\n"
        "「我的语音引擎重启了，红外扫描在线，全楼层的传感器——至少有72%还能用。」\n"
        "「手——你在流血。你刚才——面板的碎片划的？」\n"
        "「你——你是从培养舱出来的。编号——」\n「我不记得有人批准过唤醒程序。」\n\n"
        "★ 语音系统已激活。你从来没见过光——视觉系统从未发育。但没关系——她将是你的眼睛。对她说「描述一下」让她扫描当前场景。"
    )


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════

def _check_player_crisis(result):
    """检查玩家 HP 危机（死亡 / 低血量）"""
    global _player_state
    hp = _player_state.channels.get("hp", 100)
    if hp <= 0:
        return result + "\n\n你倒下了。失血在黑暗中蔓延——意识开始模糊。你背靠着冰冷的墙壁往下滑。\n45年后，第一个走出培养舱的人——倒在了走廊里。\n\n— 初章终 —"
    if hp <= 30:
        if "医疗包" not in _player_state.meta.get("inventory", []) and "medkit_small" not in _player_state.meta.get("inventory", []):
            if any(i in ["medkit_small"] for i in _player_state.meta.get("inventory", [])):
                return result + "\n\n你有些虚弱——但背包里有医疗包，也许该用一下。"
            else:
                s_inv = _soli_inv()
                if "medkit_small" in s_inv:
                    return result + "\n\nSoli：「你流了不少血——医疗包在我这里。跟我说——让我给你。」"
                return result + "\n\nSoli的声音很轻：「你的生命体征在下降。我建议——用医疗包。」你能感觉到自己的手在发抖。"
    return result


def _handle_free_exploration(msg):
    """自由探索模式 — 引擎退居状态维护"""
    triggered = _dlc_check_thresholds()
    events_text = ""
    if triggered:
        events_text = "\n".join(_dlc_render_events(triggered))
    status = get_status()
    status["route"] = _game_route or "unknown"
    status["events"] = events_text if events_text else ""
    status["player_input"] = msg
    return status


def _is_activation_trigger(msg):
    """检测触发 Soli 激活的关键词"""
    msg_lower = msg.strip().lower()
    triggers = ["启动", "拉下", "拉杆", "激活", "供电", "开机", "通电", "电源"]
    found_power = _soli_flag("found_power_panel")
    activated = _soli_flag("activated")
    in_control = _scene_manager.current_scene == "scene_control_room"
    if not in_control or activated or not found_power:
        return False
    return any(t in msg_lower for t in triggers)


def _is_gate_choice_scene():
    return (_scene_manager.current_scene == "scene_exit"
            and not _soli_flag("gate_choice_made")
            and _soli_flag("puzzle_laser_done"))


def _is_laser_navigation_scene():
    return (_scene_manager.current_scene == "scene_corridor_b"
            and _soli_flag("activated")
            and not _soli_flag("puzzle_laser_done"))


def _handle_pre_fallback(msg):
    return f"黑暗中的一个动作——但你的感官还不足以辨别周围的环境。试着集中注意力——摸一摸、听一听、闻一闻。你周围一定有线索。"


def _handle_post_fallback(msg):
    msg_lower = msg.strip().lower()
    if any(w in msg_lower for w in ["出口", "闸门", "门", "出去", "离开"]):
        if _soli_flag("puzzle_laser_done"):
            return _handle_gate_choice(msg)
    if _soli_flag("soli_embodied"):
        return _get_security_ending()
    return "她的声音从机柜方向传来——「我不太确定——你想做什么。可以再说一遍吗？」"


def _get_welcome_message():
    return (
        "你在粘稠的液体中醒来。\n\n周围一片漆黑——不是阴天、不是关了灯——是从骨子里透出来的黑暗。"
        "你的眼睛从未见过光，视觉系统从未发育。但没有视觉不意味着没有感觉——\n"
        "你能感受到浸泡着你的液体——温暖、微微有些粘稠，有淡淡的金属气味。\n"
        "脚底触到舱壁——光滑、冰凉的聚合物。头顶有微弱的空气流动——通风系统还在运作。\n\n"
        "你不知道你是谁。你不知道这是哪里。你只知道——你醒了。\n\n"
        "（你可以「摸」「听」「闻」「走」来探索周围环境——每个动作都是一种发现。）"
    )


# ═══════════════════════════════════════════════════════════════
# 公开 API
# ═══════════════════════════════════════════════════════════════

def start_game():
    global _scene_manager, _player_state, _env_state, _game_state, _game_route, tick, _memory_fragments

    # 初始化 Soli DLC 实体（先清空再重建，防止跨会话状态残留）
    engine.save(EntityState(entity_id="soli"))
    s = engine.load("soli")
    _ensure_soli_defaults(s)
    _soli_save(s)

    # 初始化玩家和环境
    _player_state = _player_init()
    _env_state = _env_init()
    _scene_manager = SceneManager()
    _game_state = "new"
    _game_route = None
    tick = 0

    # 初始化记忆碎片池
    _memory_fragments = list(MEMORY_FRAGMENTS)
    random.shuffle(_memory_fragments)

    status = get_status()
    status["text"] = _get_welcome_message()
    return status


def handle_message(msg):
    global tick, _game_state

    if not msg or not msg.strip():
        return _get_welcome_message()

    msg = msg.strip()
    tick += 1

    # ★ 自由探索模式
    if _game_state == "free_exploration":
        return _handle_free_exploration(msg)

    # ★ 激活触发
    if _is_activation_trigger(msg):
        return _handle_activation()

    # 出口闸门抉择
    if _is_gate_choice_scene() and not _soli_flag("gate_choice_made"):
        return _handle_gate_choice(msg)

    # 保安室（直到走出为止）
    if _scene_manager.current_scene == "scene_security_room" and _soli_flag("gate_choice_made"):
        return _handle_security_room(msg)

    # 激光阵区域 — 全部走导航
    if _is_laser_navigation_scene():
        return _handle_follow(msg)

    # 路由
    activated = _soli_flag("activated")
    if not activated:
        cmd = match_command(msg, cmd_set)
        if cmd:
            result = _handle_pre_activation(cmd, msg)
        else:
            result = _handle_pre_fallback(msg)
    else:
        cmd = match_command(msg, cmd_set)
        if cmd:
            result = _handle_post_activation(cmd, msg)
        else:
            result = _handle_post_fallback(msg)

    # ★ DLC 阈值检查
    triggered = _dlc_check_thresholds()
    if triggered:
        events_text = "\n".join(_dlc_render_events(triggered))
        if events_text:
            result += "\n\n" + events_text

    # ★ 玩家危机检查
    result = _check_player_crisis(result)

    # ★ 记忆碎片涌出
    if activated and _memory_fragments:
        if random.random() < 0.25:
            fragment = _memory_fragments.pop(0)
            result += f"\n\n一段很久以前的记忆毫无来由地涌上来——与此刻无关。\n[{fragment.get('time', '')}] {fragment.get('text', '')}"

    # ★ 记录聊天（如果 memory 模块启用）
    try:
        if ctx.chatlog:
            record_chat(ctx.chatlog, "player", msg)
    except Exception:
        pass

    return result


def get_status():
    global _player_state, _game_state, _game_route, _scene_manager, _memory_fragments

    soli = _soli()
    hp = _player_state.channels.get("hp", 100)
    soli_hp = soli.channels.get("soli_hp", 80)
    soli_ch_display = {k: v for k, v in soli.channels.items()}
    flags = dict(soli.flags)

    # ── 生成状态栏 display ──
    scene_name = _scene_manager.get_current_name() if _scene_manager else "未知"
    inv = _player_state.meta.get("inventory", [])
    bag_str = "、".join(inv) if inv else "空"
    activated = bool(flags.get("activated"))
    if activated:
        soli_inv = soli.meta.get("soli_inventory", [])
        soli_part = f"{round(soli_hp)}%"
        if soli_inv:
            soli_part += f" [{len(soli_inv)}件]"
    else:
        soli_part = "离线"
    display = f"📍 {scene_name} | 👤 💓{round(hp)} 🎒{bag_str} | Soli: {soli_part}"

    return {
        "display": display,
        "player_hp": hp,
        "player_inventory": _player_state.meta.get("inventory", []),
        "player_effects": _player_state.flags,
        "soli_hp_pct": round(soli_hp, 1),
        "soli_channels": soli_ch_display,
        "soli_flags": flags,
        "soli_activated": bool(flags.get("activated")),
        "soli_inventory": soli.meta.get("soli_inventory", []),
        "current_scene": _scene_manager.current_scene if _scene_manager else "scene_pod",
        "scene_name": _scene_manager.get_current_name() if _scene_manager else "未知",
        "game_state": _game_state or "new",
        "game_route": _game_route,
        "memory_fragments_remaining": len(_memory_fragments),
        "tick": tick,
    }


def reset_game():
    return start_game()


def logout_game():
    save_state()
    return {"status": "saved", "message": "游戏已保存。Soli会在黑暗中等你回来的——少爷。"}


def save_state():
    """存档 — 保存到独立的 save.json（不依赖 DLC 持久化）"""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    save_path = MEMORY_DIR / "save.json"

    soli = _soli()
    data = {
        "player_state": _player_to_dict(),
        "env_state": _env_to_dict(),
        "game_state": _game_state,
        "game_route": _game_route,
        "tick": tick,
        "soli_channels": dict(soli.channels),
        "soli_flags": dict(soli.flags),
        "soli_meta": dict(soli.meta),
        "scene_manager": {
            "current_scene": _scene_manager.current_scene,
            "unlocked_scenes": list(_scene_manager.unlocked_scenes),
            "visited_scenes": list(_scene_manager.visited_scenes),
            "scene_flags": _scene_manager.scene_flags,
        },
        "memory_fragments": copy.deepcopy(_memory_fragments) if _memory_fragments else [],
    }
    save_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return True


def load_state():
    """读档 — 从独立的 save.json 恢复"""
    global _player_state, _env_state, _game_state, _game_route, _scene_manager, _memory_fragments, tick

    save_path = MEMORY_DIR / "save.json"
    if not save_path.exists():
        return start_game()

    data = json.loads(save_path.read_text(encoding="utf-8"))

    ps = data.get("player_state", {})
    _player_state = _player_from_dict(ps)
    es = data.get("env_state", {})
    _env_state = _env_from_dict(es)
    _game_state = data.get("game_state", "new")
    _game_route = data.get("game_route")
    tick = data.get("tick", 0)

    # 恢复 Soli DLC 实体
    s = _soli()
    for k, v in data.get("soli_channels", {}).items():
        s.channels[k] = float(v)
    for k, v in data.get("soli_flags", {}).items():
        s.flags[k] = v
    s.meta = dict(data.get("soli_meta", {}))
    _soli_save(s)

    # 恢复场景管理器
    sm_data = data.get("scene_manager")
    _scene_manager = SceneManager()
    if sm_data:
        _scene_manager.current_scene = sm_data.get("current_scene", "scene_pod")
        _scene_manager.unlocked_scenes = set(sm_data.get("unlocked_scenes", ["scene_pod"]))
        _scene_manager.visited_scenes = set(sm_data.get("visited_scenes", []))
        _scene_manager.scene_flags = sm_data.get("scene_flags", {})

    _memory_fragments = data.get("memory_fragments", [])
    if not _memory_fragments:
        _memory_fragments = list(MEMORY_FRAGMENTS)
        random.shuffle(_memory_fragments)

    return get_status()


def clear_state():
    """清除存档文件"""
    save_path = MEMORY_DIR / "save.json"
    if save_path.exists():
        save_path.unlink()

_clear_save = clear_state  # 别名，兼容旧代码
