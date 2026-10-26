# 机器可读交付约定

本版沿用 `local-flow-v1` 字段、枚举及计数政策，仅澄清证明边界与覆盖语义。旧结果不自动迁移或重算，仍用各自冻结技能和渲染器；用户授权的本轮成果维护按delivery-maintenance.md单列续核/展示修订，不倒填原发现。

顶层 JSON：

- `title`, `mode`（仅 independent）, `target`, `baseline`, `scope`, `limitations`（数组），以及 `classification_schema`（固定 `local-flow-v1`）。
- `sources` 数组：`id`, `kind`, `location`, `version`, `allowed`（布尔）, `limitations`，以及 `content_hash`、`captured_at`、`allowed_uses`。哈希可为提交/内容哈希；无法获取写明 unknown 与原因，本轮生成时间不得冒充源文档时间。。
- `coverage` 数组：`module`, `files`, `paths_checked`, `gaps`；允许附加需求/资源/归属字段。
- `findings` 数组：`id`, `title`, `status`, `origin`, `severity`（P0～P4）, `severity_basis`（见 severity.md）, `trigger`, `actual`, `expected`, `impact`, `reachability`, `counterevidence`, `evidence_level`, `scope`, `limitations`, `evidence`。
- 每条 `evidence`：`source_id`, `location`, `locator`, `quote`, `supports`、`role`（implementation / norm / invariant / reachability / guard / origin）。源码定位包含提交与行，需求定位包含文档修订与段落；禁止只给文件名。
- 可增加 `probes`, `excluded_contacts`, `review_history`, `comparison` 等字段，不能用附加字段替代必填证据。
- MR链接接入时须登记 `mr_context`；非MR报告可省略。字段及版本语义见 [mr-intake.md](mr-intake.md)，缺失字段写unknown并说明原因。`target`/`baseline`仍填实际完整提交；head/base/start、项目身份、原分支及comparison_kind分别保留，不混用。版本栏的target_ref/baseline_ref可附明确的MR基点注记，仅作展示；Git对象读取仍用完整SHA，不能把注记当Git ref解析。

每项另必填：

- `claim_scope`：`local_contract` / `user_flow`，互斥选择所述窄断言。
- `local_input_basis`：对象，含 `description` 与 `evidence_refs` 数组，在description中固定已有方法/接口的完整局部边界，并说明输入/前态、合法域、内部必经前置及消费者；缺失/缺省、值域、组合、身份均须核，边界外实际构建路径另列flow。confirmed+local_contract必须有非空合法性说明和证据引用，不能只证明代码片段会错。
- `flow_reachability`：对象，含 `state`（`reachable` / `blocked_by_confirmed_issue` / `unproved` / `inactive_config`）、非空 `basis`、`blocked_by`（发现ID数组）与 `evidence_refs` 数组。blocked_by_confirmed_issue必须有非空阻断者ID及证据，每个ID须为本样本另一条confirmed项，可为historical；不能引用自身或conditional项。其余状态的blocked_by为空数组。reachable须给固定合同/配置条件下完整合法流程证据，可静态证明；basis区分静态可达与部署观测/发生频率，unproved写具体必要边而非仅“未实测”；inactive_config只用于真实配置未启用。

`confirmed`至少有implementation与norm/invariant两种证据角色，并按claim_scope核反证：local_contract须合法局部输入到必错消费者闭合，flow可blocked_by_confirmed_issue或unproved；user_flow须flow为reachable且完整守卫/资源/消费者闭合。局部规则或输入合法性缺证仍待核，不能借flow分离升级。真实配置未启用维持status=inactive_config，不计确定Bug。原`reachability`文本仍保留作可读解释，不能替代结构字段。使用代码不变量时明确理由而非伪造需求引用。

确定Bug总数按唯一根因/发现ID计，claim_scope两组互斥；被阻断及可达未证为确定项内部子计数，不与总数相加。局部项的impact/limitations须区分局部后果与未证玩家影响、频率、资产后果。P0/P1仍需严重影响、范围、恢复限制与对应流程证据，不继承阻断者等级。

所有字段的事实内容须来自当前审查，不得从参考答案补齐独立输出。另交输入来源清单及覆盖缺口。

