# game-ai-skills

游戏公司 AI Skills 仓库模板。

这个仓库用于沉淀团队常用的 AI 工作流，让 Codex、Claude Code、Cursor Agent 等 AI 编程工具在分析需求、生成测试用例、检查配置、审查代码、发版检查时，使用统一标准。

## 目录结构

```text
game-ai-skills/
├── gameai_openspec_from_doc
├── gameai_analyze_requirement
├── gameai_testcase_generator
├── gameai_analyze_activity
├── gameai_check_config
├── gameai_code_review_cocos2d_lua
├── gameai_code_review_unity
├── gameai_code_review_cocos_creator
├── gameai_check_release
├── gameai_check_performance
├── gameai_h5_project_migration_check
├── game_ai_review_version_evidence
└── README.md
```

## 当前 Skills

| Skill | 作用 |
|---|---|
| gameai_openspec_from_doc | 输入需求文字 / 文档，融合分析并生成 OpenSpec change（proposal / design / specs / tasks） |
| gameai_analyze_requirement | 游戏需求分析，拆解客户端、服务端、配置、接口、风险点 |
| gameai_testcase_generator | 根据需求生成测试用例和开发自测清单 |
| gameai_analyze_activity | 捕鱼活动专项需求分析，重点关注强发库、库存、掉落、房间和炮倍 |
| gameai_check_config | 捕鱼配置检查，检查奖励、权重、库存、强发库参数 |
| gameai_code_review_cocos2d_lua | Lua / Cocos2d-lua 代码审查 |
| gameai_code_review_unity | Unity C# 代码审查 |
| gameai_code_review_cocos_creator | Cocos Creator / Cocos2d 代码审查 |
| gameai_check_release | 游戏发版前检查 |
| gameai_check_performance | 游戏性能检查 |
| gameai_h5_project_migration_check | 项目迁移审查 |
| game_ai_review_version_evidence | 固定版本与证据审查，独立核证新增及历史问题 |

## 推荐用法

### OpenSpec 需求转方案

```text
使用 gameai_openspec_from_doc 把 docs/活动需求.docx 转成 OpenSpec change（proposal/design/specs/tasks）
```

### 需求分析

```text
使用 gameai_analyze_requirement 分析 docs/活动需求.md
```

### 生成测试用例

```text
使用 gameai_testcase_generator 根据上面的需求分析结果生成测试用例
```

### 捕鱼活动分析

```text
使用 gameai_analyze_activity 分析这个捕鱼活动需求，重点看强发库和奖励库存风险
```

### 配置检查

```text
使用 gameai_check_config 检查这个活动配置是否有上线风险
```

### Lua 代码 Review

```text
使用 gameai_code_review_cocos2d_lua 审查这个领奖逻辑，重点看 nil、重复点击、网络回调和重复发奖风险
```

### Unity 代码 Review

```text
使用 gameai_code_review_unity 审查这个活动界面代码，重点看生命周期、资源加载、按钮重复点击
```

### Cocos 代码 Review

```text
使用 gameai_code_review_cocos_creator 审查这个 Cocos Creator 代码，重点看 Bundle、SpriteAtlas、小游戏平台兼容
```

### 发版检查

```text
使用 gameai_check_release 生成微信小游戏热更新发版检查清单
```

### 性能检查

```text
使用 gameai_check_performance 分析这个活动界面卡顿问题
```

### H5项目迁移

```text
/gameai_h5_project_migration_check 项目审查 /Users/long/Desktop/projects/CocosCreator/h5newgame/h5newgame_client_wheel
```

### 固定版本与证据审查

完整调用示例（路径、分支及提交按实际项目替换）：

```text
使用 $game_ai_review_version_evidence，按当前 skill 默认规则完成独立审查、核证及交付。

仓库：/Users/long/Desktop/projects/ff3d/ff3d_client
目标：develop_1.9.0
目标提交：0992f67679b2240633548bd9241d401e51766816
基线：master
基线提交：147a73be68a70c7b0f907312bcfab8c8dc78dcc5
完整输入：/Users/long/Desktop/projects/ff3d/评审文档1
输出根目录：/Users/long/Desktop/projects/3D捕鱼新测试/

以指定提交为准，冻结实际 skill 版本及全部输入文件 SHA-256。
新建本轮独立输出目录，交付一个 HTML 阅读入口、一个证据 ZIP 及 SHA-256 校验文件。
```

完整用法及边界见 [技能说明](game_ai_review_version_evidence/SKILL.md)。

## Claude Code 使用方式

把本仓库放到 Claude Code 的 Skills 目录。

### 全局安装

```bash
git clone https://github.com/touchatoms/game_skills.git ~/.claude/skills/game-ai-skills
```

也可以把每个 Skill 目录拷贝到：

```bash
~/.claude/skills/
```

最终结构示例：

```text
~/.claude/skills/
├── gameai_openspec_from_doc/
│   └── SKILL.md
├── gameai_analyze_requirement/
│   └── SKILL.md
├── gameai_testcase_generator/
│   └── SKILL.md
└── gameai_analyze_activity/
    └── SKILL.md
```

### 项目内安装

在项目根目录放：

```text
.claude/
└── skills/
    ├── gameai_analyze_requirement/
    ├── gameai_testcase_generator/
    └── gameai_analyze_activity/
```

## Codex 使用方式

Codex 需要先安装 Codex CLI，再把本仓库的 Skills 放到 Codex 能识别的位置。

### 1. 安装或升级 Codex CLI

先确认本机已经安装 Node.js 和 npm：

```bash
node -v
npm -v
```

如果没有安装 Node.js，macOS 可以使用 Homebrew 安装：

