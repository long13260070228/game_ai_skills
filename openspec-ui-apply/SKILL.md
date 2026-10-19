---
name: openspec-ui-apply
description: 根据必填的 UI 设计效果图路径、UI 资源路径、Prefab 保存路径和 Prefab 资源命名，在当前 Unity 工程中制作或更新界面 Prefab，并完成结构校验、视觉核对和 OpenSpec 任务交接。用于 UIApply、UI 生产制作和设计稿落地；不用于仅讨论方案或纯业务逻辑开发。
metadata:
  version: "1.0"
---

# UIApply

将设计图、资源与界面脚本契约转化为可加载、可维护的 Unity UI Prefab。使用简体中文记录契约、进度和验收结果。

## 入口与边界

- Codex 入口是 `$openspec-ui-apply` 或明确的 UIApply 自然语言请求。这是项目自定义 Skill，不是 OpenSpec CLI 新子命令，也不自动注册 `/opsx:ui-apply`。
- UIApply 可在功能 Apply 前、后或期间执行；以页面契约、设计图及资源是否具备为准，不要求全部业务代码先完成。
- 负责 Prefab 层级、布局、视觉资源、组件、状态展示和绑定契约。业务协议、支付、奖励规则等交给功能 Apply；只在本次任务明确需要时修改绑定代码。
- 不修改 `.claude`、全局 OpenSpec 安装或默认 schema。不要把文档存在或脚本生成成功当作 Prefab 制作完成。

## 必填输入（缺一不可）

开始任何资源导入、Prefab 创建、Editor 脚本执行或任务勾选前，必须取得并确认以下四项：

1. **设计效果图路径**：本地文件或目录，至少包含本次页面的效果图；需要多个状态时逐项列出。
2. **UI 资源路径**：本地文件或目录，包含本次使用的 Sprite、字体、材质、图集、动效等资源来源。
3. **Prefab 保存路径**：工程内的 Unity 资产路径，必须以 `Assets/` 开头并以 `.prefab` 结尾，例如 `Assets/Res/Prefab/Feature/UIFeatureWin.prefab`。
4. **Prefab 资源命名**：最终 Prefab 文件名（不含 `.prefab` 也可输入），必须与保存路径文件名一致，使用项目现有 PascalCase/模块命名约定，不使用空格、路径分隔符或临时名称。

输入确认规则：

- 路径必须是具体路径，不能用“见附件”“当前目录”“按模块放置”等模糊描述；目录输入要说明其中哪一个文件是主设计图/主资源集。
- 保存路径和资源命名必须同时存在，并在制作前检查二者的 basename 一致；不一致时先询问修正值。
- 任一项缺失、不可访问、指向错误类型，或设计图/资源无法对应页面时，只列出缺失项并停止制作，不创建占位 Prefab、不运行构建脚本、不标记任务完成。
- 变更名、页面范围、目标分辨率等信息仍需收集；它们可从上下文推断，四项输入不能推断，必须显式确认。

收到四项输入后，先在 `ui-contract.md` 的“输入确认”中原样记录路径和命名，再进入下一步。

## 1. 选择目标、检查执行条件

1. 先收集并验证上节四项必填输入，再从用户或当前上下文确定变更名和页面范围。无明确目标时执行 `cmd /c openspec list --json`；只有一个相关变更可采用，多个候选且无法判断时才询问。
2. 执行 `cmd /c openspec status --change <change-name> --json`，读取已有 proposal、specs、design、tasks，以及已有 UI 契约。`openspec instructions apply` 可辅助取上下文，但其 `all_done` 不代表 UI 已验收。
3. 检查适用 AGENTS.md、工作区已有修改、`ProjectSettings/ProjectVersion.txt`，以及目标模块的脚本和相邻 Prefab。工程具体规则见 [references/project-conventions.md](references/project-conventions.md)。
4. 实际查看设计图，盘点提供的切图、字体、材质、动效和现有通用资源。读取源图尺寸与导入参数；视觉工具不可用时明确说明。不要仅凭文件名推断完整布局。
5. 检查能否调用当前 Unity Editor 或已配置的 Unity 工具。不能假设存在 Unity MCP。没有可执行的 Unity 环境时可完成契约和生成工具准备，但 Prefab 制作/运行/视觉验收保留未完成。