顶层另填 `skill_version`、`timings`（各阶段实际时间，等待单列）与 `high_severity_review`（P0/P1项ID、核心路径检查、缺口、实际结论）。`severity_basis`为对象，包含非空的 consequence、affected_scope、trigger_basis、recovery、rationale 与非空 evidence_refs 数组。P0/P1的严重后果有未决条件时，不能把它写成已证影响；可另填 potential_severity。机器校验仅检查结构和枚举，不能替代严重度语义审核。

客户端来源清单须说明各类 MR、需求、客户端/服务端设计、资源、配表及 SVN 是已提供、可提供但本次未收到、已读或未读，并记录版本绑定限制；这些可用性信息可放在 `input_availability` 附加账本中。Bug 列表与服务端源码写明“本次不提供/不使用”，不作为必需补充输入。未使用来源不冒充已读证据；服务端设计来源的类别须与服务端实现、真实响应明确区分。

字段类型：来源、覆盖、发现、证据、限制为数组（每项证据为对象）；文本字段用字符串，未知值说明未知原因，不用空字符串掩盖缺失。coverage 每项必须有字符串 module 及数组 files、paths_checked、gaps。confirmed 的证据至少具有 implementation 与 norm/invariant 两种角色；语义是否真正支撑仍需回读。excluded_contacts/probes/review_history 等存在时，渲染器必须在HTML/MD中完整呈现；来源允许标记及限制不可隐去。

可在证据中附 `local_copy`（固定版本源文件的相对路径或允许的HTTP(S)地址），用于查看完整上下文；必须由允许源直接提取，不可链接浮动工作区冒充固定版本。附加判定字段必须在三种格式中保留，不限于预定义字段。

存在规范输入时，在最终JSON中另填紧凑 `requirements_coverage` 数组：每项包含稳定 `id`、原文 `source_ref`（来源ID及段落/图示定位）、`condition`、独立预期 `expected`、`disposition`（satisfied / finding / unresolved / out_of_scope）、`evidence_refs`、`finding_ids` 及必要时 `gap`。适用要求逐独立结果对应。condition须给区分行为的前态/事件/分支谓词，或引用实际包含这些条件的具体case ID，不能用统一承接句代替。案例必须证明同一触发下同一预期；可复用真正相同的证明，不按父条款状态、证据并集或存在finding ID自动赋子状态。关联发现在案例/说明中区分直接结果、依赖阻断和背景；后两者不证明本行结果已核，须保留该结果的判定或具体未决维度。无规范材料时明确说明，继续核代码不变量。该数组即下述条款账本的JSON等价物；Markdown账本从它生成或引用，不重复手填。它由原文条款集合建立，不只列已有发现；未判定的必要条款不得声称已完成。渲染器会保留附加字段，来源覆盖和语义仍由审查者核证。

`disposition`沿用上述四个枚举，与`findings.status`分开：

- `satisfied`：有效条款在所列同一触发、同一期望下有正向实现证据；“没有提出候选”、其他分支安全或已排除都不能作为满足依据。
- `finding`：该独立结果关联具体缺陷断言；确定性仍以关联项的`status/claim_scope`为准，不把待核断言自动显示为确定违约。
- `unresolved`：本行判断尚不能闭合，记录具体未决维度及原因；已读但尚未核完不能改写成缺来源。纯流程未证不自动撤销已闭合的局部缺陷，也不能借局部缺陷宣称完整流程结果已核。
- `out_of_scope`：在现有条款说明中写明本轮范围依据和排除理由，表示不作本轮满足性判定；不等于实现满足或缺陷已反证。已看见实现差异但按允许范围排除的，保留差异及理由，不改写原文预期。纯外观可按范围忽略；有效规范明确约定的反馈、动画、文字行为，先核其语义及功能/交互影响。功能/交互违约不能仅按载体排除；仅外观偏差按本轮范围裁量，保留规范、实现差异及排除依据，不标satisfied，也不自动全部计Bug。

另交紧凑的 `coverage-ledger.md`（或JSON等价账本），逐项对应本轮适用的有效需求条款与行为案例。至少记录条款定位、预期、前态/事件/守卫真假值、实际状态到消费者、判定及证据；共享同一证明可引用，不重复粘贴。文件/模块阅读列表、引用可解析与0 open交接不能替代逐行为语义闭合。合并沿用原作者细结果判定及其案例；漏项/不匹配须具名交回作者实际核证后补充，不能靠机械映射补结论。完成性说明必须与未判定条款及案例缺口一致。

