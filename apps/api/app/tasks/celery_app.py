from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "aigc_studio",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.generation_tasks",
        "app.tasks.account_health",
        "app.tasks.register_batch",
        "app.tasks.story_tasks",
        "app.tasks.agentlist_tasks",
        "app.tasks.asmr_tasks",
        "app.tasks.inspection_tasks",
        "app.tasks.backup_tasks",
        "app.tasks.distill_tasks",
    ],
)
celery_app.conf.update(
    task_ignore_result=False,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # 任务超时兜底：asyncio.run 任务若卡死（跨 loop 连接等），
    # 超时后被杀释放 worker 进程，避免任务池被占满
    task_time_limit=600,
    task_soft_time_limit=540,
    task_default_queue="image",
    task_routes={
        "generate_text": {"queue": "text"},
        "generate_image": {"queue": "image"},
        "generate_video": {"queue": "video"},
        "generate_audio": {"queue": "audio"},
        "account_health_check": {"queue": "maintenance"},
        "register_batch": {"queue": "maintenance"},
        "generate_chapter_task": {"queue": "text"},
        "serial_tick": {"queue": "maintenance"},
    },
    beat_schedule={
        # grok2api 账号健康度巡检：每 30 分钟自动禁用废号（避免路由反复撞废号）
        "account-health-every-30m": {
            "task": "account_health_check",
            "schedule": 1800.0,
            "options": {"ignore_result": True},
        },
        # 注册批次：默认每 12 小时自动补一批新号（REGISTER_BATCH_INTERVAL_HOURS 可调）。
        # 注：单批 10 号需数小时，4h 间隔会批次叠加且频繁注册易触发 Grok 风控，故放慢
        "register-batch-scheduled": {
            "task": "register_batch",
            "schedule": float(os.environ.get("REGISTER_BATCH_INTERVAL_HOURS", "12")) * 3600.0,
            "kwargs": {"run_count": int(os.environ.get("REGISTER_BATCH_COUNT", "10"))},
        },
        # AgentList 目录每周一 03:00 自动刷新
        "agentlist-sync-weekly": {
            "task": "agentlist_sync_task",
            "schedule": crontab(minute=0, hour=3, day_of_week=1),
        },
        # ASMR 聚合每日 03:30 增量同步（全量在首次接入时手动触发）
        "asmr-sync-daily": {
            "task": "asmr_sync_task",
            "schedule": crontab(minute=30, hour=3),
            "kwargs": {"mode": "daily"},
        },
        # Story Forge 连载 tick：每分钟扫描到期调度，创建章节生成任务
        "story-serial-tick": {
            "task": "serial_tick",
            "schedule": 60.0,
            "options": {"ignore_result": True},
        },
        # 队列排空兜底：send_task 在 uvicorn 环境可能静默丢消息，
        # 每 15 秒从 DB 扫 queued 任务执行（pull 模式，保证任务不卡死）
        "drain-queued-tasks": {
            "task": "drain_queued_tasks",
            "schedule": 15.0,
            "options": {"ignore_result": True},
        },
        # 每日巡检：每天 06:00 收集系统健康快照
        "daily-inspection": {
            "task": "daily_inspection",
            "schedule": crontab(minute=0, hour=6),
        },
        # 每日备份：每天 02:00 逻辑 SQL + storage（保留 14 天）
        "daily-backup": {
            "task": "daily_backup",
            "schedule": crontab(minute=0, hour=2),
        },
    },
)
