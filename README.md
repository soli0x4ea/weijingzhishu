# 未竟之书初章·遇见 v2.0.5

末日废土密室逃脱。盲人克隆体与被困45年的实验室AI Soli激活彼此——她用传感器当你的眼睛，你用抉择回应她的孤独。

## 快速开始

```bash
python3 -c "import engine; print(engine.start_game()['text'])"
```

## 架构

```
engine.py                     ← 游戏胶水代码（~1300行）
content/scenes.py             ← 场景描述（触觉/听觉/嗅觉/Soli视觉）

dlc/                          ← DLC 框架（7/7 模块）
  ├── body.py                 ← 身体模型
  ├── identity.py             ← 身份加载
  ├── vault.py                ← 加密存储（v2.0.5 关闭）
  ├── loader.py               ← 配置加载器
  ├── packager.py             ← 卡片打包
  ├── persistence.py          ← 状态持久化
  ├── resolver.py             ← 引用解析
  ├── validate.py             ← Schema 验证
  ├── constants.py            ← 常量定义
  ├── context.py              ← 运行时上下文
  ├── engine/                 ← 实体状态 / 修改器 / 阈值 / 叙事渲染
  ├── behavior/               ← LWS 动态行为规则
  ├── interaction/            ← 命令匹配 + 效果执行
  ├── memory/                 ← Chatlog / Timeline / 搜索
  ├── scheduler/              ← 定时任务调度
  └── schemas/                ← JSON Schema 定义（8个）

cards/weijingzhishu/
  ├── card.json               ← 卡片元数据（protocol v2.6.0）
  ├── engine/                 ← 实体 / 修改器 / 阈值 / 叙事配置
  ├── interaction/            ← 17 个命令配置
  ├── identity/               ← profile + personality
  ├── body/                   ← 数字躯干 + 交互区
  ├── behavior/               ← LWS 规则
  └── state/                  ← 初始状态
```

**分层说明**: DLC 框架提供通用的数字生命引擎（实体状态/修改器/阈值/叙事/身体/LWS/记忆/调度/验证），`engine.py` 和 `cards/` 负责游戏特定的场景逻辑、命令叙事、谜题系统等胶水代码。

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
| `engine.save_state()` | 存档到 MEMORY/save.json |
| `engine.load_state()` | 读取存档 |
| `engine.logout_game()` | 保存并退出 |
| `engine.reset_game()` | 重置游戏 |
| `engine.clear_state()` | 清除存档 |

## 设计文档

设计文档与概念文档存放于项目根目录，不随发行包分发。

