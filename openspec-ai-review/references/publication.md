# 发布与恢复

在内部 manifest 封存 HTML 内容及哈希 → 配置及飞书群核验 → SVN 检查 → 仅在对应 SVN 版本目录生成 HTML → 精确提交报告 → 远端回读核对 → 直接上传该 SVN 路径的 HTML → 文件消息 → 文本摘要。摘要仅包括版本、分支与 SHA、过滤后报告内 P1–P4 问题数量、SVN revision、文件名和 run ID，不包含审核结论、门禁、证据/需求/验证状态、已完成项、后端联调或配置辅助项。报告为单个自包含 HTML，不生成或发布 PNG、JPG、截图、PDF、配套资源或其他文件附件。

发布模式代表已授权这次完整流程，无需逐步询问。缺发布工具/权限/凭据时报告发布失败原因，不索要密码。问题等级不阻止发布。安装及离线测试不产生真实外部写入。

## SVN

工作副本根、已纳管报告根手工配置。校验 wcroot、URL、路径，拒绝越界链接、switch 和冲突。报告存入 `<report_root>/<version>/<version>-ai-review-<run_id>.html`；版本名必须是有效的单个 Windows 目录名。

版本目录缺失时先列举 SVN 远端报告根，远端已有版本目录则 depth empty 更新；远端也没有才创建本地版本目录。创建前将目录归属写入 publish-state 的 svn_owned_directory，单独 depth empty 添加，不递归添加其中任何文件。随后将新目录和本次 HTML 作为明确的两个目标一次提交，depth empty，唯一提交标记；已有版本目录只提交本次 HTML。报告根目录本身不能被自动创建或整树提交。

已有未纳管/他人新增目录、目标版本同名文件、目录属性变更或无关文件混入本次新目录均停止，不接管或覆盖。无关修改保留，不能提交、还原或清理。文件名前缀含版本且带 run ID，同名异内容立即停止。使用个人 username 或留空使用本机 SVN 登录缓存，不传 password 或绕过证书。

## 状态恢复

manifest v2 在 review_cache 内封存 HTML 内容、哈希、SHA、统计，不另存 HTML 文件；本地 publish-state 原子保存 report_path（唯一的 SVN HTML 路径）、SVN revision、file_key、file_message_id、summary_message_id。首次发布绑定目的地，续传不可换群/目录或改 HTML。兼容已有 v1 manifest 的续传，从旧缓存读取封存内容后仍只向 SVN 目标写报告并从该路径上传；不自动删除历史产物。

| 情况 | 重跑行为 |
| --- | --- |
| 预检明确失败 | 修复配置/环境后重试。 |
| 新版本目录已创建或已 add，报告未提交 | 根据 svn_owned_directory 恢复，只接受该运行创建的目录，精确提交目录和报告；不重复纳管其他文件。 |
| SVN 已开始，结果未知 | 先查远端文件哈希和唯一提交标记；完全匹配恢复 revision，否则暂停，不盲目重交。 |
| SVN 成功，上传失败 | 跳过 SVN 重试上传；孤立上传文件不会形成群重复消息。 |
| 上传成功，文件消息明确被拒 | 保留 file_key，修复后只重发消息。 |
| 文件消息成功，摘要失败 | 只补发摘要。 |
| 完全成功 | 返回已有记录，不重发。 |
| 消息网络超时/中断/响应异常 | 保留 pending 和 UUID，先核对群记录，不自动重发。 |

稳定 UUID 辅助平台去重，不依赖其时效保证永久幂等。明确非零业务错误允许重试；网络/HTTP/响应解析错误保守视为不确定。状态不得提交 SVN 或发送群。

## 人工核对不确定结果

先备份状态并确认没有运行中的进程。SVN 用远端 `svn log --xml`、`svn cat` 核对 run 标记和 SHA256；脚本会自动恢复已提交 revision。若已证实未提交，仅移除 svn_pending，并在 recovery.md 写核查人、时间与证据；内容冲突不能覆盖。

飞书按群/时间/文件名/run ID 查记录，必要时用平台查询 API。确认已发，将 file_message_id 或 summary_message_id 写回状态，移除 file_pending 或 summary_pending；确认未发，仅移除对应 pending 再重跑。在 recovery.md 记来源、时间、消息 ID、结论。无法确认保持暂停，不能删状态或新建运行绕过去重。

HTML 更新或补测需新 run，可在摘要说明替代关系。真实服务联调需配置后执行；飞书使用 stream 类型上传 HTML，组织策略拒绝 HTML 时保留 SVN 成功状态并报告发送失败，不能偷偷更换格式或声称成功。
