import uuid

from app.providers.base import SpeechProvider


class MockSpeechProvider(SpeechProvider):
    async def submit(self, text: str, model: str = "mock", **kwargs: object) -> dict[str, object]:
        return {"task_id": str(uuid.uuid4()), "status": "processing"}

    async def poll(self, task_id: str) -> dict[str, object]:
        return {"status": "succeeded", "progress": 100}
