# 文档缓存、进度与增量审核

仍仅审核 C#，不比较资源。`review/review-publish` 控制发布；下文的 `full/incremental` 控制审核结果复用，两个概念独立。所有计划、进度和解析缓存只保存在 review_cache 内，不进入 HTML/SVN/飞书。

## 文档解析缓存

```powershell
python .codex/skills/openspec-ai-review/scripts/document_cache.py --run <run> --file documents/requirements/spec.md
python .codex/skills/openspec-ai-review/scripts/document_cache.py --run <run> --file documents/requirements/spec.md --offset 20
```

使用 context.json 中的精确文档路径。先验证本次冻结文档哈希，再按「内容哈希＋扩展名＋解析器版本＋提取规则版本」查找 review_cache/.document-cache。支持 UTF-8 文本文档和 DOCX 正文、表格中的段落、页眉页脚、脚注和尾注。保留原文行号或 XML 部件/段落锚点，DOCX 删除文本显式标记，不自动判断需求取消。图片/对象、修订、域、自动编号会提示核对原文；不支持的格式返回 manual-required，不能视为已经理解。PDF/图示等仍按需用可用工具解析，必要中间数据只保存在缓存。

每页默认最多 20 个文本块、6,000 字符；next 含 offset/text_offset，超长段落按两者续读。摘要不替代原文，章节位置来自原始解析结果。缓存损坏时报错，不沿用损坏结果。不同 run 可复用相同解析结果，但始终校验本次源文件。解析结果不代表已完成需求审核。

## 建立有效需求与模块计划

首次审核先核对需求增删改、取消记录及版本边界，在运行目录写 plan.json。以下是结构示例，需替换为真实映射：

```json
{
  "requirements_complete": true,
  "requirements_basis": "已核对本版本需求及取消/替代记录；列举实际文档与核对依据",
  "review_profile": "记录实际审核模型/方式及本次额外审核要求",
  "requirements": [{
    "id": "REQ-001", "module": "reward", "description": "领取期间禁止重复提交",
    "sources": [{"file": "documents/requirements/spec.md", "anchor": "line:12"}]
  }],
  "modules": [
    {"id": "shared", "paths": ["Assets/Scripts/Common"], "depends_on": [], "dependencies_complete": false},
    {"id": "reward", "paths": ["Assets/Scripts/Reward"], "depends_on": ["shared"], "dependencies_complete": false}
  ]
}
```

paths 为大小写精确的仓库相对 C# 文件或目录前缀；`*` 表示全部 C#。所有 introduced/heads 中的 C# 路径（包括删除文件）必须分配到模块，需求也必须有所属模块；零 diff 仍建立需求覆盖。跨模块调用、公共服务、事件发布/订阅、反射/注册入口和跨文件 partial 等相关代码都要纳入依赖范围。只有实际确认依赖范围完整时才填写 dependencies_complete=true；工具不把关键词搜索当作可靠 C# 调用图。未知依赖保持 false，有 C# 变化就回退完整审核。

review_profile 是复用条件的一部分；切换审核模型/方法或增加用户要求时应更新它。规则文件/脚本的哈希由工具自动固定。计划一旦开始不原地替换；发现遗漏可新建 run，提供修正计划并做完整审核，避免保留错误覆盖。

## 开始、续审与保存模块结果

```powershell
python .codex/skills/openspec-ai-review/scripts/review_progress.py start --run <run> --plan <run>/plan.json --mode full
python .codex/skills/openspec-ai-review/scripts/review_progress.py status --run <run>
python .codex/skills/openspec-ai-review/scripts/review_progress.py status --run <run> --module reward
python .codex/skills/openspec-ai-review/scripts/review_progress.py checkpoint --run <run> --file <run>/reward-checkpoint.json
```

模块 checkpoint 示例：

```json
{
  "module": "reward",
  "status": "in_progress",
  "notes": "实际已检查的 C# 入口、需求、证据位置以及下一步",
  "pending": ["核查超时回调中的在途标记恢复"]
}
```