顶层必填 `review_state`（completed / incomplete）及 `handoffs` 数组，交接字段与闭合规则见coverage-completion.md。存在open不能声明completed。blocked须说明真实缺失来源及现有材料不足以证明的维度；closed/out_of_scope须有结论和依据。此状态只表示本轮必要工作完成性，不表示穷尽Bug或实际集成验收通过。


待核项以 `proof_gaps` 数组仅列未决维度；每项含 `dimension`（fact / norm / reachability）、`gap_kind`（missing_source / conflicting_sources / unfinished_check）、`evidence_refs`、一句具体缺口及 `next_step`。真实缺少必要来源或必要语义时用 missing_source，并写最小所需信息及现有材料不足之处；同条件规范冲突无法消解时用 conflicting_sources；已有可读材料或必要推导尚未核完时用 unfinished_check。已核维度复用现有证据，不重复抄写。此字段不替代 status 或必填证据；必要 unfinished_check 未闭合时，整份 review_state 仍为 incomplete。

实现阻断统一记flow_reachability，不另用顶层blocked_by代替。basis及evidence_refs说明阻断输入、顺序、已保留状态与未证范围；它不是missing_source。仅真实缺少规则、局部合法输入依据或流程语义时才列proof_gaps。local_contract+confirmed可保留纯流程缺口，但必要的可读检查未完仍使review_state=incomplete；不能假设上游修复、跳过局部前提核证，或据一个受阻案例反证所有流程。

## 展示汇总与筛选（delivery-entry-v4）

以下定义定稿模板的数据与展示契约，后续审查复用既有渲染器并替换本轮数据，不逐轮重新设计页面。模板复用、必要校验及触发视觉复验的条件见 [delivery-maintenance.md](delivery-maintenance.md)；有效问题发现与核证优先于展示优化，不能省略计数、筛选、链接和证据包检查。

`status`、`severity`、`origin`及local-flow-v1判定不变。渲染器从findings派生`presentation_summary`：`confirmed_total`、`pending_total`、`severity_confirmed`（P0～P4）、`main_total`、`archive_total`与`version`，另派生`origin_confirmed`和`origin_labels`，不手填第二套数量。

- 确定问题：status=confirmed且finding_kind不是improvement；P0～P4只统计这些条目，五级合计必须等于confirmed_total。既有分类汇总仍单列新增、历史和归因未知，不把确定问题总数冒充新增Bug数。
- 待确认：conditional、requirement_unverified、unresolved的非改进条目。同根一个ID只计一次；详情保留原状态与暂定P等级，暂定等级不参与确定问题分布。
- 审计记录：refuted、inactive_config及improvement。保留原证据和排除/未启用理由，不计入主问题总数或待确认。
- 主问题总数=确定问题+待确认；全部findings=主问题+审计记录。局部confirmed的flow未证/被阻断不改列待确认，仍单列流程状态。覆盖账本中的unresolved记录不是finding，不凭覆盖行数派生待确认数量。

首页在严重度统计前增加三张归因卡，从`findings`生成`presentation_summary.origin_confirmed`，只计confirmed且非improvement：

- `new_or_omission`：origin为new_implementation/new_requirement/migration_gap，扣除下述旧代码×新配置项；显示“目标标签新增 / 遗漏”。
- `historical`：origin=historical，显示“基线标签历史问题”。
- `legacy_code_new_config`：origin=migration_gap且origin_subtype=legacy_code_new_config，显示“旧代码 × 新配置”。该可选子类只在已核基线旧实现、本次有效配置变化及同场景触发因果后填写；不能从标题、引用过配置文件或migration_gap枚举自动推断。
- `unknown`：origin=unknown，首页另行显示“归因未知”，不混入前三张卡。前三项互斥，与unknown合计等于确定问题数。原有new_bug_total继续包含旧代码×新配置，所以等于new_or_omission+legacy_code_new_config；不能把两种“新增”口径混用。

