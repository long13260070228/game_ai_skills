# 迁移检查依据

来源为用户提供的《技术-客户端-H5-项目开发README》中的“准备工作”和“项目迁移CheckList”，以及用户随后确认的规则。其他章节不作为本 skill 的流程依据。这里保留可复用要求，不复制账号、token、机器人 webhook 或临时下载入口。

优先级：用户当前明确要求 > 本 skill 中确认的范围和分支规则 > 文档历史示例。文档曾要求从 master 迁移；现规则为用户指定源分支，并主动获取其最新提交。文档中的 Jenkins、打包验证和真机验收由用户排除，不执行。

## 准备工作

- Cocos Creator 文档基准为 2.4.8，检查项目声明及实际环境，不能擅自升级。
- 确认 JavaScript 与 Cocos2d-x 引擎设置和项目自定义引擎要求。文档“内置引擎”设置与 setup 的全局引擎替换应按实际环境核实，不同时机械执行。
- 复用项目已有 Prettier 配置。全局格式化不能发生在原样初次提交之前；不要借格式化修改无关项目。
- tools/setup/setup.sh 中的 Git 仓库地址统一使用 `https://`；检查 GIT_REMOTE、git clone 等全部位置，将 `http://` 改为 `https://`，保留域名及仓库路径；已使用 HTTPS 时继承。引擎仓库和依赖安装段需要检查。目标引擎：
  - `https://gitlab.xgame1024.com/client_mini_games_cc/client_core_yq/cocos2d-x_2.4.8.git`
  - `https://gitlab.xgame1024.com/client_mini_games_cc/client_core_yq/engine_2.4.8.git`
- setup.sh 中 Creator 2.4.8 的安装目录统一为 `/Applications/CocosCreator/Creator/2.4.8/CocosCreator.app/`。逐一核验安装检查、引擎目录检查、mkdir 和 cd，完整替换旧的 `/Applications/Cocos/Creator/2.4.8/CocosCreator.app/` 前缀并保留其后 Contents/Resources 子路径。源中部分路径已经正确时只补齐旧路径；全部已满足时不重复修改或产生空提交。不借此升级 Creator 版本或实际操作全局引擎。
- 公共库分为两组，必须分别检查声明、锁文件、imports、全局符号及初始化调用：框架 `yyf ^6.0.0` → `npmgpf ^6.0.1`；性能监控 `yy_performance_monitoring ^2.0.0` → `npmgpm ^2.0.11`。源中更早的 yq/yqf、yq_performance_monitoring 名称按真实导出判断相应归属。仅迁移源中已有的库；源已移除且无有效引用时记为不适用，不自行新增监控依赖或功能。已符合目标的库直接继承，不降级。版本按本次用户确认值，不自行取最新版。
- 公共库示例混有 yq、yyf、yqf 等不同阶段的写法，以及旧性能监控名称。先检查真实导出和调用关系，再迁移到目标依赖，不能只做字符串替换。
- setup.sh 安装段按原文要求改为：回到项目根目录，依次执行 `rm -rf node_modules`、`rm -rf package-lock.json`、`npm i`，由 npm 重新生成锁文件。不手工拼装或复制参考项目的 package-lock 记录来代替安装生成。不能用 `npm ci` 代替这条迁移要求，也不能继续调用旧的私有源安装脚本。路径变量正确引用以兼容空格。修改脚本不等于执行：不在基线前或只读阶段运行；用户已要求将三步装配进 project_migrate：全部适配后实际安装，再用项目 Prettier 格式化 assets 全部 .ts 和唯一主 Config.js，其它 .js 不格式化，成功后在 init 分支一次提交。只执行这段根目录安装，不运行全局引擎 setup；只读审查不执行。核验 npm 生成的锁文件与实际安装库。不把公共 npm 包存在当作框架兼容性的证据。

## 客户端迁移清单

每项先核对源基线实际状态；源项目已完成且符合本次目标的工作直接继承，不重复修改。确定的引擎/依赖/字段/平台文件映射可交给 project_migrate 的可选适配清单执行；未知原值或 API/协议差异需先判断，不能绕过冲突强制替换。适配提交与原样初次提交分开，玩法与历史 Bug 适用性继续按下表审查。

