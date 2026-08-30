"""Core Runtime 抽象层。

P0 目标：从 services/task_runner.py 拆出与 Runtime 通用职责相关的部分
（调度状态、任务进度常量、取消检查、启动恢复），但**保持现有行为不变**。

不引入新接口；不修改 Provider / Domain 行为；只为后续 P0-P4 重构
建立"Core 不依赖 Domain"的物理边界。
"""