目标/基线标签依次从可选target_label/baseline_label、target_ref/baseline_ref、匹配固定SHA的git来源requested_ref读取；未登记时用“本次”“基线”，不写死具体项目版本或master，不查询实时分支。HTML、Markdown及JSON共享计数与标签。卡片可点击，切换到确定问题及对应互斥归因组，总览表与详情同步，仍可组合模块和搜索。数量不随筛选变化；零项也显示。

该附加子类不改local-flow-v1的既有origin含义，也不重判冻结事实。旧报告没有子类时不猜测、不回填；旧代码×新配置只表示已标记项数，其它migration_gap保留在新增 / 遗漏。新审查应依据原稿归因证据核实是否填写该子类；维护旧成果需用户授权后另记修订。

HTML主筛选提供全部问题、确定问题、P0～P4、待确认；选择P等级只显示该等级确定项。归因、模块与搜索可组合，显示命中数/主问题记录总数；首页统计按整份报告固定，不随搜索变化。数字卡可切换对应筛选。审计记录独立折叠展示，不被主筛选藏成“丢失记录”。Markdown同步分组及同口径数量。

HTML/Markdown均显示P0～P4分类标准、边界与统计说明；分类表直接复用references/severity.md，不维护不同表述的等级规则。旧冻结结果的用户授权展示更新另填`presentation_revision`（原技能版本、展示技能版本、快照和变更边界），不覆盖独立发现时的skill_version或重算缺陷判定。

新生成报告的finding填写module作为筛选/展示标签，归属须经现有证据核实；旧报告维护可单列标签补录记录，保持原判定字段。目标与基线分支由显式target_ref/baseline_ref或匹配固定SHA的git来源requested_ref提供，不必为了标签读取实时Git。

默认HTML采用摘要卡片：标题、等级、确定性、断言范围、流程状态、触发及影响直接可见；分析、反证、证据与附加判定可展开。来源、覆盖、历史等辅助账本折叠收纳但保留完整内容；搜索仍包含折叠的证据文本。移动端不以裁剪或截断替代关键触发条件。

网页问题详情之后提供可展开的完整输入清单和顶部锚点，列出全部sources：仓库/基线/目标固定版本，各文档与配表的原始文件名、绝对路径、固定版本/修订、允许用途状态及已有快照链接。原输入可用性/未提供/禁止项单列，明确所述阶段；不能把已提供且冻结等同已完整核证。通用渲染按实际source kind分组，未知类别仍保留，不以预设来源类型漏项；完整哈希元数据继续保留。

长正文应保留原换行，较长中文说明按句号/分号分段显示；不得用HTML默认空白合并把多段压成一行。路径、哈希、证据和标题允许容器内自动折行；输入/来源表在窄屏转为逐项带标签纵向内容，避免固定最小列宽迫使用户横向阅读。仅调整呈现，原文字符及数据字段不改。

网页顶部提供简短免责声明，详细条款可展开，Markdown同步、JSON保存同一份`disclaimer`内容。说明固定版本与允许输入边界、已完成验证的范围、确定性与流程可达性的区别、未发现不代表无缺陷，以及发布仍需实际验证；不得用免责文字替代证据、淡化已证问题，或把静态结论表述为线上已发生。条款按实际方法表述，不虚构运行验证。

## 维护记录与证据交付

独立发现、必要核证与一次终稿核对、范围核对、实际验收、唯一终版和打包规范见 [delivery-maintenance.md](delivery-maintenance.md)。可在review_history/附加账本保存phase、round、核查人与检查依据、采用修改、遗留项、快照/哈希及scope_audit；不改变local-flow-v1的既有必填字段，不要求回填旧冻结结果。展示修改沿用presentation_revision，事实续核另记原/新判定及证据。

验收记录分别说明结构、数量/筛选、链接、视觉和真实运行/集成的执行方式、结果及限制。默认只交付一个证据ZIP，标注实际大小、用途和SHA-256；本地与包内HTML共享同一事实源、分类和数量，包内页面不设置指向自身ZIP的下载链接。网页顺序、筛选同步及delivery.json展示清单见delivery-maintenance。记录唯一推荐入口、包内文件清单及SHA-256；报告或附件修订后同步重新打包，完整工作存档不默认混入分享包。
