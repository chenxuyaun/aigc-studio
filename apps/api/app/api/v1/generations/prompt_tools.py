from fastapi import APIRouter, Depends

from app.models.user import User
from app.schemas.prompt_tools import (
    OptimizeResult,
    PromptGenerateRequest,
    PromptOptimizeRequest,
    StructuredPrompt,
)
from app.security.auth import get_current_user
from app.services import prompt_tools

router = APIRouter()


@router.post("/generate", response_model=StructuredPrompt)
async def generate_prompt(
    req: PromptGenerateRequest, _: User = Depends(get_current_user)
) -> StructuredPrompt:
    return prompt_tools.generate_structured_prompt(req)


@router.post("/optimize", response_model=OptimizeResult)
async def optimize_prompt(
    req: PromptOptimizeRequest, _: User = Depends(get_current_user)
) -> OptimizeResult:
    return prompt_tools.optimize_prompt(req)
