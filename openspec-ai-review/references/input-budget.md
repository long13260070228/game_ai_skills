# 输入索引与用量

采集仅生成 C# 差异，需求文档和固定目标快照仍保留，模型通过 `scripts/review_input.py` 按需读取 C# 实现。以下命令的 `<run>` 都是 collect 返回的独立缓存目录。索引、用量记录属于内部数据，不进入 SVN/飞书报告。

## 索引优先

```powershell
python .codex/skills/openspec-ai-review/scripts/review_input.py index --run <run>
python .codex/skills/openspec-ai-review/scripts/review_input.py index --run <run> --category code --limit 40
python .codex/skills/openspec-ai-review/scripts/review_input.py index --run <run> --path-contains SeaScroll --offset 0
```

先看汇总，再按需求/模块选 C# 文件。`next_offset` 非空时继续分页；筛选结果不代表整个审核范围。新运行的类别只有 code，采集使用 `:(top,glob,icase)**/*.cs` 同时匹配根目录和子目录及大小写扩展名；不匹配 `.cs.meta`、其他语言或资源。added/deleted 为 null 表示 Git 认为该 C# 文件是二进制，0/0 也可能有模式变化，需据实处理。

`input-index.json` 记录文件路径、增删行数、分类、差异字节范围及哈希。两份 diff 哈希相同时只索引一次；不同 diff 的相同文件差异块也只索引一次。每条 `comparisons` 标记 introduced、heads 或两者，先处理 introduced，再补充 heads 独有内容。只合并完全相同的块，不做相似性摘要或语义合并。

introduced.diff / heads.diff / changes.txt 从 Git 生成时就限定为 C#，不先生成全资源差异再过滤；索引同样只接受 C#。context.json 和索引标记 review_scope=csharp-only。相同基线时第二份直接复制，避免重复运行 Git diff。文件名和封存/发布协议兼容既有流程；旧运行保持原始范围和证据，不修改旧缓存，新采集才使用 C# 范围。文档解析缓存、模块断点和跨次复用见 [增量审核](incremental-review.md)。

## 分段读取

```powershell
python .codex/skills/openspec-ai-review/scripts/review_input.py read --run <run> --id D000001
python .codex/skills/openspec-ai-review/scripts/review_input.py read --run <run> --id D000001 --offset <next_offset>
python .codex/skills/openspec-ai-review/scripts/review_input.py read --run <run> --source snapshot --path Assets/Scripts/Example.cs
python .codex/skills/openspec-ai-review/scripts/review_input.py read --run <run> --source snapshot --path Assets/Scripts/Example.cs --line 120
python .codex/skills/openspec-ai-review/scripts/review_input.py read --run <run> --source documents --path <context中documents之后的相对路径>
```

默认每次最多 24,000 字节、200 行，可用 `--max-bytes` / `--max-lines` 调整，上限 32,000 字节、400 行。预算针对原文，JSON 封装和工具开销另计，不是精确 Token 上限。单批输入以约 6k–10k Token 为软目标，超出时拆批，不丢弃证据。

offset 是文件或差异块内的字节位置，使用返回的 next_offset 续读，避免自行切开 UTF-8 字符。也可用 `--line` 从搜索定位的行直接读取，不能与非零 offset 同用。first_line 是该文件/差异块内的行号；diff 源码行号以 @@ 标记为准。starts_mid_line / ends_mid_line 提醒超长行被分段。complete 仅表示该文本已到末尾，不证明需求覆盖或语义审核完成。

代码按完整方法和调用链理解，必要时补读未改动的公共 C# 实现。检索目标实现时使用 `rg -n -g '*.[cC][sS]'` 并限定模块、符号与输出范围。新运行的 snapshot 读取只允许 C# 文件；有效需求通过 documents 读取。动画、材质、模型、Prefab 等不做差异对比，也不再按疑点展开资源绑定检查；仅由 C# 可证明的资源加载/释放逻辑缺陷仍在范围内。

UTF-8 文档和 DOCX 优先使用 document_cache.py 缓存解析并分页读取；PDF、图片、二进制或非 UTF-8 文件由适当工具解析。读取失败要保留内部待处理事项，不标记已审核。必要中间数据仍只留在 review_cache。使用其他工具取得的内容不在本脚本用量统计内。

## 测量而非猜测

```powershell
python .codex/skills/openspec-ai-review/scripts/review_input.py usage --run <run>
python .codex/skills/openspec-ai-review/scripts/review_input.py usage --run <run> --model-usage <运行环境导出的用量JSON>
```

成功的 index/read、文档分页和进度命令输出自动记录到 input-usage.jsonl：输出 UTF-8 字节数、字符数、粗估 Token。index/read 另记录读取证据范围，usage 汇总其重复读取字节；重叠范围按内容身份求并集。用量日志不保存源码正文，不代表审核结论；模块覆盖与断点另存 progress.json。

`estimated_tokens_utf8_div4` 只是“输出 UTF-8 字节数 / 4 向上取整”的粗估，不是模型 tokenizer 结果或实际计费量；不包含会话历史、其他工具、推理及后续重复上下文。真实用量缺失时 model_usage 为 null，不填 0，不宣称已实现某个节省比例。

真实用量可导入如下结构（示例数字不是实际用量）：

```json
{"id":"unique-call-or-batch-id","source":"runtime usage export","input_tokens":10000,"output_tokens":1000,"cached_input_tokens":8000,"reasoning_tokens":500}
```

id/source/input_tokens/output_tokens 必填，后两项可选；每条必须来自真实运行统计且覆盖互不重叠的调用或批次。同 id 同数据导入不重复计数，不同数据拒绝覆盖。字段沿用数据源的计数语义，缓存和推理数据不得再与输入/输出简单相加。无自动模型计量接口时，只报告可测量的工具输出和估算范围。

对比优化效果时使用固定 SHA、固定文档和相同模型设置；检查已知 C# 问题及代码需求覆盖，特别包括零 C# diff 需求遗漏、公共 C# 依赖、删除/重命名、子目录与大小写扩展名。确认仅有资源变更时 C# 差异为空、需求仍保留。预算不足继续分批处理，不能据此封存不完整的 C# 审核。
