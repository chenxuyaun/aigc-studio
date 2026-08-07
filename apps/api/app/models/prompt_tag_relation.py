from sqlalchemy import Column, ForeignKey, String

from app.models.base import Base


class PromptTagRelation(Base):
    __tablename__ = "prompt_tag_relations"
    prompt_id = Column(String(36), ForeignKey("prompts.id", ondelete="CASCADE"), primary_key=True)
    tag_id = Column(String(36), ForeignKey("prompt_tags.id", ondelete="CASCADE"), primary_key=True)
