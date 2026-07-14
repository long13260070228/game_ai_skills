# AGENTS.md

本项目使用 game-ai-skills 作为团队 AI 协作规范。

## Skill 使用规则

当用户要求“把需求转成 OpenSpec”“生成 proposal / design / specs”“从文档生成技术方案”时，优先使用：

- gameai_openspec_from_doc

当用户要求“需求分析”“分析活动文档”“拆解需求”时，优先使用：

- gameai_analyze_requirement

当用户要求“生成测试用例”“自测清单”“QA 用例”时，优先使用：

- gameai_testcase_generator

当用户要求“分析捕鱼活动”“强发库”“库存池”“掉落”“捕鱼配置”时，优先使用：

- gameai_analyze_activity
- gameai_check_config

当用户要求代码审查时：

- Lua / Cocos2d-lua 使用 gameai_code_review_cocos2d_lua
- Unity C# 使用 gameai_code_review_unity
- Cocos Creator / Cocos2d 使用 gameai_code_review_cocos_creator

当用户要求“发版检查”“上线前检查”“热更检查”时，使用：

- gameai_check_release

当用户要求“性能分析”“卡顿”“内存”“FPS”“包体”时，使用：

- gameai_check_performance
