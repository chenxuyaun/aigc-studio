"""Creative 内核：创作智能（Creative Integrity First）的数据模型与校验。

对应 docs/creative-engine/03-06 设计：
- CharacterConstitution：人物决策模型（03）
- ValueHierarchy / MotivationTrace：价值模型（04）
- StoryState / StateDelta：故事状态（05）
- DiagnosticReport / QualityReport：质量门诊断（06）

第一阶段（P0）只建数据模型与校验器，不接入生成管线（CREATIVE_ENGINE_ENABLED=0）。
"""