缺少页面设计图、关键资源、指定字体或目标范围时，记录具体缺口并继续不依赖它们的工作。仅在用户同意占位后使用占位资源，且不得据此宣布最终视觉验收通过。

## 2. 建立 UI 制作契约

在变更目录建立或更新 `ui-contract.md`，使用 [assets/ui-contract-template.md](assets/ui-contract-template.md)。按页记录设计来源、状态图、输出路径、参考分辨率、适配策略、节点路径、组件类型、资源映射和待解决项。

- 将设计图拆成背景、窗口容器、安全区、标题、内容、按钮、列表模板和弹窗；区分静态装饰和真实交互控件，不能把整张效果图贴成完成品。
- 优先复用工程组件和子 Prefab；读取现有脚本中的 `Transform.Find`、动态路径拼接、资源加载路径和 `GetComponent` 要求，形成绑定表。
- 设计坐标换算为父节点局部 RectTransform 坐标时明确坐标原点、缩放、anchor 和 pivot。拉伸节点用 offset，固定节点用 anchoredPosition/sizeDelta，不混用屏幕像素与局部坐标。
- 原图不能确定的九宫格、适配或交互状态要标注为假设/待补充，不伪造精确设计数值。
- 先锁定路径和组件契约。更新现有界面时不要为了视觉整理擅自改名；确需变更时列出受影响绑定并一起验证。

在现有 `tasks.md` 中补充独立的 `UIApply` checkbox 分组或复用已有 UI 子任务，避免重复记账。任务拆为契约、资源导入、页面制作、结构校验、运行验收、视觉验收，只有对应工作实际完成才打勾。无法安全编辑原文件时使用 `ui-tasks.md` 并明确说明标准 CLI 进度不追踪该文件，归档前需单独检查。

## 3. 通过 Unity 制作 Prefab

具体编辑、保存和重复执行规则见 [references/unity-production.md](references/unity-production.md)。根据现有能力选择 Unity Editor 工具或为本模块编写小型 Editor 构建脚本；Skill 本身不是图像自动转 Prefab 的运行引擎。

1. 复核资源映射与缺失项，按目标模块现有目录导入资源。保留已存在资产及 `.meta` 的身份，只改变本次必要的导入参数。
2. 从相邻合适的窗口/组件结构建立页面，生成实际 UGUI 控件、布局、嵌套 Prefab 与资源引用。按项目根 Canvas 策略配置，不给每个页面随意增加 CanvasScaler 或 EventSystem。
3. 配置适用的字体、九宫格、raycast、Button targetGraphic/状态、ScrollRect content/viewport、遮罩及初始显隐。按需求覆盖选中、禁用、锁定、红点、空列表等状态，不凭空扩充功能。
4. 使用 Unity Prefab API 保存新建或修改后的 Prefab。保存成功后重新加载，验证序列化后的结果；保留用户编辑，重复运行不得产生重复节点或重新生成既有 GUID。

禁止通过拼接 Prefab YAML 和猜测 fileID/GUID 完成制作。只读解析 YAML 可用于盘点和差异检查，不能代替 Unity 导入、保存和加载校验。

## 4. 验证并交接

按 [references/prefab-qa-checklist.md](references/prefab-qa-checklist.md) 执行适用检查。记录每项为通过、失败、未执行或不适用，并附证据/原因。

- 结构：保存后的 Prefab 可加载；包含非激活节点的脚本、绑定、组件、嵌套引用和图集/字体引用有效；没有意外场景对象引用。
- 运行：经项目真实窗口入口验证创建/关闭、按钮、滚动、动态列表与状态切换。编辑器孤立预览只能证明预览表现，不能算真实业务入口验收。
- 视觉：在契约指定分辨率、SafeArea 和状态下渲染截图，打开截图与设计图核对。缺字、裁剪、层级、色彩、间距、九宫格和长文本需要实看，不能只以截图文件存在判定通过。
- 交付：在变更目录维护 `ui-validation.md`，记录环境、输入版本/哈希、输出路径、检查结果、截图路径和遗留问题。设计或资源变更后，原验收证据标记失效并重验受影响项。

完成时报告 Prefab 和契约路径、实际验证结果及未完成原因。没有执行 Unity 保存/重新加载或未查看截图时，明确标记对应阶段未验收。只更新本次 UI 任务，不擅自归档整个变更。
