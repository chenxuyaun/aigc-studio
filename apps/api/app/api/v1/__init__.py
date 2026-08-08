from fastapi import APIRouter

from app.api.v1 import (
    agentlist,
    agents,
    asmr,
    assets,
    auth,
    character_cards,
    dashboard,
    health,
    knowledge,
    logs,
    memory,
    photography,
    projects,
    prompts,
    providers,
    roleplay,
    search,
    skills,
    story,
    tasks,
    upstream,
    users,
    workflows,
)
from app.api.v1.generations import audio as gen_audio
from app.api.v1.generations import music as gen_music
from app.api.v1.generations import comic as gen_comic
from app.api.v1.generations import image as gen_image
from app.api.v1.generations import prompt_tools as gen_prompt
from app.api.v1.generations import text as gen_text
from app.api.v1.generations import video as gen_video

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(users.router, prefix="/users", tags=["users"])
router.include_router(prompts.router, prefix="/prompts", tags=["prompts"])
router.include_router(projects.router, prefix="/projects", tags=["projects"])
router.include_router(providers.router, prefix="/providers", tags=["providers"])
router.include_router(agents.router, prefix="/agents", tags=["agents"])
router.include_router(skills.router, prefix="/skills", tags=["skills"])
router.include_router(workflows.router, prefix="/workflows", tags=["workflows"])
router.include_router(gen_text.router, prefix="/generations/text", tags=["generations"])
router.include_router(gen_image.router, prefix="/generations/image", tags=["generations"])
router.include_router(gen_video.router, prefix="/generations/video", tags=["generations"])
router.include_router(gen_audio.router, prefix="/generations/audio", tags=["generations"])
router.include_router(gen_music.router, prefix="/generations/music", tags=["generations"])
router.include_router(gen_comic.router, prefix="/generations/comic", tags=["generations"])
router.include_router(gen_prompt.router, prefix="/generations/prompt", tags=["generations"])
router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
router.include_router(assets.router, prefix="/assets", tags=["assets"])
router.include_router(photography.router, prefix="/photography", tags=["photography"])
router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
router.include_router(upstream.router, prefix="/upstream", tags=["upstream"])
router.include_router(character_cards.router, prefix="/character-cards", tags=["character-cards"])
router.include_router(roleplay.router, prefix="/roleplay", tags=["roleplay"])
router.include_router(search.router, prefix="/search", tags=["search"])
router.include_router(story.router, prefix="/story", tags=["story"])
router.include_router(agentlist.router, prefix="", tags=["agentlist"])
router.include_router(asmr.router, prefix="/asmr", tags=["asmr"])
router.include_router(health.router, prefix="/health", tags=["health"])
router.include_router(logs.router, prefix="/logs", tags=["logs"])
router.include_router(memory.router, prefix="", tags=["memory"])
