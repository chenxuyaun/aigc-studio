"""Providers - 具体模型 Provider 实现包（P2-2 从 providers/ 根归位）。

基础设施留根目录：base.py（抽象）、registry.py（类型分派）、failover.py（候选链）、
mock/（测试隔离实现）。本包只放「对接外部模型服务」的具体实现：
openai_compatible / chat_image / comfyui / minimax_video / edge_tts / musicgen /
zarklab / huggingface。

P2 边界：providers/<name>.py 保留轻量 facade（旧 import 与测试 patch 路径兼容）。
"""
