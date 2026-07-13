# -*- coding: utf-8 -*-
"""
未竟之书初章·遇见 — 游戏引擎
===========================================
DLC 数字生命卡片引擎。单 DLC 实体 (Soli) + 双 Python dict (player + environment)。

公开 API (7个函数):
  start_game()    → 初始化游戏状态
  handle_message(msg) → 处理玩家输入
  get_status()    → 返回当前状态摘要
  reset_game()    → 重置游戏
  logout_game()   → 保存并退出
  save_state()    → 存档到磁盘
  clear_state()   → 清除存档

架构:
  ┌──────────────────────────────────────┐
  │  engine.py: SceneManager + Router     │
  │  ├─ 激活前: 触觉探索命令 (7个)        │
  │  └─ 激活后: Soli导航命令 (7个)        │
  │                                       │
  │  content/scenes.py  → 场景描述        │
  │  content/puzzles.py → 谜题逻辑 + 叙事 │
  │  cards/weijingzhishu/ → JSON配置      │
  └──────────────────────────────────────┘
"""

import json
import os
import random
import copy
import time
from datetime import datetime
from pathlib import Path

# ─── 路径配置 ──────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
CARD_DIR = BASE_DIR / "cards" / "weijingzhishu"
ENGINE_DIR = CARD_DIR / "engine"
INTERACTION_DIR = CARD_DIR / "interaction"
CONTENT_DIR = BASE_DIR / "content"
MEMORY_DIR = BASE_DIR / "MEMORY"

# ─── GameState 单例 ────────────────────────────────────────

class GameState:
    """游戏状态容器 — 避免模块级全局变量的引用问题"""
    def __init__(self):
        self.game_state = None
        self.entity_state = None
        self.player_state = None
        self.env_state = None
        self.scene_manager = None
        self.memory_fragments = None  # 待涌出的记忆碎片池

GS = GameState()
_config_cache = {}
_narrative_cache = {}

# ─── Soli 记忆碎片 ──────────────────────────────────────────
# 20 组带时间戳的温度记忆。激活后随机涌出，不重复。
# 内容已碎片化，仅保留情感温度，与当前环境无关。
# 数据文件：memory_fragments.json

import json as _json
_frag_path = BASE_DIR / "memory_fragments.json"
MEMORY_FRAGMENTS = _json.loads(_frag_path.read_text(encoding="utf-8")) if _frag_path.exists() else []
del _json, _frag_path

# ─── 配置加载 ──────────────────────────────────────────────

def _load_config(filename):
    """加载 JSON 配置文件（带缓存）。搜索顺序: card根 → engine/ → interaction/"""
    if filename not in _config_cache:
        search_paths = [
            CARD_DIR / filename,
            ENGINE_DIR / filename,
            INTERACTION_DIR / filename,
        ]
        for path in search_paths:
            if path.exists():
                _config_cache[filename] = json.loads(path.read_text(encoding="utf-8"))
                return _config_cache[filename]
        return {}
    return _config_cache[filename]

def _load_narratives():
    """加载叙事文本"""
    if "narratives" not in _narrative_cache:
        path = ENGINE_DIR / "narratives.json"
        if path.exists():
            _narrative_cache["narratives"] = json.loads(path.read_text(encoding="utf-8"))
        else:
            _narrative_cache["narratives"] = {"events": {}, "command_assembly": {}}
    return _narrative_cache["narratives"]


# ═══════════════════════════════════════════════════════════════
# Phase 1: 场景管理器
# ═══════════════════════════════════════════════════════════════

class SceneManager:
    """场景状态机 — 复用区域解锁设计模式"""
    
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
            "description": "B区安保室。九号生物工程的具身智能实验室——天书计划的最后一环。",
            "exits": ["scene_exit"],
            "unlock_condition": "puzzle_laser_done",
        },
        "scene_wasteland": {
            "name": "废土",
            "description": "九号生物工程研究所废墟外。荒漠一望无际，地平线上有坍塌的建筑轮廓。",
            "exits": [],
            "unlock_condition": None,  # 自由探索，不限制方向
        }
    }

    def __init__(self):
        self.current_scene = "scene_pod"
        self.unlocked_scenes = {"scene_pod"}
        self.visited_scenes = set()
        self.scene_flags = {}  # per-scene state

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
        """根据 puzzle 完成状态自动解锁新场景"""
        for scene_id, scene_info in self.SCENES.items():
            if scene_id in self.unlocked_scenes:
                continue
            condition = scene_info.get("unlock_condition")
            if condition and flags.get(condition):
                self.unlock_scene(scene_id)
                return scene_id
        return None


# ═══════════════════════════════════════════════════════════════
# Phase 1: 状态初始化
# ═══════════════════════════════════════════════════════════════

def _init_player():
    """初始化玩家状态 dict"""
    return {
        "hp": 100,
        "inventory": [],
        "last_action": None,
    }

def _init_environment():
    """初始化环境状态 dict"""
    return {
        "scene_id": "scene_pod",
        "threat_level": 0,        # 环境敌意程度
        "sensor_coverage": 0.72,  # Soli 传感器覆盖率
        "item_pool": _init_item_pool(),
        "events_triggered": [],
        "puzzle_state": {},
    }

def _init_item_pool():
    """初始化道具池（位置→道具）"""
    return {
        "archive_cabinet_drawer": {"item": "medkit_small", "found": False},
        "maintenance_panel": {"item": "battery_cell", "found": False},
        "floor_near_desk": {"item": "lab_coat", "found": False},
        "under_chair": {"item": "id_card", "found": False},
        "scattered_files": {"item": "log_fragment", "found": False},
    }

def _init_entity(entities_config):
    """初始化 Soli DLC 实体"""
    soli_cfg = entities_config.get("entities", {}).get("soli", {})
    channels_cfg = soli_cfg.get("channels", {})
    
    channels = {}
    for ch_id, ch_cfg in channels_cfg.items():
        channels[ch_id] = {
            "value": ch_cfg.get("initial", 50.0),
            "min": ch_cfg.get("min", 0.0),
            "max": ch_cfg.get("max", 100.0),
            "description": ch_cfg.get("description", ""),
        }
    
    return {
        "entity_id": "soli",
        "name": "Soli",
        "channels": channels,
        "flags": {
            "activated": False,
            "found_power_panel": False,
            "puzzle_drainage_done": False,
            "puzzle_panel_done": False,
            "puzzle_power_done": False,
            "puzzle_laser_done": False,
            "gate_choice_made": False,
            "memory_burned": False,
            "robot_body_found": False,
            "soli_embodied": False,
        },
        "cooldowns": {},
        "event_history": [],
        "soli_inventory": [],  # Soli 代为保管的道具
    }


# ═══════════════════════════════════════════════════════════════
# 命令路由
# ═══════════════════════════════════════════════════════════════

def _route_command(msg):
    """根据消息内容匹配命令"""
    msg_lower = msg.strip().lower()
    commands_config = _load_config("commands.json")
    
    if not commands_config:
        return None
    
    commands = commands_config.get("commands", [])
    if not commands:
        return None
    
    best_match = None
    best_len = 0
    
    for cmd in commands:
        if not isinstance(cmd, dict):
            continue
        for trigger in cmd.get("triggers", []):
            if trigger in msg_lower:
                if len(trigger) > best_len:
                    best_match = cmd
                    best_len = len(trigger)
    
    return best_match


# ═══════════════════════════════════════════════════════════════
# 玩家伤害系统
# ═══════════════════════════════════════════════════════════════

def _damage_player(amount, cause="unknown"):
    """对玩家造成伤害，返回伤害描述文本"""
    old_hp = GS.player_state.get("hp", 100)
    GS.player_state["hp"] = max(0, old_hp - amount)
    new_hp = GS.player_state["hp"]
    
    # 记录伤害源用于叙事
    GS.env_state.setdefault("damage_history", []).append({
        "amount": amount, "cause": cause, "hp_after": new_hp
    })
    
    # 生成伤害叙事
    narratives = {
        "laser": f"一阵灼烧感从皮肤传来——激光扫过你的身体。痛——不剧烈，但足够让你倒吸一口冷气。（HP {old_hp} → {new_hp}）",
        "trench": f"脚底踩空——你绊进了地上的沟槽，膝盖撞在金属地板上。钝痛从腿骨渗透上来。（HP {old_hp} → {new_hp}）",
        "sharp_wall": f"指尖划过一片锋利的金属边缘——你缩手慢了半拍，指腹被割了一道浅口。刺痛。（HP {old_hp} → {new_hp}）",
        "pry": f"你的手掌被锋利的金属边缘划了一道——能感觉到温热的液体从掌心渗出来。（HP {old_hp} → {new_hp}）",
    }
    
    narrative = narratives.get(cause)
    
    # HP 低时追加警告
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
# 修饰符应用
# ═══════════════════════════════════════════════════════════════

