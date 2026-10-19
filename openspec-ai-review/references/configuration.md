# 配置与运行

仅安装当前工程 `.codex/skills/openspec-ai-review`，不向 Claude/全局目录复制；必要时重开当前工程 Codex 会话。AI Review 由技能驱动，不新增 OpenSpec CLI 子命令。

优先使用已有 `config.local.json`，不存在时才复制 `config.example.json`，通过本机编辑器填写。个人配置由本目录 `.gitignore` 排除，禁止强制提交；配置和缓存需按私有源码设置本机权限。

| 字段 | 规则 |
| --- | --- |
| project | 报告项目名称，显示在 HTML 主标题、浏览器页签标题及“项目名称”字段；标题格式为“项目名称-审核版本号”（例如“魔音崛起-1.3.1”），使用 collect 时冻结的值。 |
| default_mode | 默认 review-publish，完整流程为 SVN 单个 HTML 报告加飞书同步发送；显式 review 只封存内部审核数据。 |
| git.url / username | 实际仓库与个人用户名。支持 HTTPS/SSH/本地测试路径；URL 不得含密码、token 或 query。 |
| git.local_path | 本机已有 Git 工程根的绝对路径；只读校验根目录和 origin 与 git.url 一致，不在此目录切换分支或更新代码。可留空用于没有本地工程的独立审核。 |
| git.auth | credential-manager-or-ssh。先用本机 Git Credential Manager 或 SSH 登录；脚本禁止交互密码提示。 |
| git.review_cache | 手工指定绝对路径，不能是当前工程或其父目录，建议工程外。每次独立 run，不改业务工作树。 |
| versions | target_branch + base_branch 精确唯一匹配 version；version 是明确的目标版本名，也是目录名/报告名前缀，不能包含斜杠、Windows 非法字符或保留名。不自动截取分支名；多工程用不同配置。 |
| openspec_changes | 目标快照该版本所有 change 的仓库相对目录，含 proposal/design/tasks/specs；归档后填实际 archive 路径。 |
| documents | 每项唯一 id、kind（requirements/api/design）、source（target/local）、path；target 支持仓库相对目录/文件，local 为绝对文件。固定字节及 SHA256。 |
| svn.working_copy | **手工配置**已 checkout 的工作副本根；不自动推测或 checkout。 |
| svn.repository_url | 该工作副本根对应 URL，脚本校验完全匹配。 |
| svn.report_root | **手工配置**工作副本内已纳管的报告根目录绝对路径，例如 `D:/WorkSpace/MiniGame/war3d/客户端`。报告存入其下 `<version>/`，发布时自动创建缺失版本文件夹；报告根本身须已纳管。 |
| svn_version_dir | 兼容旧配置：仅未配置 report_root 时使用，须提前创建并纳管。新配置使用 report_root + version，无需逐版本手填路径。 |
| svn.username / auth | local-cache；username 可填写个人账号，留空则使用本机已有 SVN 登录缓存。先在本机 SVN 登录，不把提交作者推断为登录账号，不传 --password。 |
| svn.executable | svn 或 svn.exe 绝对路径；TortoiseSVN 需安装命令行组件。 |
| feishu.app_id / app_secret_env | 自建应用 ID 和本机 secret 环境变量名称，不能填写 secret 本体。 |
| feishu.chat_id / chat_name | 手工填写客户端开发-U3D的唯一 chat_id；脚本查询并核对群名，不只依赖名称。 |

飞书机器人需入群，应用获取群信息/上传文件/机器人发送消息权限需生效。使用国内飞书 open.feishu.cn，不接受任意第三方 API 地址。恢复可能需要读取消息权限；不能在终端打印 secret。

本机已补装 TortoiseSVN 的 command line client tools，个人配置使用 `C:/Program Files/TortoiseSVN/bin/svn.exe`，不依赖当前 Codex 进程刷新 PATH。脚本对本地目标使用工作目录加精确相对路径，避免当前 Windows 环境直接传中文绝对路径时无法识别节点。只读连通检查不会证明 SVN 提交权限。

## 版本目录与文件名

例如 version 为 `1.2.0`，发布路径为 `<report_root>/1.2.0/1.2.0-ai-review-<run_id>.html`。文件和目录均包含目标版本，run_id 保留同版本多次审核，避免覆盖历史报告。目录不存在时先核对 SVN 远端：已存在则浅更新；远端也不存在才创建，并和报告在同一次精确提交中纳管。不接管已有未纳管目录、同名文件或他人添加的目录。

