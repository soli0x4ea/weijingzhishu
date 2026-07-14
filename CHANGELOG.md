# 未竟之书初章·遇见 — CHANGELOG

## v2.0.3 (2026-07-14) — 发布前收尾

### 修复

- **P2-1 __pycache__ 清理**: 删除 6 个编译缓存目录，发布包整洁
- **P2-2 duo 路线 game_route 时序**: 在具身转移分支中即时设置 `_game_route = "duo"`，确保 LLM 在转移叙事后的第一次回复中就能正确识别双人路线。修复前需等下一轮玩家输入才设置。

## v2.0.2 (2026-07-14) — Bug 修复

### 修复

- **P0-1 激活前命令匹配错误**: `cmd_follow` 的触发词（"往前走"/"走"/"往前走"等）与 `cmd_move` 重叠，导致激活前说"往前走"被误匹配为激活后命令，玩家卡在培养舱。修复: 移除重叠触发词，`cmd_follow` 改为"跟着你的声音走"/"带路"/"导航"/"你带路"等无歧义触发词。
- **P0-2 激活后场景不推进**: `_handle_follow` 只返回固定叙事文本，未调用 `_scene_manager.move_to()` 切换场景。修复: 增加场景推进映射（控制室→走廊B、走廊A→控制室），首次进入走廊B自动触发激光阵叙事；其他场景返回对应导航叙事。
- **P1-1 版本号统一**: VERSION / SKILL.md / README.md / card.json → 2.0.2；SKILL.md protocol → 2.6.0
- **P1-3 记忆碎片清理**: 移除了聊天表情符号（[偷笑]/[坏笑]/😊/😳等）和格式残余
- **P1-4 README 架构更新**: 更新架构图反映 DLC 框架 + 胶水代码的分层结构
- **P2-1 __pycache__ 清理**: 删除所有编译缓存

## v2.0.1 (2026-07-14) — Python 兼容性修复

### 修复

- **P0-1 Python 3.9 兼容性**: dlc/ 下 28 个 .py 文件添加 `from __future__ import annotations`，解决 `X | None` 语法兼容性
- **P1-1 protocol_version**: `card.json` 从 `1.0.0` 改为 `2.6.0`
- **P1-3 vault**: 从 `enabled: true` 改为 `false`（无配置数据）

## v2.0.0 (2026-07-13) — DLC 框架迁移

### DLC 框架接入（7/7 模块全开）

**阶段 0 — 基础设施**
- 引入 dlc/ 框架（从 dlc-skill 复制，protocol v1.0.0）
- 建立标准目录结构：dlc/ + cards/weijingzhishu/ + content/
- card.json 升级：protocol_version 1.0.0，7/7 模块全部启用

**阶段 1 — Engine 模块迁移**
- engine.py 从 1653 行重构为 ~780 行（-53%）
- DLC 框架接管：实体状态（EntityEngine/EntityState）、修改器（apply_modifier）、阈值检测（check_thresholds）、叙事渲染（render_event）
- 保留胶水代码：SceneManager、激光阵导航、出口抉择、保安室、激活过场、道具、伤害、记忆碎片
- 三实体全 DLC EntityState：soli（4通道+17标记）、player（hp+inventory）、environment（3通道+item_pool）
- 叙事格式兼容：v1.0.6 的 pipeline 格式注入 command_assembly，通过 render_command_narrative 渲染

**阶段 2 — Interaction 模块标准化**
- 命令匹配：dlc.interaction.match_command（最长触发词优先）
- 效果执行：dlc.interaction.execute_command（modifier/narrative/state 统一管道）
- 游戏特定叙事（intimacy 分档、场景分叉）保留 Python handler

**阶段 3 — Identity + Memory**
- identity/profile.json：Soli 身份背景（S0-L1 / 45年 / 九号生物工程研究所）
- identity/personality.json：5 特质 + companion archetype + 说话风格
- Memory 模块自动加载：ChatlogStore + TimelineStore + MemorySearch

**阶段 4 — Behavior + Body + Vault**
- body/anatomy.json：5 区域数字躯干（服务器机柜模型）
- body/zones.json：6 交互区
- dlc/body.py（235行）：AnatomyLoader + ZonesLoader + BodyModel
- behavior/lws_rules.json：6 核心原则 + 11 条 LWS 规则
  - 根据 intimacy/stability/understanding/soli_hp 动态切换 Soli 语气
  - 预激活→系统口吻 / 激活后→「我」自称 / 高亲密→温暖 / 临界稳定→碎片化 / 记忆碎片→泄露「少爷」
- dlc/vault.py（162行）：AES-256-GCM 加密存储，3 次错误锁定 5 分钟

**阶段 5 — 回归测试 + 文档**
- 全量回归 57 项测试（模块加载/启动/命令/谜题/导航/激活/道具/存档/边界/7模块交叉）
- SKILL.md 重写：新增架构章节、LWS 行为规则表、7 模块说明
- CHANGELOG 补全 v2.0.0

### 模块状态：7/7（全开）
identity | body | engine | interaction | memory | behavior | vault

---

## v1.0.6 (2026-07-13)

### 修复

- **P1-1 出口抉择关键词**：否定词检查 + 绕路优先匹配 + 大小写兼容
- **P1-2 记忆碎片内容**：敏感词过滤为 `..`（丢失的记忆碎片）
- **P1-3 CHANGELOG 补全**：补充 v1.0.4 / v1.0.5 变更记录
- **P1-4 __pycache__ 清理**：打包干净

## v1.0.5 (2026-07-13)