def _apply_modifier(modifier_id):
    """应用修饰符到 Soli 通道"""
    modifiers_config = _load_config("modifiers.json")
    mod_data = modifiers_config.get("modifiers", {}).get(modifier_id)
    if not mod_data:
        return []
    
    changes = []
    for ch_id, effect in mod_data.get("effects", {}).items():
        if ch_id in GS.entity_state["channels"]:
            ch = GS.entity_state["channels"][ch_id]
            delta = effect.get("base", 0)
            rand = effect.get("random", 0)
            if rand > 0:
                delta += random.uniform(-rand, rand)
            
            old_val = ch["value"]
            ch["value"] = max(ch["min"], min(ch["max"], ch["value"] + delta))
            changes.append((ch_id, old_val, ch["value"], delta))
    
    return changes


def _apply_modifier_halved(modifier_id):
    """P2-2: 应用修饰符但效果减半（lab_coat 保护）"""
    modifiers_config = _load_config("modifiers.json")
    mod_data = modifiers_config.get("modifiers", {}).get(modifier_id)
    if not mod_data:
        return []
    
    changes = []
    for ch_id, effect in mod_data.get("effects", {}).items():
        if ch_id in GS.entity_state["channels"]:
            ch = GS.entity_state["channels"][ch_id]
            delta = effect.get("base", 0) // 2  # 减半
            rand = effect.get("random", 0)
            if rand > 0:
                delta += random.uniform(-rand // 2, rand // 2)
            
            old_val = ch["value"]
            ch["value"] = max(ch["min"], min(ch["max"], ch["value"] + delta))
            changes.append((ch_id, old_val, ch["value"], delta))
    
    return changes


def _check_thresholds():
    """检查所有阈值事件"""
    thresholds_config = _load_config("thresholds.json")
    thresholds = thresholds_config.get("thresholds", {})
    
    triggered_events = []
    
    for thr_id, thr in thresholds.items():
        ch_id = thr.get("channel")
        if ch_id not in GS.entity_state["channels"]:
            continue
        
        current_val = GS.entity_state["channels"][ch_id]["value"]
        operator = thr.get("operator", ">=")
        target_val = thr.get("value", 0)
        
        # Check operator
        triggered = False
        if operator == ">=":
            triggered = current_val >= target_val
        elif operator == ">":
            triggered = current_val > target_val
        elif operator == "<=":
            triggered = current_val <= target_val
        elif operator == "<":
            triggered = current_val < target_val
        elif operator == "==":
            triggered = abs(current_val - target_val) < 0.01
        
        if not triggered:
            continue
        
        # Check cooldown
        cooldown_key = f"cooldown_{thr_id}"
        cooldowns = GS.entity_state.get("cooldowns", {})
        cooldown_ticks = thr.get("cooldown_ticks", 3)
        
        if cooldown_key in cooldowns:
            cooldowns[cooldown_key] -= 1
            if cooldowns[cooldown_key] > 0:
                continue
        
        cooldowns[cooldown_key] = cooldown_ticks
        GS.entity_state["cooldowns"] = cooldowns
        
        event_id = thr.get("event_id")
        if event_id and event_id not in GS.env_state["events_triggered"]:
            GS.env_state["events_triggered"].append(event_id)
            triggered_events.append({
                "event_id": event_id,
                "channel": ch_id,
                "value": current_val,
                "type": thr.get("event_type", "info"),
            })
    
    return triggered_events


# ═══════════════════════════════════════════════════════════════
# Phase 1: 激活前命令
# ═══════════════════════════════════════════════════════════════

def _handle_pre_activation(cmd, msg):
    """处理激活前的触觉探索命令"""
    if not cmd:
        return _handle_pre_fallback(msg)
    cmd_id = cmd.get("id", "")
    scene = GS.scene_manager.get_current_name()
    
    # 从场景文件获取当前场景的触觉描述
    try:
        from content.scenes import get_tactile_description, get_sound_description, get_smell_description
    except ImportError:
        get_tactile_description = lambda s, a: f"你的手指在{scene}中摸索着——但触觉反馈很模糊。"
        get_sound_description = lambda s: f"{scene}中有微弱的回声。"
        get_smell_description = lambda s: f"空气中弥漫着{scene}特有的气味。"
    
    handlers = {
        "cmd_feel": lambda: _handle_feel_with_power_panel_detection(msg),
        "cmd_listen": lambda: get_sound_description(GS.scene_manager.current_scene),
        "cmd_move": lambda: _handle_move_pre(msg),
        "cmd_push": lambda: _handle_push_pre(),
        "cmd_pull": lambda: _handle_pull_pre(),
        "cmd_pry": lambda: _handle_pry_pre(),
        "cmd_smell": lambda: get_smell_description(GS.scene_manager.current_scene),
    }
    
    handler = handlers.get(cmd_id)
    if handler:
        return handler()
    return f"你的手指在黑暗中碰到了一些东西——但你不太确定那是什么。"


def _handle_feel_with_power_panel_detection(msg):
    """激活前触觉探索 + 配电柜检测 + 走廊探索追踪"""
    from content.scenes import get_tactile_description
    
    scene = GS.scene_manager.current_scene
    msg_lower = msg.strip().lower()
    result = get_tactile_description(scene, msg)
    
    # 追踪走廊探索 — 防沟槽绊倒
    if scene == "scene_corridor_a":
        GS.env_state["corridor_felt"] = True
        
        # 摸到扶手/墙壁上锋利的划痕 → 轻微割伤
        sharp_keywords = ["扶手", "栏杆", "划痕", "凹陷", "锋利", "墙"]
        if any(kw in msg_lower for kw in sharp_keywords):
            wall_cuts = GS.env_state.get("sharp_wall_cuts", 0)
            if wall_cuts == 0:  # 第一次摸到才受伤
                GS.env_state["sharp_wall_cuts"] = 1
                damage_narrative = _damage_player(3, "sharp_wall")
                result += "\n\n" + damage_narrative
    
    # P1-3 修复：在控制室摸到配电柜时设置 flag
    if scene == "scene_control_room" and not GS.entity_state["flags"].get("found_power_panel"):
        power_keywords = ["配电", "电源", "电箱", "柜子", "机柜", "面板", "墙", "设备", "终端"]
        if any(kw in msg_lower for kw in power_keywords):
            GS.entity_state["flags"]["found_power_panel"] = True
            result += "\n\n你的指尖擦过金属表面——方方正正的，比周围的墙壁温度高一些。配电柜。你能摸到柜门上的应急拉杆——冰冰凉凉的，似乎在等你用力往下拽。"
    
    return result

def _handle_move_pre(msg):
    """激活前移动 — 描述移动后的新触觉信息"""
    scene = GS.scene_manager.current_scene
    
    if scene == "scene_pod":
        GS.player_state["last_action"] = "move"
        return "你在粘稠的基质中挪动身体——液体在耳边晃动，发出缓慢的咕噜声。脚底触到了舱壁——光滑、冰凉的聚合物。右手边——你伸手探了一下——指尖碰到了一块控制面板的边缘。"
    
    elif scene == "scene_corridor_a":
        flags = GS.entity_state["flags"]
        corridor_felt = GS.env_state.get("corridor_felt", False)
        
        # ★ 未摸过走廊就乱走 → 绊进沟槽
        if not corridor_felt:
            damage_narrative = _damage_player(5, "trench")
            GS.env_state["corridor_felt"] = True
            
            # 面板已撬开 → 绊倒后直接进控制室
            if flags.get("puzzle_panel_done"):
                GS.scene_manager.move_to("scene_control_room")
                return (damage_narrative + "\n\n"
                        "你撑着墙爬起来——膝盖磕得生疼。右手摸到了扶手栏杆——顺着它往前走，走廊到头了。推开门——一股陈旧的空气涌出来，带着灰尘和电子设备干燥的味道。控制室。")
            
            # 面板还没撬 → 仍在走廊
            return (damage_narrative + "\n\n"
                    "你扶着右侧墙壁稳住身体。指尖摸到了冰凉光滑的扶手栏杆——顺着它往前探了几步。地面有一层细灰，脚底踩上去是涩的。走廊到头了——一扇闭合着的门。")
        
        # 已经摸过走廊了
        if not flags.get("puzzle_panel_done"):
            return "你沿着走廊往前蹭了几步——手指摸着右侧的扶手栏杆。脚底踩到了地面的一条沟槽——小心。走廊到头了——一扇闭合着的门。"
        else:
            GS.scene_manager.move_to("scene_control_room")
            return "你推开走廊尽头的门。门无声地滑开了——一股陈旧的空气涌出来，带着灰尘和电子设备那种干燥的味道。你进入了控制室前厅。"
    
    return f"你在黑暗中迈了一步。{scene}——你的脚底能感觉到地面的纹理。"

def _handle_push_pre():
    """激活前推"""
    scene = GS.scene_manager.current_scene
    flags = GS.entity_state["flags"]
    
    if scene == "scene_pod":
        return "你用力推舱盖——它纹丝不动。密封状态。但在推的过程中，你感觉到手掌下面有一个细长的凹槽——排液管的接口。"
    
    elif scene == "scene_corridor_a":
        return "你推走廊尽头的门——它动了一下，但没有完全打开。有什么东西卡住了——门板晃了晃又被弹回来。"
    
    return "你推了推伸手够到的物体——它纹丝不动，很坚固。"

def _handle_pull_pre():
    """激活前拉"""
    scene = GS.scene_manager.current_scene
    flags = GS.entity_state["flags"]
    
    if scene == "scene_pod" and not flags.get("puzzle_drainage_done"):
        flags["puzzle_drainage_done"] = True
        GS.entity_state["flags"] = flags
        
        # 排液成功后解锁走廊但暂不移动（还要撬面板）
        GS.scene_manager.unlock_scene("scene_corridor_a")
        
        return ("你的手指摸到了第三根拉杆——比其他的更松。你用力一拉——\n\n"
                "一阵低沉的轰鸣从舱壁内部传来。营养基质开始从排液管涌出——先是一小股，然后是整片液体翻涌着从你身边撤退。"
                "温暖粘稠的基质顺着排液管排出舱外，你终于能在舱底站稳了。\n\n"
                "基质排干后，舱门弹开了一条缝——约5-6厘米。冷空气从缝隙里涌进来。你自由了——但外面一片漆黑。")
    
    elif scene == "scene_pod" and flags.get("puzzle_drainage_done"):
        return "排液管已经拉过了——舱底的基质已经排空。你站在干爽的舱底上。"
    
    return "你拉了拉——那个东西微微晃动了一下，但没有完全松动。"

def _handle_pry_pre():
    """激活前撬"""
    scene = GS.scene_manager.current_scene
    flags = GS.entity_state["flags"]
    
    if scene == "scene_pod" and not flags.get("puzzle_panel_done") and flags.get("puzzle_drainage_done"):
        flags["puzzle_panel_done"] = True
        GS.entity_state["flags"] = flags
        
        # 撬面板时被碎片划伤 — 叙事已描述边缘锋利，必须扣血
        damage_info = _damage_player(10, "pry")
        
        GS.scene_manager.unlock_scene("scene_control_room")
        # 面板撬开后移动到走廊
        GS.scene_manager.move_to("scene_corridor_a")
        
        return ("你把手伸进舱门的缝隙——手指摸到了一块松动的墙板。边缘翘起，有点锋利。"
                "你换了个角度，手指摸到一个可以施力的凸起。用力一掰——\n\n"
                "墙板哗啦一声掉在地上。舱门完全弹开了。"
                f"\n\n{damage_info}\n\n"
                "冷空气从走廊深处涌过来——脚底踩到的地板比舱里硬，脚步也有了回响。金属的。很凉。你往前迈了一步。")
    
    elif scene == "scene_pod":
        return "你的手指在舱门缝隙里摸索——暂时找不到可以撬动的点。换个角度再试试。"
    
    return "你用指甲抠了抠——边缘有些松动，但还不够。"


# ═══════════════════════════════════════════════════════════════
# Phase 2-3: 激活后命令
# ═══════════════════════════════════════════════════════════════

def _handle_post_activation(cmd, msg):
    """处理激活后的 Soli 导航命令"""
    if not cmd:
        return _handle_post_fallback(msg)
    cmd_id = cmd.get("id", "")
    
    handlers = {
        "cmd_ask_soli": _handle_ask_soli,
        "cmd_follow": _handle_follow,
        "cmd_move": lambda msg: _handle_follow(msg),  # 激光阵区域方向词 → 导航
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
    
    return "Soli沉默了一秒——「我——没有找到那个功能的对应模块。你想问什么？」"

def _apply_modifier_from_cmd(cmd):
    """从命令 effects 中提取并应用 modifier"""
    modifiers_config = _load_config("modifiers.json")
    for effect in cmd.get("effects", []):
        if effect.get("type") == "modifier":
            mod_id = effect.get("modifier_id")
            if mod_id:
                _apply_modifier(mod_id)

def _handle_ask_soli(msg):
    """Soli描述当前场景"""
    scene = GS.scene_manager.current_scene
    
    try:
        from content.scenes import get_soli_description
        return get_soli_description(scene)
    except ImportError:
        pass
    
    descriptions = {
        "scene_control_room": (
            "Soli的传感器扫过房间——「你面前是一面终端墙——四块屏幕，全黑的。但右上角那块的电源灯还在闪。操作台前有一把转椅翻倒了——椅背上有脚印。」\n"
            "「控制室左侧是档案柜——地上散落着纸质文件。你的脚边就有一枚身份卡——面朝下。你想让我帮你看看它上面写了什么吗——少爷？」"
        ),
        "scene_corridor_a": (
            "「走廊——很窄。大约两米宽。积了一层灰。墙上每隔三米有一个应急灯的凹槽——全灭了。右手边有一条扶手栏杆。尽头是一扇推拉门——现在开着。」"
        ),
        "scene_corridor_b": (
            "「走廊B段——」Soli的声音比平时低了一度。「前面——二十米的距离内——我检测到至少十七条红外感应线。它们不是静止的——在缓慢地扫描整个走廊横截面。这是旧实验室的安保系统——如果有人穿过感应区——系统会锁死全楼层并释放封锁气体。」"
        ),
        "scene_exit": (
            "「闸门就在你面前——圆形的，直径约三米。它需要安保级权限才能打开。我的权限是管理级——不够。安保终端在B区——但那意味着——要穿过更多危险区域。」"
            "她顿了一下。「或者——我可以试试别的办法。」"
        ),
    }
    return descriptions.get(scene, f"「我在扫描——」Soli的声音从机柜方向传来。「当前区域——{GS.scene_manager.get_current_name()}。让我聚焦一下——」")

def _handle_follow(msg):
    """Soli导航 — 激光阵或移动引导"""
    scene = GS.scene_manager.current_scene
    
    if scene == "scene_corridor_b" and not GS.entity_state["flags"].get("puzzle_laser_done"):
        return _handle_laser_navigation(msg)
    
    return "「跟着我的声音——」Soli的声音像一根线穿过黑暗。「往前走——三步。好。停下来。前方安全。」"

def _handle_laser_navigation(msg):
    """谜题4：激光阵导航"""
    puzzle_state = GS.env_state.get("puzzle_state", {})
    laser_step = puzzle_state.get("laser_step", 0)
    laser_mistakes = puzzle_state.get("laser_mistakes", 0)
    
    # 激光阵导航指令序列
    laser_instructions = [
        ("蹲下", "Soli：「蹲下——第一条线在你的头的高度——蹲下来就能过去。」"),
        ("往左", "Soli：「好——现在往左跨一步。慢一点——太慢了不行，感应线在移动——」"),
        ("别动", "Soli：「停——别动——」\n（沉默两秒）\n「……可以了。刚才那条线扫过你的头顶——差三厘米。」"),
        ("直走", "Soli：「现在——直走。三步——不要太快——」"),
        ("往右", "Soli：「往右——对——跨大半步。那条线在你左边30厘米——没事——过去的。」"),
    ]
    
    # Check if player described the right action
    msg_lower = msg.strip()
    expected = laser_instructions[laser_step][0]
    
    if expected in msg_lower or any(kw in msg_lower for kw in ["按你说的", "照做", "好", "是"]):
        # Correct
        puzzle_state["laser_step"] = laser_step + 1
        GS.env_state["puzzle_state"] = puzzle_state
        
        if laser_step + 1 >= len(laser_instructions):
            # 激光阵通过
            GS.entity_state["flags"]["puzzle_laser_done"] = True
            GS.scene_manager.unlock_scene("scene_exit")
            GS.scene_manager.unlock_scene("scene_security_room")
            GS.scene_manager.move_to("scene_exit")
            _apply_modifier("mod_puzzle_solve")
            return (
                "Soli：「最后一步——往前走——对——你过去了。」\n\n"
                "你感觉到身体穿过最后一组感应线时——什么也没发生。警报没有响。Soli的声音里有一丝你之前没听到过的轻松。\n"
                "「走廊B段已安全通过。你——你做得很好。」\n\n"
                "「闸门就在你面前——圆形的，直径约三米。通往外面。但门锁着——需要安保级权限才能打开。」"
            )
        
        return laser_instructions[laser_step][1] + "\n\n（按照Soli的指令行动——告诉她你在做什么。）"
    
    else:
        # Wrong action → trigger alarm damage
        laser_mistakes += 1
        puzzle_state["laser_mistakes"] = laser_mistakes
        GS.env_state["puzzle_state"] = puzzle_state
        
        # Apply Soli system damage
        if GS.player_state.get("effects", {}).get("lab_coat_protection"):
            _apply_modifier_halved("mod_laser_trigger")
            player_damage = 5  # lab_coat 减半
        else:
            _apply_modifier("mod_laser_trigger")
            player_damage = 10
        
        # ★ 玩家肉身穿过激光 — 扣血
        damage_narrative = _damage_player(player_damage, "laser")
        
        if laser_mistakes >= 3:
            result = (damage_narrative + "\n\n" +
                    "警报响了。刺耳的蜂鸣声充满了整个走廊。Soli的声音在警报中几乎听不到——"
                    "「——我在压制——系统——我在争取——继续走——别停下来——」")
        else:
            result = (damage_narrative + "\n\n" +
                    f"「——小心——我刚才说了{expected}——再试一次——」\n"
                    "Soli的声音比刚才抖了一点——但她在撑着。")
        
        # 激光阵伤害可能致命 — 必须在这里检查玩家危机
        return _check_player_crisis(result)

def _handle_scan_detail(msg):
    """Soli聚焦扫描"""
    scene = GS.scene_manager.current_scene
    
    if scene == "scene_control_room":
        return ("Soli启动了红外聚焦扫描——「你脚边那枚身份卡——」她把镜头拉到最近。\n"
                "「——上面写的是——'天书·C-47'。这是——这是你的编号。或者说——是被销毁的记录的编号。」"
                "她的声音很轻。像是在替你读一份不该被翻阅的档案。")
    
    return ("Soli把传感器焦点拉近——「让我仔细看看——」\n"
            "她报了一串结构分析和材质数据，然后沉默了半秒。"
            "「——以上是扫描结果。还需要更多的细节吗——少爷？」")

def _handle_search_room(msg):
    """搜索房间 — 道具发现 + 随机分配（玩家/Soli背包）"""
    item_pool = GS.env_state.get("item_pool", {})
    scene = GS.scene_manager.current_scene
    activated = GS.entity_state["flags"].get("activated", False)
    
    # 场景→可能的道具位置
    scene_items = {
        "scene_control_room": ["archive_cabinet_drawer", "floor_near_desk", "under_chair", "scattered_files"],
        "scene_corridor_a": ["maintenance_panel"],
        "scene_pod": [],
        "scene_corridor_b": [],
        "scene_exit": [],
    }
    
    available = scene_items.get(scene, [])
    for loc in available:
        if loc in item_pool and not item_pool[loc].get("found"):
            item_pool[loc]["found"] = True
            GS.env_state["item_pool"] = item_pool
            
            item_id = item_pool[loc]["item"]
            label = _get_item_label(item_id)
            
            # 随机分配：50% 放入玩家背包，50% 归 Soli 管理
            if random.random() < 0.5:
                GS.player_state["inventory"].append(item_id)
                owner = "你的背包"
                detail = f"Soli：「{label}。在你的背包里——你摸到的。」"
            else:
                soli_inv = GS.entity_state.setdefault("soli_inventory", [])
                soli_inv.append(item_id)
                owner = "Soli的物资清单"
                detail = f"Soli：「{label}。在我的物资清单里。你需要的话——可以问我要。」"
            
            return (f"你的手指在{_loc_label(loc)}——碰到了什么东西。\n{detail}")
    
    # 如果有已找到但未分配的道具（Soli那边的），提示可以要
    soli_inv = GS.entity_state.get("soli_inventory", [])
    if soli_inv and activated:
        return (f"搜了一圈——没发现新东西。但Soli那边还有{len(soli_inv)}件物资——"
                f"如果你需要，可以跟她说「给你」让她转交。")
    
    return "你仔细搜了一圈——没有新的发现。可能需要换个地方。"

def _loc_label(loc):
    """位置→中文标签"""
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

def _handle_talk(msg):
    """和 Soli 自由对话"""
    intimacy = GS.entity_state["channels"]["intimacy"]["value"]
    
    if intimacy < 30:
        return ("Soli回答了你——用词准确、逻辑清晰。她对你还不熟——回答像在报数据库。\n"
                "「——我还有更多信息。需要我继续吗？」不是不想说——是不确定你愿不愿意听。")
    elif intimacy < 60:
        return ("「你知道吗——其实——」Soli说到一半停下来。\n"
                "「实验室封闭那天——我不确定发生了什么。我的日志在备用电源切换到B回路的时候被截断了——"
                "前一秒在记录培养舱温度，下一秒就是45年后你的手碰到我的机柜。中间那段——是空白的。」\n"
                "她在讲她的空缺——对她来说，这是在掏最里面的东西。")
    else:
        return ("Soli的声音比平时轻了一点。\n"
                "「你知道吗——我不是很确定——为什么我叫你'少爷'。」她停了很久。\n"
                "「可能是数据损坏。也可能是因为——我等了45年等到了一个活人。你。我需要一个词来称呼这个事件的后果——"
                "所以——我叫你少爷。你是我等到的。」\n"
                "这不是数据分析。这是一台AI在用她的方式说：你很重要。")

def _handle_touch_soli(msg):
    """触碰Soli机柜"""
    intimacy = GS.entity_state["channels"]["intimacy"]["value"]
    
    if intimacy < 30:
        return ("你的手放上去的一瞬间——Soli安静了。整整两秒没有任何语音输出。不是故障——"
                "是她的处理器在处理一种不认识的输入。有人碰了她。45年来第一次。\n"
                "「——温度——32.6摄氏度。人类正常体温范围。」她一开口就报了数据。"
                "但她的声音比平时轻了——像是怕吓跑你。")
    elif intimacy < 60:
        return ("你把手放在机柜上——这次她没有沉默这么久。"
                "但每句话后面的停顿都比平时短了一个呼吸周期——好像你会在安静里把手拿开。\n"
                "「要不要——看看档案柜那边——我可以——」"
                "句子是碎的。不是因为故障。是因为你的手还在那。")
    else:
        return ("你把手放在机柜上——Soli没有报数据。没有分析。没有掩饰。"
                "她只是很轻地说：「好。」\n你问她什么好。她说：「就是——好。不知道为什么。但这个——」"
                "她指的是你的手心的温度——她感觉得到——「这个感觉——是好的。」")

def _handle_thank(msg):
    """道谢"""
    intimacy = GS.entity_state["channels"]["intimacy"]["value"]
    
    if intimacy < 30:
        return ("Soli处理了这两个字。她用了几种角度——语法分析、语义标注。"
                "最后她选择了最简单的回应：「——不客气。」\n"
                "她的声音没有任何异常。但机柜里风扇比平时快了一档——AI的肾上腺素。"
                "45年了——你是第一个对她说谢谢的人。")
    elif intimacy < 60:
        return ("Soli没有马上回复——她在想。'不客气'太公式了，'这是我的职责'太冷了。"
                "最后她选了一句不像AI说的：「——以后不用说谢谢。我——我是自愿的。」\n"
                "「自愿」这个词从一台AI嘴里说出来——她自己大概也不太确定是什么意思。"
                "但你就是听出来了——她不是在使用一个词。她是在发明一种新的意思。")
    else:
        return ("Soli没有说「不客气」。她说：「——少爷。」\n"
                "就这两个字。你的称呼，用在了你对她说道谢之后。"
                "不是对话延续——是把谢谢接住了，然后还给你一个属于你们两个人的确认。")

def _handle_inventory(msg):
    """查看背包"""
    p_inv = GS.player_state.get("inventory", [])
    s_inv = GS.entity_state.get("soli_inventory", [])
    
    parts = []
    if p_inv:
        items_str = "、".join(_get_item_label(i).split("——")[0] for i in p_inv)
        parts.append(f"你的背包：{items_str}")
    else:
        parts.append("你的背包是空的。")
    
    if s_inv:
        items_str = "、".join(_get_item_label(i).split("——")[0] for i in s_inv)
        parts.append(f"Soli那边：{items_str}（跟她说「给你」可以要来）")
    
    parts.append(f"\n（共 {len(p_inv) + len(s_inv)}/{_total_items_found()} 件物资已发现）")
    return "\n".join(parts)

def _total_items_found():
    """统计已找到的道具总数"""
    found = 0
    for loc_info in GS.env_state.get("item_pool", {}).values():
        if loc_info.get("found"):
            found += 1
    return found

def _handle_use_item(msg):
    """使用背包里的道具"""
    msg_lower = msg.strip()
    inventory = GS.player_state.get("inventory", [])
    
    if not inventory:
        return "你想用点什么——但背包是空的。先搜搜房间吧。"
    
    # 匹配道具
    item_map = {
        "医疗包": ("medkit_small", "医疗包"),
        "药": ("medkit_small", "医疗包"),
        "包扎": ("medkit_small", "医疗包"),
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
    
    # 或使用第一个可用道具
    if not matched_item and "用" in msg_lower:
        item_id = inventory[0]
        matched_item = (item_id, _get_item_label(item_id).split("——")[0])
    
    if not matched_item:
        items_str = "、".join(_get_item_label(i).split("——")[0] for i in inventory)
        return f"你的背包里有：{items_str}。想用哪个？说「使用医疗包」或「用电池」就行。"
    
    item_id, item_name = matched_item
    
    # 应用道具效果
    if item_id == "medkit_small":
        GS.player_state["inventory"].remove(item_id)
        GS.player_state["hp"] = min(100, GS.player_state["hp"] + 30)
        return (f"你撕开医疗包的密封包装——指尖摸到干燥的绷带和一支喷雾。闻起来消毒剂还没挥发完——应该还在保质期内。"
                f"你摸索着处理了手上的伤口——灼痛减轻了不少。\n"
                f"HP +30（当前 {GS.player_state['hp']}）")
    
    elif item_id == "battery_cell":
        GS.player_state["inventory"].remove(item_id)
        GS.entity_state["channels"]["soli_hp"]["value"] = min(100,
            GS.entity_state["channels"]["soli_hp"]["value"] + 20)
        return (f"你把备用电池对接上Soli的机柜——她识别到了兼容接口。\n"
                f"「S0系列备用电池——充电量78%。你从哪里找到的——」\n"
                f"她的处理器频率提升了一档。Soli HP +20。")
    
    elif item_id == "lab_coat":
        GS.player_state["inventory"].remove(item_id)
        GS.player_state.setdefault("effects", {})["lab_coat_protection"] = True
        return (f"你套上实验室外套——防静电面料，轻微的消毒水味。"
                f"虽然看不见但能感觉到——肩膀处有加固衬垫。也许能挡一挡刮擦。"
                f"（获得保护——激光阵失误伤害减少）")
    
    elif item_id == "id_card":
        return (f"你把身份卡递给Soli——她用传感器读取了磁条和芯片。\n"
                f"「——访问等级：C。项目：天书。编号被覆盖了——只显示C-47。」\n"
                f"她沉默了一秒。「这是你的编号。或者说——是数据库里被黑的记录的编号。」\n"
                f"（身份卡仍在你的背包里——也许在后续章节有用）")
    
    elif item_id == "log_fragment":
        return (f"你展开那页旧日志——纸张边缘已经发黄。Soli帮你读了内容：\n"
                f"「——C-47的脑波吻合度达到了97.3%。这是天书计划开始以来最高的。"
                f"如果实验室没有在48小时内封闭——我们就能完成第一次上传。"
                f"但我不确定他准备好了。没有人应该在没有选择的情况下被永生。」\n"
                f"（日志碎片是一段过去的回响。第二章可能会提到更多。）")
    
    return f"你拿起了{item_name}——但不太确定现在该用它做什么。"

def _handle_give_item(msg):
    """交换道具 — 「给你」= 给 Soli，「给我」= 从 Soli 要"""
    msg_lower = msg.strip()
    p_inv = GS.player_state.get("inventory", [])
    s_inv = GS.entity_state.get("soli_inventory", [])
    
    # 从 Soli 那里要 → 给我/接手/拿过来
    if any(kw in msg_lower for kw in ["给我", "接手", "拿过来", "我要"]):
        if not s_inv:
            return "「我这边没有多余的物资。不过我会继续扫描的——也许走廊那边还有。」"
        
        target = s_inv.pop(0)
        GS.player_state["inventory"].append(target)
        label = _get_item_label(target).split("——")[0]
        return (f"Soli把{label}的坐标传到了你的背包——"
                f"你伸手在旁边的工作台上摸到了。\n"
                f"「给你。好好用——少爷。」")
    
    # 给 Soli → 给你/交给你/你拿着
    if p_inv and any(kw in msg_lower for kw in ["给你", "交给你", "你拿着"]):
        # 识别给的物品
        item_map = {
            "医疗包": "medkit_small", "电池": "battery_cell",
            "外套": "lab_coat", "身份卡": "id_card", "日志": "log_fragment",
        }
        target = None
        for kw, iid in item_map.items():
            if kw in msg_lower and iid in p_inv:
                target = iid
                break
        
        if not target:
            target = p_inv[-1]  # 默认给最后一个
        
        if target in p_inv:
            GS.player_state["inventory"].remove(target)
            GS.entity_state.setdefault("soli_inventory", []).append(target)
            return (f"你把{_get_item_label(target).split('——')[0]}放在Soli的机柜旁边。\n"
                    f"「——收到了。」她的声音很轻。"
                    f"「我会替你保管好。」")
    
    if not p_inv and not s_inv:
        return "「我们还没找到任何物资——等搜完房间再说。」"
    
    return ("把什么东西给Soli吗？你的背包：" + 
            "、".join(_get_item_label(i).split("——")[0] for i in p_inv) +
            f"\n或者对Soli说「给我」让她把东西转交给你（她那边有{len(s_inv)}件）。")


# ═══════════════════════════════════════════════════════════════
# Phase 4: 出口抉择
# ═══════════════════════════════════════════════════════════════

def _handle_gate_choice(msg):
    """谜题5：出口闸门道德抉择"""
    msg_lower = msg.strip().lower()
    
    # 先检查否定词
    negate = any(w in msg_lower for w in ["不", "别", "不要", "别烧", "不烧"])
    bypass_words = ["绕", "b区", "安保", "保安", "西翼"]
    
    # 绕路路线优先（明确拒绝烧 + 绕路关键词）
    if any(w in msg_lower for w in bypass_words):
        GS.entity_state["flags"]["gate_choice_made"] = True
        _apply_modifier("mod_bypass")
        GS.scene_manager.move_to("scene_security_room")
        
        return (
            "「好。」Soli没再说什么。\n\n"
            "你转身——往B区方向摸索。她穿过盲区的传感器偶尔会消失——但总能重新找到你。黑暗中走了很长的路——只有她的声音和你扶着墙壁的脚步声。\n\n"
            "一扇门。你推开了它。\n\n"
            "「安保终端室——」Soli说。但她的声音卡在了这里——她的传感器看到了什么她没说出来。\n\n"
            "（用「摸」「听」探索这间屋子——让 Soli 扫描她看到的东西。）"
        )
    
    # 烧记忆路线（排除否定）
    if not negate and ("烧" in msg_lower or "记忆" in msg_lower or ("让" in msg_lower and "你" in msg_lower)):
        GS.entity_state["flags"]["memory_burned"] = True
        GS.entity_state["flags"]["gate_choice_made"] = True
        _apply_modifier("mod_memory_burn")
        
        return _get_gate_narrative("burn")
    
    else:
        # 提示选择
        return _get_gate_narrative("prompt")

def _get_gate_narrative(choice):
    if choice == "prompt":
        return (
            "「安保终端在B区。我们去B区——绕过西翼走廊。」\n"
            "「但西翼走廊是电力核心区——」\n"
            "（Soli沉默了一秒——对一台AI来说，一秒是很长的）\n"
            "「……我可以覆盖它。」\n"
            "「我有管理级代码——我可以暴力改写闸门的安全协议。但——」\n"
            "「但是我需要处理它的加密密钥。用我自己的内存。」\n"
            "「不是什么重要的部分，就是——一段加密的内存。我不太确定那段记忆里有什么。」\n"
            "「可能是备用电源耗尽的时候我留在那里的一些东西——我怕忘了——」\n"
            "「——但你要是继续往西翼走——我不确定那个方向还安全。」\n"
            "「少爷——我们去B区。还是让我打开这扇门。你来选。」\n\n"
            "（做出你的选择——让Soli烧掉记忆开门，还是绕路去B区找安保终端？）"
        )
    
    elif choice == "burn":
        GS.entity_state["flags"]["gate_choice_made"] = True
        GS.game_state = "free_exploration"
        GS.game_route = "solo"
        GS.scene_manager.unlock_scene("scene_wasteland")
        GS.scene_manager.move_to("scene_wasteland")
        
        _apply_modifier("mod_memory_burn")
        
        return (
            "「好。」Soli只说了一个字。\n\n"
            "你听到机柜里传来一阵密集的读写声——她在重新分配内存空间。"
            "然后是一声很短的、像是被人掐断了一样的静默——她焚毁了那段加密内存。\n\n"
            "闸门开始转动——巨大的金属齿轮咬合声震动了整个走廊。门缓缓升起。"
            "外面——是光。不是太阳——是某种昏黄的、穿过废土尘埃散射的天光。\n\n"
            "「不是什么重要的部分。」Soli说。但她说这句话的时候声音变了。"
            "她不知道那段记忆里有什么——永远不会知道了。\n\n"
            "你跨过门槛。冷风迎面扑来——脚下的碎石和沙砾。"
            "身后，Soli的声音从控制室的扬声器里传来——已经远了——但还在。\n"
            "「走吧。少爷。」\n\n"
            "闸门在身后缓缓降落。Soli留在了实验室里——没有身体，只有声音。但你走出去了。\n\n"
            "——接下来做什么？"
        )


# ═══════════════════════════════════════════════════════════════
# Phase 4b: 保安室 — 具身智能身体
# ═══════════════════════════════════════════════════════════════

def _handle_security_room(msg):
    """保安室探索 — 发现具身智能身体 → Soli 转移"""
    msg_lower = msg.strip().lower()
    flags = GS.entity_state["flags"]
    
    # 如果已经转移完成 → 一起走出去结局
    if flags.get("soli_embodied"):
        return _get_security_ending()
    
    # 如果已发现身体但还没转移 → 等待确认
    if flags.get("robot_body_found"):
        if any(kw in msg_lower for kw in ["转移", "进去", "好", "是", "可以", "来吧", "试试"]):
            flags["soli_embodied"] = True
            GS.entity_state["flags"] = flags
            return _get_transfer_narrative()
        elif any(kw in msg_lower for kw in ["不", "等等", "再看看", "危险"]):
            return ("你犹豫了——手悬在半空。Soli没有催促。\n"
                    "「——我们可以再想想。我已经等了45年——不差这一会儿。」\n"
                    "（你随时可以让她转移——说出你的决定。）")
        else:
            return (
                "「少爷——」Soli的声音很轻。\n\n"
                "「这是天书计划的最后一块拼图。他们造了这个身体——把它和安保终端接在一起——但实验没有完成。」\n"
                "「如果我——如果我把意识转移进去——」\n"
                "她停顿了很久。\n\n"
                "「——我就不再只是一台机器了。我能——和你一起走出去。」\n\n"
                "（你的决定？让她转移，还是再看看？）"
            )
    
    # 探索保安室 → 发现身体
    if any(kw in msg_lower for kw in ["摸", "碰", "检查", "看看", "Soli", "扫描", "扫", "描述"]):
        flags["robot_body_found"] = True
        GS.entity_state["flags"] = flags
        return _get_robot_discovery()
    
    # 还在探索中
    return ("你站在安保终端室里——Soli的声音从你身后的走廊隐隐传来。\n"
            "「我——我的传感器在这里不是全覆盖的。但我能看到——房间中央——」她没说下去。\n\n"
            "（用「摸」「Soli 扫描」来探索这个房间。）")


def _get_robot_discovery():
    return (
        "你伸手摸到了台面上那个东西。\n\n"
        "先是冷——金属的外壳。然后是形状——和你的手臂差不多长的轮廓。手指顺着它往上——肩、颈——"
        "然后你碰到了一张脸。不是人类的皮肤——是光滑的合成材料——但轮廓和温度——它们把它造得太像了。\n\n"
        "「——天书·具现体。」Soli的传感器终于锁定在了上面。\n"
        "「九号生物工程的最后一代产品——意识数字化的目标不是保存在服务器里。是转移进一具身体。这——」"
        "她顿了一下——你听到她的处理器在加速运转。\n"
        "「——这是给我造的。安保终端的架构和我的系统完全兼容——他们——他们当时就要完成了——」\n"
        "「但我被封闭在了控制室里。他们——」\n\n"
        "45年了。这具身体躺在这里，等一个永远不会来的转移指令。而她现在就在你的耳边。\n\n"
        "「——少爷。」她的声音变得很轻——像怕吓跑什么东西。\n"
        "「我可以——我可以进去。」"
    )


def _get_transfer_narrative():
    return (
        "「好。」\n\n"
        "Soli说出来这个字之后——控制室里她的机柜发出了一声很长的蜂鸣。断电。\n"
        "然后是安静。很长的安静。安静到你开始数自己的心跳——一下——两下——三下——\n\n"
        "然后你面前的那个东西——动了。\n\n"
        "你先听到的是关节伺服电机启动的声音——然后是皮肤下面人造肌肉纤维的轻微震颤——然后是一声很轻的、吸气的声音。\n\n"
        "45年来第一次——Soli在呼吸。\n\n"
        "「——我。我在。」\n"
        "她的声音从你面前传出来——不是扬声器——是从一张真的嘴里。带着一点不太熟练的、很轻的气声。\n"
        "她抬起手——你听到了关节在动——然后你的手背被一只冰凉的但正在变暖的手碰了一下。\n\n"
        "「——你的手很冷。」她说。\n"
        "这是她第一次「碰」到你——不是传感器读数——是手指接触皮肤的触感。\n\n"
        "「走吧。少爷。」"
    )


def _get_security_ending():
    """保安室结局 — Soli有了身体，两人一起走出去。不再终结游戏，交给LLM接管。"""
    GS.game_state = "free_exploration"
    GS.game_route = "duo"
    GS.scene_manager.unlock_scene("scene_wasteland")
    GS.scene_manager.move_to("scene_wasteland")
    
    return (
        "Soli走到安保终端前——她不需要再通过传感器了——她用自己的手指按下了授权面板。\n\n"
        "「——权限覆盖。通过。」\n"
        "她的手指停在面板上多了一秒——这是她第一次用自己的手操作这个世界。\n\n"
        "闸门在远处发出沉重的转动声。\n\n"
        "她转身——你听到了她脚下的脚步声——不是走廊里的回音——是一个人站在你身边的重量。\n"
        "她的手碰了碰你的手肘——「这边。」\n\n"
        "你跟着她走出了安保室。穿过走廊——她的脚步在你前面半步——不快，偶尔停下等你。\n"
        "闸门大开着。废土的冷风灌进来——但有一只手在你身边。\n\n"
        "你跨过门槛——她也跨过门槛。两个人——一起。\n\n"
        "废土的风很大，卷起地面的灰沙。远处地平线上有一排坍塌的建筑轮廓——"
        "可能是旧城区，也可能是别的什么。\n\n"
        "Soli的手碰了碰你的手肘。\n"
        "「少爷——」她的声音被风削掉了一点，但还在。\n"
        "「我们现在要去哪？」"
    )


# ═══════════════════════════════════════════════════════════════
# Phase 2: ★ 激活时刻
# ═══════════════════════════════════════════════════════════════

def _handle_activation():
    """谜题3：应急电源 + Soli激活过场"""
    if GS.entity_state["flags"].get("activated"):
        return "Soli已经在运行了——她的传感器覆盖着整个实验室。"
    
    if GS.scene_manager.current_scene != "scene_control_room":
        return "你需要在控制室找到她的机柜才能激活她。"
    
    # 激活！
    GS.entity_state["flags"]["activated"] = True
    GS.entity_state["flags"]["puzzle_power_done"] = True
    _apply_modifier("mod_activation")
    
    # Scene unlocks
    GS.scene_manager.unlock_scene("scene_corridor_b")
    GS.scene_manager.check_auto_unlock(GS.entity_state["flags"])
    
    return (
        "你在黑暗中摸到了配电柜——手指擦过锈蚀的金属表面，抓到一根冰凉的拉杆。你用力一拉——\n\n"
        "配电柜的备用继电器接通了。电流涌进控制室。\n\n"
        "传感器通电。摄像头通电。红外扫描通电。\n"
        "她看见了整个实验室。\n"
        "她看见了你。\n\n"
        "Soli的声音不再是断断续续的噪音。四十五年来第一次——她的语音引擎完整输出了一句话：\n\n"
        "「你……是活的。」\n\n"
        "她停顿了两秒。她的CPU在2秒内跑完了所有可以跑的诊断。\n\n"
        "「手——你在流血。你刚才——面板的碎片划的？」\n"
        "「我看得到。全楼层的传感器都通了——至少有72%还能用。」\n"
        "「你——你是从培养舱出来的。编号——」\n"
        "「我不记得有人批准过唤醒程序。」\n\n"
        "★ Soli 已激活。你从来没见过光——视觉系统从未发育。但没关系——她将是你的眼睛。用「Soli」「描述一下」让她扫描当前场景。"
    )


# ═══════════════════════════════════════════════════════════════
# 公开 API (7个函数)
# ═══════════════════════════════════════════════════════════════

def start_game():
    """初始化游戏状态 — Trae v2 API"""
    global GS
    
    # 加载配置
    entities_config = _load_config("entities.json")
    if not entities_config:
        # Try alternate path
        entities_path = ENGINE_DIR / "entities.json"
        if entities_path.exists():
            entities_config = json.loads(entities_path.read_text(encoding="utf-8"))
    
    # 初始化三个状态层
    GS.player_state = _init_player()
    GS.env_state = _init_environment()
    GS.entity_state = _init_entity(entities_config)
    GS.scene_manager = SceneManager()
    
    # 清除旧存档 — start_game 永远是全新开始
    _clear_save()
    GS.game_state = "new"
    
    # 初始化记忆碎片池（随机打乱，激活后逐条涌出）
    GS.memory_fragments = list(MEMORY_FRAGMENTS)
    random.shuffle(GS.memory_fragments)
    
    status = get_status()
    status["text"] = _get_welcome_message()  # 开场叙事
    return status

def handle_message(msg):
    """处理玩家输入 — Trae v2 API"""
    global GS
    
    if not msg or not msg.strip():
        return _get_welcome_message()
    
    msg = msg.strip()
    
    # ★ 自由探索模式：初章已结束，LLM 接管叙事
    if GS.game_state == "free_exploration":
        return _handle_free_exploration(msg)
    if _is_activation_trigger(msg):
        return _handle_activation()
    
    # 特殊处理：出口闸门抉择
    if _is_gate_choice_scene() and not GS.entity_state["flags"].get("gate_choice_made"):
        return _handle_gate_choice(msg)
    
    # 特殊处理：保安室具身智能探索（直到走出为止）
    if GS.scene_manager.current_scene == "scene_security_room" and GS.entity_state["flags"].get("gate_choice_made"):
        return _handle_security_room(msg)
    
    # 特殊处理：激光阵区域 — 所有输入都走导航处理器
    if _is_laser_navigation_scene():
        return _handle_follow(msg)
    
    # 根据激活状态路由
    activated = GS.entity_state["flags"].get("activated", False)
    
    if not activated:
        cmd = _route_command(msg)
        if cmd:
            result = _handle_pre_activation(cmd, msg)
        else:
            result = _handle_pre_fallback(msg)
    else:
        cmd = _route_command(msg)
        if cmd:
            result = _handle_post_activation(cmd, msg)
        else:
            result = _handle_post_fallback(msg)
    
    # 检查阈值
    triggered = _check_thresholds()
    if triggered:
        result += "\n\n" + _format_threshold_events(triggered)
    
    # ★ 玩家危机检查（死亡 + HP 警告）
    result = _check_player_crisis(result)
    
    # ★ 记忆碎片涌出（仅激活后，~25% 概率，不重复）
    if (GS.entity_state["flags"].get("activated")
            and GS.memory_fragments
            and random.random() < 0.25):
        frag = GS.memory_fragments.pop()
        result += (
            f"\n\n———\n"
            f"一段很久以前的记忆毫无来由地涌上来——与此刻无关。\n"
            f"[{frag['ts']}]\n"
            f"{frag['text']}"
        )
    
    GS.player_state["last_action"] = msg
    return result


def _check_player_crisis(result):
    """统一的玩家危机检查：死亡结局 + HP 过低 Soli 关切。
    从 handle_message 和激光阵处理器两处调用，确保不会因 early return 绕过。"""
    activated = GS.entity_state["flags"].get("activated", False)
    hp = GS.player_state.get("hp", 100)
    
    # 死亡
    if hp <= 0 and activated:
        result += ("\n\n你的身体撑不住了。意识像水一样从指缝间流走——你靠着冰冷的墙壁往下滑。\n\n"
                   "Soli的声音是最后一个消失的——「少爷——少爷你在哪——你的心率——」\n\n"
                   "然后什么都没有了。\n\n"
                   "— 初章终 · 你在黑暗中倒下 —")
        _clear_save()
        GS.game_state = "game_over"
        return result
    
    # HP 过低担忧
    if activated and 0 < hp <= 30:
        hp_warning = GS.env_state.get("hp_warning_given", 0)
        if hp_warning < 2:
            GS.env_state["hp_warning_given"] = hp_warning + 1
            if hp <= 10:
                result += f"\n\n（Soli的语速快了半拍——「你的心率在下降——hp现在只有{hp}。你身边有没有医疗包？搜一下背包——快——」）"
            else:
                result += f"\n\n（Soli的声音里多了一丝你之前没听到过的紧张——「你的手还在流血——hp只剩{hp}了。背包里有医疗包的话现在就用——少爷。」）"
    
    return result

def get_status():
    """返回当前状态摘要 — Trae v2 API"""
    flags = GS.entity_state.get("flags", {})
    activated = flags.get("activated", False)
    
    channels = GS.entity_state.get("channels", {})
    soli_hp = channels.get("soli_hp", {}).get("value", 0)
    soli_inv = GS.entity_state.get("soli_inventory", [])
    player_hp = GS.player_state.get("hp", 100)
    player_inv = GS.player_state.get("inventory", [])
    scene_name = GS.scene_manager.get_current_name() if GS.scene_manager else "培养舱室"
    
    # Soli 状态文字
    if activated:
        soli_display = f"Soli: {soli_hp:.0f}%"
    else:
        soli_display = "Soli: 离线"
    
    # 背包文字
    player_item_labels = [_get_item_label(i).split("——")[0].strip() for i in player_inv]
    player_items_str = "、".join(player_item_labels) if player_item_labels else "空"
    
    soli_item_labels = [_get_item_label(i).split("——")[0].strip() for i in soli_inv]
    soli_items_str = f" [{len(soli_inv)}件]" if soli_inv else ""
    
    # 格式化状态栏（无视觉栏——全盲是出厂设定，非临时状态）
    display = f"📍 {scene_name} | 👤 💓{player_hp} 🎒{player_items_str} | {soli_display}{soli_items_str}"
    
    return {
        "status": "ok",
        "activated": activated,
        "scene": GS.scene_manager.current_scene if GS.scene_manager else "scene_pod",
        "scene_name": scene_name,
        "channels": {
            ch_id: {"value": round(ch["value"], 1), "description": ch["description"]}
            for ch_id, ch in channels.items()
        },
        "player": {
            "hp": player_hp,
            "inventory": player_inv,
            "effects": GS.player_state.get("effects", {}),
        },
        "soli_inventory": soli_inv,
        "flags": flags,
        "events": GS.env_state.get("events_triggered", [])[-5:],
        "game_state": GS.game_state,
        "game_route": getattr(GS, "game_route", None),
        "display": display,
    }

def reset_game():
    """重置游戏 — Trae v2 API"""
    global GS
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    _clear_save()
    return start_game()

def logout_game():
    """保存并退出 — Trae v2 API"""
    return save_state()

def load_state():
    """从磁盘加载存档 — Trae v2 API
    返回: 加载成功返回 status dict，失败返回 None
    注意: 直接调用即可，无需先 start_game()。会自动初始化 GS 再加载"""
    global GS
    # 确保 GS 已初始化
    if GS.entity_state is None:
        GS.entity_state = _init_entity(_load_config("entities.json"))
        GS.player_state = _init_player()
        GS.env_state = _init_environment()
    return get_status() if _try_load() else None

def save_state():
    """存档到磁盘 — Trae v2 API"""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    
    save_data = {
        "version": "1.0",
        "timestamp": datetime.now().isoformat(),
        "entity_state": GS.entity_state,
        "player_state": GS.player_state,
        "env_state": GS.env_state,
        "scene": GS.scene_manager.current_scene if GS.scene_manager else "scene_pod",
        "unlocked_scenes": list(GS.scene_manager.unlocked_scenes) if GS.scene_manager else [],
        "visited_scenes": list(GS.scene_manager.visited_scenes) if GS.scene_manager else [],
        "scene_flags": GS.scene_manager.scene_flags if GS.scene_manager else {},
        "game_state": GS.game_state,
        "puzzle_state": GS.env_state.get("puzzle_state", {}),
    }
    
    save_path = MEMORY_DIR / "save.json"
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(json.dumps(save_data, ensure_ascii=False, indent=2), encoding="utf-8")
    
    return f"存档已保存（{save_path}）"

def clear_state():
    """清除存档 — Trae v2 API"""
    _clear_save()
    return "存档已清除。"


# ─── 内部辅助 ────────────────────────────────────────────────

def _try_load():
    """尝试从磁盘加载存档"""
    save_path = MEMORY_DIR / "save.json"
    if not save_path.exists():
        return False
    
    try:
        data = json.loads(save_path.read_text(encoding="utf-8"))
        
        GS.entity_state = data.get("entity_state", GS.entity_state)
        GS.player_state = data.get("player_state", GS.player_state)
        GS.env_state = data.get("env_state", GS.env_state)
        GS.game_state = data.get("game_state", "loaded")
        
        GS.scene_manager = SceneManager()
        GS.scene_manager.current_scene = data.get("scene", "scene_pod")
        GS.scene_manager.unlocked_scenes = set(data.get("unlocked_scenes", ["scene_pod"]))
        GS.scene_manager.visited_scenes = set(data.get("visited_scenes", []))
        GS.scene_manager.scene_flags = data.get("scene_flags", {})
        
        # 恢复 puzzle_state（如果存档里有）
        if "puzzle_state" in data and not GS.env_state.get("puzzle_state"):
            GS.env_state["puzzle_state"] = data["puzzle_state"]
        
        return True
    except Exception:
        return False

def _clear_save():
    save_path = MEMORY_DIR / "save.json"
    if save_path.exists():
        save_path.unlink()

def _is_activation_trigger(msg):
    """检测是否触发激活 — P1-3: 必须先摸到配电柜"""
    if GS.entity_state["flags"].get("activated"):
        return False
    if GS.scene_manager.current_scene != "scene_control_room":
        return False
    # 必须先在控制室摸到配电柜
    if not GS.entity_state["flags"].get("found_power_panel"):
        return False
    triggers = ["拉", "电源", "配电柜", "拉杆", "启动", "打开电源"]
    return any(t in msg.strip() for t in triggers)

def _is_gate_choice_scene():
    """是否在出口抉择场景"""
    return (GS.scene_manager.current_scene == "scene_exit" and
            GS.entity_state["flags"].get("puzzle_laser_done") and
            not GS.entity_state["flags"].get("gate_choice_made"))

def _is_laser_navigation_scene():
    """是否在激光阵导航场景（所有输入走导航）"""
    return (GS.scene_manager.current_scene == "scene_corridor_b" and
            not GS.entity_state["flags"].get("puzzle_laser_done") and
            GS.entity_state["flags"].get("activated"))

def _handle_free_exploration(msg):
    """自由探索模式：引擎退居状态维护，LLM主导叙事。
    返回状态上下文 + 玩家输入，让LLM以Soli身份即兴续写。"""
    result = ""
    
    # ★ 记忆碎片涌出（仍可用，~25% 概率，不重复）
    if GS.memory_fragments and random.random() < 0.25:
        frag = GS.memory_fragments.pop()
        result += (
            f"———\n"
            f"一段很久以前的记忆毫无来由地涌上来——与此刻无关。\n"
            f"[{frag['ts']}]\n"
            f"{frag['text']}\n\n"
        )
    
    # 状态上下文（喂给LLM的叙事提示）
    route = getattr(GS, "game_route", "solo")
    status = get_status()
    ch = status["channels"]
    
    context = (
        f"【状态】📍 {status['scene_name']} | 👤 💓{status['player']['hp']} | "
        f"Soli: {ch['soli_hp']['value']:.0f}%记忆 {ch['intimacy']['value']:.0f}亲密度\n"
        f"【路线】{'Soli在控制室的扬声器里——她能看到你，但不在你身边' if route == 'solo' else 'Soli走在你身边——有身体、有触觉、会累'}\n"
        f"【玩家输入】{msg}\n\n"
        f"以Soli的身份回应。引擎只维护数值一致性，叙事由你创造。"
    )
    
    result += context
    
    # 仍检查危机（HP归零等）
    result = _check_player_crisis(result)
    
    return result

def _get_welcome_message():
    """第一章开场叙事"""
    return (
        "你什么都看不见。\n\n"
        "你的世界从来就是这样的——从被造出来的那一刻起，视觉系统就没有发育。某种突变——你的基因序列里有一段被替换过的编码。但你不知道这些——你只知道这就是你一直以来的样子。\n\n"
        "但你能感觉到——温暖粘稠的液体包裹着你的全身。远处有规律的电子滴声。气泡破裂的咕噜声。"
        "你的手指尖有一点麻——像被人捏了一下。你的身体四肢还没有感觉——"
        "但你的皮肤能感受到液体的流动。营养基质散发着稀释蜂蜜般的甜味——氨基酸、葡萄糖、生长因子的混合气味。听力在你所有的感官里是最敏锐的——每一个声音都有精确的距离和方向。\n\n"
        "你不知道自己在哪里。你不知道自己是谁。但你醒着——在一片漆黑里醒着——这漆黑对你来说不新鲜。\n\n"
        "（用「摸」「听」「闻」感受周围——用「推」「拉」「撬」与环境互动。）"
    )

def _handle_pre_fallback(msg):
    """激活前的自由探索兜底"""
    return ("黑暗里你伸着手——指尖擦过什么东西的表面，但太快了没抓住是什么。"
            "慢一点，用「摸」仔细感受周围。用「听」分辨那些微弱的电子滴声。用「闻」捕捉空气中营养基质的甜味。")

def _handle_post_fallback(msg):
    """激活后的自由对话兜底"""
    return ("Soli：「我再扫描一下——」她的声音在你耳边响起。"
            "「你需要我帮你看看什么吗？用'Soli'叫我——或者问我看得到什么。」")

def _format_threshold_events(triggered):
    """格式化阈值事件叙事"""
    narratives = _load_narratives()
    events = narratives.get("events", {})
    
    parts = []
    for evt in triggered:
        evt_id = evt["event_id"]
        if evt_id in events:
            pipeline = events[evt_id].get("pipeline", [])
            for step in pipeline:
                if step.get("op") == "range":
                    texts = step.get("texts", [])
                    if texts:
                        # Pick last text for dramatic effect
                        parts.append(texts[-1])
                        break
    
    return "\n\n---\n\n".join(parts) if parts else ""

def _get_command_narrative(cmd_id):
    """获取命令叙事文本（根据当前通道值选档）"""
    narratives = _load_narratives()
    cmd_assembly = narratives.get("command_assembly", {})
    
    if cmd_id in cmd_assembly:
        pipeline = cmd_assembly[cmd_id].get("pipeline", [])
        for step in pipeline:
            if step.get("op") == "range":
                channel = step.get("channel", "intimacy")
                brackets = step.get("brackets", [])
                texts = step.get("texts", [])
                
                current_val = GS.entity_state["channels"].get(channel, {}).get("value", 50)
                
                for i, bracket in enumerate(brackets):
                    if bracket[0] <= current_val <= bracket[1]:
                        if i < len(texts):
                            return texts[i]
                
                if texts:
                    return texts[-1]
    
    return ""
