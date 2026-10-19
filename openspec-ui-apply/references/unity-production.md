# Unity Prefab 制作执行规则

## 执行通道

Prefab 制作前必须已确认设计效果图路径、UI 资源路径、Prefab 保存路径和 Prefab 资源命名。保存路径必须是工程内 `Assets/` 下的 `.prefab` 文件，资源命名必须与路径 basename 完全一致；不满足时停止，不生成临时 Prefab 代替正式输出。

先检查当前可用工具与 Unity 状态，再选择：

- 已配置的 Unity 编辑器接口：在主线程调用编辑器 API，回收结构与保存结果。
- 项目内 Editor 工具：按页面契约编写范围明确的菜单/静态入口，在已打开的 Editor 内运行。
- Unity batchmode：工程未被另一个 Editor 占用时才使用匹配版本的 Unity 和 `-executeMethod`。日志写到指定路径，执行后检查退出码、编译错误及资产加载结果。

不要为启动 batchmode 强行关闭用户 Editor 或删除 Unity 锁文件。不能运行 Unity 时，交付契约、资源映射及待执行工具，明确 Prefab 仍待制作/验证。
渲染截图需要图形设备，不使用 `-nographics` 的结果声称视觉验收通过。

## 导入和资源映射

- 映射每个切图到节点，记录 Sprite/多 Sprite 子资产、源文件路径、GUID、尺寸、border、pivot、PPU、字体及材质。多 Sprite 不仅凭同一个纹理 GUID 区分。
- 使用 `AssetDatabase.LoadAssetAtPath` 或子资产加载接口获取真实对象引用；不手填猜测的 GUID/fileID。
- TextureImporter 的 Sprite 模式、透明、压缩、最大尺寸、过滤、九宫格等取自项目和资源要求。不自动给所有图片相同设置。
- 保留已有 `.meta`。新资产通过 Unity 导入生成 `.meta` 并纳入交付。移动资产优先使用 `AssetDatabase.MoveAsset`，不删除重建已有资源。

## 构建与更新

- 更新已有 Prefab 时采用 `PrefabUtility.LoadPrefabContents`，在隔离内容中局部更新，用 `SaveAsPrefabAsset` 保存，并在 finally 中 `UnloadPrefabContents`。
- 新建时使用 RectTransform 根或合适模板，子 Prefab 通过 `PrefabUtility.InstantiatePrefab` 复用，保存成功后清理临时对象。
- 保留 Prefab Variant/嵌套关联，除非任务需要，不展开整个 Prefab、不将实例修改应用到共享源资产。
- 写入前检查目标路径及已存在文件。生成节点按稳定路径识别：存在则更新必要字段，不存在才创建；组件同理，不无条件 AddComponent。
- 保存前再次校验目标路径和资源命名：路径父目录存在或由 Unity 创建，文件名与契约命名一致，扩展名为 `.prefab`。如果目标已存在，先报告将更新现有资源，不得静默覆盖。
- 仅清理本次明确拥有且不再使用的节点，避免删除人工添加的动效、绑定和布局。不通过删除 `.meta` 重建来消除冲突。
- 如果使用临时构建脚本，说明其位置和复跑方式；只有本次创建且确定不再需要的临时文件才可清理。可复用工具与一次性脚本分开说明。

## 组件和显示

- 保留窗口框架管理的根 Canvas 策略，Item 通常只需 RectTransform 和控件。文本组件依据项目使用 TMP 或旧 Text，不能随意替换而破坏绑定。
- 真实按钮需要 Button、targetGraphic 和可用的射线命中区域；纯装饰按需求关闭 raycastTarget。背景遮罩是否阻挡点击依契约配置。
- ScrollRect 需要 content、viewport、方向和模板；LayoutGroup 与 ContentSizeFitter/手动定位不能互相竞争同一尺寸。
- 图片拉伸选择合适的 Image 类型；Sliced 需要有效 border，不能仅设置类型就认为九宫格成立。
- 字体使用已有 TMP 字体资产及 fallback，验证中文与动态文案；不要新建空字体资产充当验收。
- 动效复用提供的 Animator、Spine、UIParticle 等资产与组件，缺少来源时记录缺口，不根据单张静态图伪造动画需求。

## 校验实现要点

可以按契约编写本次所需的 Editor 校验入口。本 Skill 不附带已安装的通用 Validator，不引用不存在的工具名。

校验应重新加载保存后的 Prefab，遍历包含非激活子物体的组件；检查 Missing Script、必需节点、组件类型和必需资源引用。用 SerializedObject 检查引用时要区分允许为空的字段与真正损坏的对象引用，不能把所有 null 都报错。

用 `AssetDatabase.GetDependencies` 辅助核对依赖，但它不能证明动态加载路径有效。动态 Item、Atlas/Sprite 名称、资源收集规则需结合代码和真实窗口加载验证。

预览时记录尺寸、摄像机、Canvas 缩放、模拟数据和状态。不要提交仅供截图的调试场景或把临时 mock 数据存入正式 Prefab。用可复现的预览与真实入口测试分别记录证据。
