from __future__ import annotations

from pydantic import BaseModel


class PromptGenerateRequest(BaseModel):
    idea: str = ""
    scene: str = ""
    target_model: str = "llm"  # llm | image | video | speech | code
    goal: str = ""
    audience: str = ""
    style: str = ""
    tone: str = ""
    length: str = ""
    output_format: str = ""
    constraints: str = ""
    output_language: str = "中文"


class StructuredPrompt(BaseModel):
    role: str
    background: str
    goal: str
    input: str
    steps: list[str]
    output_format: str
    constraints: str
    quality_check: str
    full_prompt: str


class PromptOptimizeRequest(BaseModel):
    prompt: str
    target_model: str = "llm"


class DiagnosisItem(BaseModel):
    dimension: str
    score: int
    level: str
    note: str


class OptimizeResult(BaseModel):
    score_before: int
    score_after: int
    diagnosis: list[DiagnosisItem]
    suggestions: list[str]
    concise: str
    standard: str
    professional: str
