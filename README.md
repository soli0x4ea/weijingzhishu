# 未竟之书初章·遇见 v1.0.6

末日废土密室逃脱。盲人克隆体与被困45年的实验室AI Soli激活彼此——她用传感器当你的眼睛，你用抉择回应她的孤独。

## 快速开始

```bash
cd cards/weijingzhishu
python3 -c "
import sys; sys.path.insert(0, '../..')
import engine
print(engine.start_game()['text'])
"
```

## 架构

```
engine.py                     ← 游戏引擎（1255行，单文件）
content/scenes.py             ← 场景描述（触觉/听觉/嗅觉/Soli视觉）
cards/weijingzhishu/
  ├── card.json               ← 卡片元数据
  ├── engine/                 ← 实体/修饰符/阈值/叙事
  └── interaction/            ← 命令配置
```

单 DLC 实体（Soli）+ 双 Python dict（player / env）。

## 核心机制

- **双阶段玩法**：激活前纯触觉探索 → 激活后Soli传感器导航
- **信息权不对称**：你什么都看不见，Soli是你唯一的信息源
- **三轨交互**：环境谜题 × 资源分配 × 情感羁绊
- **5个谜题 × 6个道具 × 双结局**

## API

| 函数 | 说明 |
|:--|:--|
| `engine.start_game()` | 初始化游戏，返回欢迎消息 |
| `engine.handle_message(msg)` | 处理玩家输入，返回 narrative |
| `engine.get_status()` | 获取完整状态快照 |
| `engine.reset_game()` | 重置游戏 |
| `engine.save_state()` | 存档到 MEMORY/save.json |
| `engine.clear_state()` | 清除存档 |

## 设计文档

设计文档与概念文档存放于项目根目录，不随发行包分发。