in_progress 可附 review 草稿，结构沿用 review-contract，保存已记录需求/问题/检查；草稿不代表模块完成。完成时 status=complete、pending=[]，并必填 evidence_kind=static 或 runtime、review（现有完整 review.json 结构，但只包含本模块全部需求及相关问题）。notes 必须记录实际覆盖依据。模块间需求/问题 id 全局唯一；不为节省预算省略未完成需求。静态证据不得标为运行验证通过。

相同 run 再次 start 自动续审，读取 status 后继续 pending 模块，不重新审核已完成模块。工具校验冻结文档、diff、索引、C# 清单、目标 HEAD、工作树中的 C# 和规则是否变化；变更则停止，需重新采集。封存后的 run 不再接受进度修改。

## 增量审核和失效规则

新提交先执行 collect，新 run 独立取证，采集失败仍停止，不能回退旧缓存。然后：

```powershell
python .codex/skills/openspec-ai-review/scripts/review_progress.py start --run <new-run> --mode incremental
python .codex/skills/openspec-ai-review/scripts/review_progress.py start --run <new-run> --plan <new-run>/plan.json --previous <previous-run> --mode incremental
```

默认选择同一 cache、仓库/版本映射中最近的已完整封存基线。没有有效基线须提供 plan 并执行完整审核；未完成的历史 run 只可原地续审，不能作为增量基线。旧版无进度记录的报告可照常发布恢复，但不能作为复用依据。显式指定的基线损坏或不匹配时停止，自动选择时忽略无效候选。封存进度、审核结果、context、C# 清单均验证哈希，复用结果记录来源 run 和原始审核 SHA。

复用条件：

- 需求文档及缺口、模块/需求计划、审核方式、基线 SHA、merge-base、审核规则必须一致。任一变化则完整审核；文档变化需要重新建立有效需求计划，不自动沿用旧验收条件。当前先按整份文档失效，未做章节级语义合并。
- 对比全部目标 C# 的 Git 对象及模式清单，识别新增、修改、删除和重命名。根据模块目录及已确认依赖，重审变化模块和传递依赖它的模块；同时比较各模块对应的 introduced/heads 差异内容。
- 有任何 C# 变化且依赖信息不完整，或变化落在已知模块范围之外，回退完整审核；新增 diff 路径必须先在计划中分配模块。
- 有未解决问题、无法确认的需求或运行时证据的模块必须重新核查；只有静态且无上述待处理事项的模块允许复用。资源变更不会触发 C# 差异审核。

失效模块保留 previous_review，查看 `status --module` 获取旧问题。每条旧 open 问题在完成 checkpoint 时都要填写 rechecked_findings，例如：

```json
{"ISSUE-001": {"resolution": "resolved", "evidence": "当前 C# 文件/行号及本次复核事实"}}
```

仍 open 的问题必须保留在当前模块 review.findings 中；取消/替代的需求据实标记 removed/cancelled/superseded 并提供依据。有旧 open 问题的模块不能从计划直接移除，先保留模块并完成问题复核。工具校验记录结构，不代替模型确认语义事实。

## 汇总与封存

```powershell
python .codex/skills/openspec-ai-review/scripts/review_progress.py assemble --run <run>
python .codex/skills/openspec-ai-review/scripts/review.py render --run <run> --review <run>/review.json
```

assemble 将全部完成模块合并为 review.json，验证需求/问题关联。新运行的 render 强制检查所有模块 complete、无 pending，且 review 与 checkpoint 一致；不能绕过待办直接写空报告。progress.final.json 和哈希随报告封存，用作下次基线，发布报告的内容和位置保持既有约束。发布中断仅恢复 publish.py，不重新做语义审核。

用量统计包含文档分页和进度命令的输出。实际模型 Token 仍仅接受真实运行统计；不会把缓存命中或字节减少换算成已证实的 Token 节省比例。