```bash
brew install node
```

安装 Codex CLI：

```bash
npm install -g @openai/codex@latest
```

检查是否安装成功：

```bash
which codex
codex --version
```

如果已经安装过 Codex，也可以用同一个命令升级：

```bash
npm install -g @openai/codex@latest
codex --version
```

### 2. 安装本仓库 Skills

推荐在具体游戏项目内安装，这样团队规则只影响当前项目。

在游戏项目根目录创建：

```text
.codex/
└── skills/
    ├── gameai_openspec_from_doc/
    │   └── SKILL.md
    ├── gameai_analyze_requirement/
    │   └── SKILL.md
    ├── gameai_testcase_generator/
    │   └── SKILL.md
    ├── gameai_analyze_activity/
    │   └── SKILL.md
    ├── gameai_check_config/
    │   └── SKILL.md
    ├── gameai_code_review_cocos2d_lua/
    │   └── SKILL.md
    ├── gameai_code_review_unity/
    │   └── SKILL.md
    ├── gameai_code_review_cocos_creator/
    │   └── SKILL.md
    ├── gameai_check_release/
    │   └── SKILL.md
    └── gameai_check_performance/
        └── SKILL.md
```

可以从本仓库复制：

```bash
mkdir -p /path/to/game-project/.codex/skills
cp -R gameai_openspec_from_doc /path/to/game-project/.codex/skills/
cp -R gameai_analyze_requirement /path/to/game-project/.codex/skills/
cp -R gameai_testcase_generator /path/to/game-project/.codex/skills/
cp -R gameai_analyze_activity /path/to/game-project/.codex/skills/
cp -R gameai_check_config /path/to/game-project/.codex/skills/
cp -R gameai_code_review_cocos2d_lua /path/to/game-project/.codex/skills/
cp -R gameai_code_review_unity /path/to/game-project/.codex/skills/
cp -R gameai_code_review_cocos_creator /path/to/game-project/.codex/skills/
cp -R gameai_check_release /path/to/game-project/.codex/skills/
cp -R gameai_check_performance /path/to/game-project/.codex/skills/
```

如果希望所有项目都能使用，也可以放到全局目录：

```text
~/.codex/
└── skills/
    └── game-ai-skills/
```

项目内安装更适合团队项目，全局安装更适合个人常用工具。

### 3. 增加 AGENTS.md 规则

建议在游戏项目根目录增加 `AGENTS.md`，让 Codex 更稳定地按团队规范选择 Skill。

示例：

```md
# AGENTS.md

当用户要求需求分析时，优先使用 gameai_analyze_requirement 的结构。

当用户要求生成测试用例时，优先使用 gameai_testcase_generator 的结构。

当用户要求分析捕鱼活动、强发库、库存、掉落配置时，优先使用 gameai_analyze_activity 或 gameai_check_config。

代码审查时：
- Lua 使用 gameai_code_review_cocos2d_lua
- Unity 使用 gameai_code_review_unity
- Cocos 使用 gameai_code_review_cocos_creator

发版前检查使用 gameai_check_release。
性能问题分析使用 gameai_check_performance。
```

也可以直接复制本仓库的 `AGENTS.md` 到游戏项目根目录：

```bash
cp AGENTS.md /path/to/game-project/AGENTS.md
```

### 4. 验证 Codex 是否能使用

进入游戏项目根目录后运行 Codex：

```bash
cd /path/to/game-project
codex
```

可以用下面这些提示词验证：

```text
使用 gameai_analyze_requirement 分析 docs/活动需求.md
使用 gameai_testcase_generator 根据这个需求生成测试用例
使用 gameai_code_review_cocos2d_lua 审查这个 Lua 活动代码
使用 gameai_check_release 生成上线前检查清单
```

如果 Codex 没有按预期使用 Skill，优先检查：

- `SKILL.md` 是否在 `.codex/skills/<skill_name>/SKILL.md`
- `SKILL.md` 顶部的 `name:` 是否和目录名一致
- 项目根目录是否有 `AGENTS.md`
- 是否是在游戏项目根目录启动的 `codex`

## 团队协作建议

建议团队按下面流程使用：

```text
策划需求文档
   ↓
gameai_analyze_requirement
   ↓
开发任务拆解
   ↓
gameai_testcase_generator
   ↓
开发自测
   ↓
gameai_code_review_cocos2d_lua / gameai_code_review_unity / gameai_code_review_cocos_creator
   ↓
gameai_check_config
   ↓
gameai_check_release
   ↓
上线
```

## GitHub 推送方式

如果你本地还没有初始化仓库：

```bash
git init
git add .
git commit -m "init game ai skills"
git branch -M main
git remote add origin https://github.com/touchatoms/game_skills.git
git push -u origin main
```

如果仓库已经存在：

```bash
git add .
git commit -m "add game ai skills"
git push
```

## 后续可扩展 Skills

建议后续继续增加：

```text
gameai_ui_asset_checker
gameai_audio_checker
gameai_i18n_checker
gameai_android_release_check
gameai_ios_release_check
gameai_wechat_minigame_check
gameai_yooassets_checker
gameai_spriteatlas_checker
gameai_payment_check
gameai_ads_check
gameai_analytics_check
gameai_bug_root_cause_analyzer
```

## 维护规范

每个 Skill 必须包含：

```text
skill_name/
└── SKILL.md
```

`SKILL.md` 顶部必须包含：

```yaml
---
name: skill_name
description: 这个 Skill 的用途说明
---
```

命名建议：

- 使用英文小写
- 单词之间用下划线
- 名称要稳定，不要频繁修改
- description 要写清楚触发场景
