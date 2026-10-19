# 当前工程约定

以下是初始盘点结果，执行时重新读取实际文件，以目标模块当前代码为准。

| 项目 | 参考位置或约定 |
| --- | --- |
| Unity | `ProjectSettings/ProjectVersion.txt`：2021.3.23f1 |
| UI | UGUI、TextMeshPro；依赖版本见 `Packages/manifest.json` |
| 窗口业务代码 | `Game/Scripts/Window/Windows/<Module>/` |
| 窗口基类 | `Game/Scripts/Window/WindowBase.cs`、`WindowActivityBase.cs` |
| 窗口入口 | `Game/Scripts/Utils/UtilsWindow.cs`、`Game/Scripts/Utils/UI.cs` |
| Prefab | `Assets/Res/Prefab/<Module>/`；某些模块另有 `Prefabs/` 子目录，遵循相邻资产 |
| 通用运行资源 | `Assets/Res/Common/Common/` 中的红点、货币、提示等 Prefab |
| 编辑器组件入口 | `Assets/Editor/CustomComponent.cs` 与 `Assets/Editor/CustomComponents/` |
| 编辑器扩展 | `Assets/Editor/`；不得直接依赖未参与 Editor 编译的热更新类型 |
| 资源链路 | MotionFramework / YooAsset；依据当前收集配置核对资源可加载性 |

## 窗口路径契约

`WindowBase.ShowInAction()` 在入场动画启用时使用根节点下的 `bg`（含 Graphic）与 `UIWindow`。
`SetCloseButton()` 仅在未传入自定义按钮时默认查找 `UIWindow/Cont/ButtonClose`。
这些规则有调用条件，不能要求每个 Item、Page 或自定义窗口都具有同一层级。

例如 `UIWeaponTrialWin.cs` 使用 `UIWindow/centerNode`、`main_bg`、`cangBao_bg` 等路径，说明窗口存在自己的绑定约定。检查实际目标脚本及它调用的页面/Item 类，不要把此例复制成所有模块模板。

窗口控制类属于热更新代码并通过窗口框架创建，不要把普通窗口类误作为 MonoBehaviour 挂到 Prefab。确需组件时确认它继承 Unity 可序列化组件基类且在 Editor 中可用。

## 适配与资源复用

读取相邻窗口和根 UI 的 Canvas、CanvasScaler、sorting、摄像机策略。安全区通常由代码调用 `UtilsScreen.SetRectInSafeArea`，契约应指明目标 RectTransform，避免生成时和运行时重复扣减安全区。

需要复用编辑器模板时核对其运行依赖。运行 Prefab 不得残留仅在 `Assets/Editor` 下可用的资源引用；使用现有运行资源或将需要的资产及依赖正确落入运行目录。

字体、材质、图集和资源加载设置遵循目标模块，不新增另一套 Addressables/Resources 加载体系。不批量修改共享 Atlas 或字体来满足单一页面。