`versions` 未配置时停止并补充目标分支、主干分支、目标版本及该版本文档映射，不生成虚构的默认版本。可按下面结构添加条目，替换所有示例内容：

```json
{
  "version": "1.2.0",
  "target_branch": "release/1.2.0",
  "base_branch": "master",
  "openspec_changes": ["openspec/changes/实际change目录"],
  "documents": [
    {"id": "requirements", "kind": "requirements", "source": "target", "path": "openspec/changes/实际change目录/specs"},
    {"id": "api", "kind": "api", "source": "local", "path": "D:/ReviewDocuments/1.2.0/api.md"},
    {"id": "design", "kind": "design", "source": "target", "path": "openspec/changes/实际change目录/design.md"}
  ]
}
```

在线文档先导出本地，记录来源和导出时间。PDF/Word/图片需要 Codex 使用可用工具解析；脚本复制字节不等于已理解。无法解析列缺口。不适用接口文档须说明依据。

```powershell
python .codex/skills/openspec-ai-review/scripts/review.py collect --config .codex/skills/openspec-ai-review/config.local.json --target release/1.2.0 --base master
# 按下文增量审核指南解析文档、建立 plan，执行 start 和各模块 checkpoint。
python .codex/skills/openspec-ai-review/scripts/review_progress.py assemble --run C:/ReviewCache/newproject_client/RUN_ID
python .codex/skills/openspec-ai-review/scripts/review.py render --run C:/ReviewCache/newproject_client/RUN_ID --review C:/ReviewCache/newproject_client/RUN_ID/review.json
python .codex/skills/openspec-ai-review/scripts/publish.py --config .codex/skills/openspec-ai-review/config.local.json --run C:/ReviewCache/newproject_client/RUN_ID --mode review-publish
```

最后一条才在 SVN 版本目录生成唯一 HTML 文件、提交并发送飞书，须与选定模式一致。default_mode 由技能读取，默认完成采集、模块审核、汇总封存和发布流程，不会让 collect/render 自动发布。禁止另存 HTML 到工程或缓存，禁止导出 PNG、JPG、截图、PDF 或配套资源；HTML 内联样式和脚本。

## review_cache

每次生成 `时间-随机ID/`：repository.git 是独立对象库，snapshot 是固定目标工作树，documents 是文档副本，introduced.diff/heads.diff/changes.txt 是差异，context.json 是 SHA/哈希/缺口。新增 input-index.json 保存去重后的分类索引并纳入证据哈希，input-usage.jsonl 记录分段读取输出量，可选 model-usage.json 保存真实运行用量；使用方法见 [输入索引与用量](input-budget.md)。AI 写 review.json，render 将 HTML 内容和哈希封存在 report-manifest.json（schema_version=2），不生成 HTML 文件；publish 只在 SVN 版本目录生成 HTML，并在缓存保存 publish-state.json。上述缓存均为内部取证/恢复数据，不作为输出附件，不复制到 SVN、工程 review-output 或飞书。

fetch 原子获取显式 refs；断网、分支不存在、无共同祖先、多 merge-base 均停止，不用旧缓存。发布代表已记录 SHA；有新提交需重新审核。LFS/submodule 不自动拉取，涉及部分须补充固定证据或标明限制。

新运行额外冻结 code-inventory.json（全部目标 C# 的 Git 对象及模式），context 保存审核规则哈希与 progress_version。按 [文档缓存、进度与增量审核](incremental-review.md) 建立 plan 和 progress.json；render 要求覆盖完整并封存 progress.final.json 及其哈希。文档解析缓存跨运行存放在 review_cache/.document-cache，按文档内容和解析版本复用。增量审核仍先成功 collect，旧运行不改写；发布重试只走原 publish 恢复流程。

差异采集固定只包含 `.cs`（大小写不敏感），不需要增加个人配置。两份 diff、changes.txt 和索引均不包含动画、材质、模型、Prefab 或其他非 C# 文件。完整工作树仍用于检查未修改的公共 C# 实现，需求文档单独冻结；资源留在快照不代表纳入审核。新运行标记 review_scope=csharp-only，旧运行封存与发布保持兼容。

缓存不自动删除；人工清理前保留 context、review、manifest、publish-state，以便审计/恢复，HTML 保留在 SVN 路径。不能丢弃状态后重发。不同运行独立，单次运行和 SVN 报告根目录有排他锁；崩溃遗留锁需确认进程结束并核对状态再手工删除。