| 检查项 | 适用条件与核验要求 |
|---|---|
| 源码与版本 | 克隆指定源分支最新代码，记录 SHA 后删除临时副本根目录 `.git`，复制其余全部文件和文件夹（包括隐藏项）到新仓库并提交；不按跟踪状态或忽略规则筛选，不迁入源历史、分支或标签；原样初次提交与后续适配分开，产品版本原值用于配置与新分支 |
| 项目命名 | 产品名称、目标仓库名、gameName、埋点路径、ZIP 名及上传目录分别确认其映射；不可将仓库命名的驼峰说明直接应用到服务端协议 |
| 构建模板 | build-templates 默认适配：存在时删除 cocos2d-js.js、cocos2d-js-min.js、vconsole.min.js；index.html 的引擎 loadScript 第一个参数整体替换为 `https://hkres.qigame1024.com/h5sdk/v1/cocos2d-js-min.fcae2.js`，不再按 debug 选择本地引擎；vconsole 引用改为 `https://hkres.qigame1024.com/h5sdk/v1/vconsole.min.40fd7.js`。style-mobile.css 中 #splash 的 background-size 改为 cover，保留其它 CSS。处理实际目录大小写和已完成项，在 init 分支适配；不下载 CDN 资源或执行构建。 |
| PAC 与主构建压缩 | 枚举全部 `.pac`，配套 `.meta` 顶层 maxWidth/maxHeight 固定为整数 2048；UUID、子资源及其它字段保持，已符合项跳过，缺少或无效 meta 时停止，不生成 UUID。settings/builder.json 顶层 mainCompressionType 固定为 merge_all_json，缺字段时补齐，其它字段保持；兼容首字母大小写，缺文件报告不适用，无效 JSON 停止。默认工具化，无额外用户参数，仅 init 分支提交；版本基线保留源值。 |
| 引擎和公共库 | 引擎地址、依赖声明、有效引用、锁文件与兼容 API 对应一致 |
| 布局适配 | 目标设计分辨率、效果图和显示容器适配；无目标变化时保留源布局；遇到 checkSceneScalePortrait 调用直接删除，清理因此无用途的导入；SceneMain 其它逻辑保留，不替换成 checkSceneScale 或 Canvas 布局；其它 API 不兼容记录待处理 |
| 资产显示 | 资产上限、图标、尺寸、数值格式和权威数据来源 |
| 多语言 | 支持语言、URL/SDK 语言字段映射、用户语言、默认语言及回退；查图片资源和有效缓存 |
| 环境 | 工具仅修改主 Config 的 build、version、SHOW 标识；网关、HTTP/CDN、DEBUG 等源值保留，由 skill 审查并交接，不自动写入目标环境 |
| 业务标识 | channel、gameName、roomId 和相关请求类型；仅根据目标平台协议调整 |
| SDK 与登录 | SDK 引入、初始化、URL/桥接数据获取、startup 的 query 传递、登录凭证；调试和跳转入口同步适配 |
| 支付与退出 | 平台 API、回调注册、请求锁、资产刷新、退出路径及缺失桥接时的行为；调用前有适当的分层诊断埋点 |
| 异常上报 | 目标平台的异常报告配置；不复制源平台机器人或自行创建外部机器人 |
| 埋点 | 核验 traceEvent 与 DataCollection 的目标游戏路由及源设备标识策略，问题记录待处理；保留 traceEvent.device_id，不新增 TraceIdentity 或擅自改写 DataCollection 的对应逻辑。数据库实际入库状态属于未验证外部证据 |
| 停服 | 停服协议、提示唯一性、退出行为和重复通知处理 |
| 玩法一致性 | 保留玩法状态与资产不变量；仅在适用时核验盘面预制体名字/尺寸、转轴高度、spin 状态和网络判断 |
| 产品额外要求 | 仅落实本次明确新增项；不得把参考项目的专属玩法一并带入 |
| 性能监控 | 按准备工作依赖和目标参考接入；静态核对监控初始化和引用，不伪称性能实测通过 |

平台专属要求仅在目标平台匹配时启用：

- StarChat/SCLite：按其协议核对网络通信退出流程，不能用其他平台 JSB 替代。
- Wesing：关闭按钮、离线包、初始化、Bundle 路径、gameAppId、头像更新和 `_assets_` 结构为配置检查项；不执行打包验证。
- SoulU：适用时核对 UILoading 的退出按钮。
- 实际 Slots 盘面存在时：结合源玩法检查图标、转轴、数据清理与动画顺序；文档旧 yqf 版本及截图是历史方案，不是新项目统一补丁。

## tools_h5 静态配置

`tools_h5` 是独立工具集合，使用 master。以其实际 README、projects.json 和调用代码为依据；schema 未知时主动读取，不要求用户手工抄配置字段。

核对平台/项目键、Git URL、游戏标识、产品版本的真实配置位置、ZIP/发布目录名称、图片压缩排除项、平台专属 Bundle 路径。字段不存在时不自行发明，不复制参考项目的账号或上传凭证。