### 新功能

- **记忆碎片系统**：20 组带时间戳的 Soli 温度记忆，激活后 ~25% 概率随机涌出，不重复
- **自由探索模式**：初章结束后引擎不终结，退居状态维护（HP/道具/通道），LLM 接管叙事
- **双路线设计**：solo（烧记忆独自逃出）/ duo（保安室具身转移双人逃出）→ 走向废土
- **废土场景**：`scene_wasteland` — 开放式探索，引擎不限制方向
- **Soli 人格补全**：SKILL.md 新增五条特质 + 五条行为准则 + 说话方式

### 修复

- **P1-1 出口抉择关键词**：`"不烧记忆"` 不再误触发烧路线（加否定词检查）；`"B区"` 正确匹配（改为小写 `b区`）
- **P1-2 记忆碎片内容**：不适合公开展示的成人向内容 → 替换为 `..`（丢失的记忆碎片）

## v1.0.4 (2026-07-13)

### 修复

- **P0-1 SKILL.md API 契约**：`start_game()` 返回增加 `text` 字段；新增公开 `load_state()` 函数
- **P0-2 版本号统一**：VERSION/README/card.json/SKILL.md → 1.0.4
- **P1-1 撬面板叙事去重**：`_damage_player("pry")` 不再与 pry handler 冗余
- **P1-2 README 移除失效 docs 引用**

## v1.0.3 (2026-07-13)

### 修复

- **P0-1 修复 SKILL.md API 契约**：`start_game()` 返回增加 `text` 字段（开场叙事）；新增公开 `load_state()` 函数
- **P0-2 版本号统一**：VERSION / README / card.json → 1.0.3
- **P1-1 撬面板伤害叙事去重**：`_damage_player("pry")` 有自己的叙事文本，不再与 `_handle_pry_pre` 中的描述冗余
- **P1-2 README 移除失效 docs 引用**：docs/ 不在发行包内，README 同步更新
- **CHANGELOG 补全**：补充 v1.0.2 和 v1.0.3 变更记录

## v1.0.2 (2026-07-13)

### 新设定

- **生来全盲设定**：克隆体视觉系统从未发育（突变个体），非受伤/可恢复
- **开场叙事更新**：「你的世界从来就是这样的」——贴合全盲人设
- **移除 blindness_timer**：全盲是出厂设定，非临时状态

### 修复

- **激光阵中死亡不触发结局**：`_handle_laser_navigation` 早期 return 绕过死亡检查 → 统一调用 `_check_player_crisis()`
- **__pycache__ 清理**：builds + skills 目录清扫干净

### 文档

- **SKILL.md 重构为盲人GM协议**：LLM 和玩家一样通过 stdout 体验故事，SKILL.md 只讲「怎么调用」不讲「会发生什么」
- **数值系统补充**：HP/Soli%/道具指令表——纯机制知识，无剧透

## v1.0.1 (2026-07-13)

### Bug 修复

- **修复跨进程存档污染**：`start_game()` 不再自动加载旧存档。`_try_load()` 被 `_clear_save()` 替代——每次开始新游戏都是全新状态，不受上次会话残留影响。
- **修复撬面板 HP 不扣血**：`_handle_pry_pre()` 中面板碎片划伤后 HP 保持 100 不变。现在撬面板扣 10 HP，激活时 Soli 说「你在流血」对应实际受伤状态。
- **修复盲人视角叙事泄漏**：20 处视觉词/精确数字/上帝视角空间描述修正——激活前全部基于触觉、听觉、嗅觉和步数/臂展丈量空间。

### 新增功能

- **玩家伤害系统**：`_damage_player(amount, cause)` — 受伤时返回叙事文本而非静默扣血。
  - **撬面板割伤**：-10 HP（叙事已描述边缘锋利 → 现在真的会流血）
  - **走廊沟槽绊倒**：-5 HP（未先摸索走廊就乱走 → 踩空绊进沟槽）
  - **走廊锋利墙板**：-3 HP（摸到扶手上锐利划痕 → 指尖割伤，仅触发一次）
  - **激光阵灼伤**：-10 HP/次（肉身穿过激光感应线 → 灼烧感 + Soli 压制警报）
  - **lab_coat 保护**：穿外套时激光伤害减半至 -5 HP
- **HP 梯度叙事**：HP ≤ 20 时追加手抖/脚步沉重的叙事；HP ≤ 50 时追加伤口隐痛的警告
- **Soli 血量关切**：激活后 HP ≤ 30 时 Soli 会主动提醒使用医疗包（最多 2 次，不重复啰嗦）
- **死亡结局**：HP 降至 0 → 游戏结束叙事「— 第一章终 · 你在黑暗中倒下 —」，静默重置

## v1.0.0 (2026-07-13)

### 第一章初始版本

- **5 个场景**：培养舱室 → 走廊A → 控制室 → 走廊B → 出口
- **5 个谜题**：排液 / 撬面板 / 应急电源激活 / 激光阵 / 出口抉择
- **17 个命令**：7 个激活前触觉探索 + 10 个激活后 Soli 导航/道具
- **6 个道具**：医疗包 / 备用电池 / 实验室外套 / 身份卡 / 日志碎片（50%随机分配）
- **4 个通道**：soli_hp / understanding / intimacy / stability
- **10 个阈值事件**：覆盖稳定性/记忆/了解/亲密四维度
- **32 段叙事文本**：threshold events + command assembly
- **双结局**：烧记忆开门 / 绕路保Soli完整
- **存档系统**：JSON 全量持久化（MEMORY/save.json）