新目标配置的 key 必须等于 Git 项目名（不含 `.git`）；`uploadZipName` 取 key 最后一个 `_` 后面的名字并转为小写，不沿用源项目值。

初始化证据由 AI skill 只读采集并核验，不运行正式迁移命令代替审查。检查 JSON 解析、有效键唯一性、路径引用和已有配置调用关系。能解析不等于能打包；脚本会构建、压缩或上传时不运行。Jenkins 名称和任务由用户维护，只按需交接项目参数。

## 完成证据

记录源分支与完整 SHA 作为来源，记录目标原样初次提交 ID；核对克隆副本除根目录 `.git` 外的全部内容（含隐藏项）已复制、可提交文件全部纳入，目标初次提交无父提交、初始化阶段仅有该新提交、未导入源分支和标签。空目录可存在于本地副本，但 Git 提交不保留空目录。用户只要求到版本分支时，以版本分支及这条初次提交为阶段完成点；开发分支、tools_h5 改动和其他后续事项尚未执行。继续迁移时再记录这些阶段的变更及静态检查结果。直接证据与推断分别说明，不以没有 diff 证明某项已满足。

从本清单和 known-bugs 按适用性形成条目，不要求产出额外报告文件：优先复用已有任务/交接文档，否则在响应中记录。任何新增文档和状态文件均在原样初次提交之后。

- Config 的唯一 SHOW_旧平台_CODE 声明改为 SHOW_目标Git库名第一个下划线前的大写_CODE，同步可执行引用及 game.d.ts，保留存储键和注释。不存在时记不适用，多声明冲突须停止。
- 枚举 assets 下全部 exclude、*_exclude 目录。每个都恰好含 README.md、README.md.meta 才统一删除（含目录 meta），并将 BundleManager.loadBundle 改为只加载主 bundle，保持错误/成功回调；同步核验启动模板及其它有效消费方不再请求已删除的 Bundle，保持启动完成计数。任一不满足就全部保留且不改方法。未知方法逻辑不能自动删除资源。


平台标识默认适配从 PlatformManager 的 platformGame 实例及本地默认导入识别源类，不依赖源仓库前缀或固定 LieBao 名称。CHANNLE_NAME 仅保留 H5: 'h5' 和目标平台项；LOGINTYPE 仅保留 WEB: 'h5visitor' 和目标平台项。目标项 key 为目标 Git 项目名首个下划线前的内容大写，value 为其小写；平台类名仅将该平台首字母大写，再加 H5Game，例如 h5newgame → H5newgameH5Game。同步类声明、导入、类型和实例化、枚举消费方以及配套 .meta 文件名，meta 内容及 UUID 原样保留，PlatformManager.meta 无内容变化。基于 TypeScript 符号解析处理导入别名，保留无关对象同名字段、字符串和注释；动态索引、多平台实例、目标路径/UUID 冲突或枚举合并后重复 switch 分支停止并交接。已有源状态满足目标时继承；重复完整文件清单按不可变版本基线映射旧类路径，不恢复旧文件。这些命名及枚举值调整不扩展 SDK 或登录流程。审查须确认基线原样、改动仅在 init 分支，并核对所有消费方及 meta UUID，不能以命令执行成功代替验收。


G.ts 的 G.LocalStorage 默认只迁移已有 MUSIC、VOICE、SHAKE 设置（允许缺少 SHAKE）：无前缀或旧平台前缀的键和值统一为 `SETTING_<目标仓库平台前缀大写>_<类型>`，如 SETTING_H5NEWGAME_MUSIC。同步实际 G 的全局桥接、import/namespace/别名、属性/静态括号和解构消费方；仅实际旧键/旧值的浏览器存储字面量引用随之更新，保留其它存储项、局部同名对象、日志和注释，不迁移用户已有缓存数据。路径兼容首字母大小写；同类项重复、名称和值不一致、动态成员/索引/解构需先处理，命令写入前停止。

assets 下直属文件夹的配套 .meta 默认将 compressionType["web-mobile"] 固定为 "merge_all_json"（缺字段或缺此平台项时补齐）；包括非 Bundle 和隐藏文件夹，兼容 Assets/assets，保留 UUID、子资源及其它平台/字段。只处理仍存在的直属文件夹，不改嵌套文件夹、资源文件、孤立 .meta 或已清理 exclude 的 meta；缺少配套 meta 时报告未验证，不生成 UUID，无效 JSON/字段类型或符号链接停止。此项在 init 分支随其它适配一次提交，原样版本分支保持源值；重复执行不产生空提交。
