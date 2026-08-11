import uuid

from app.providers.base import ImageProvider

_MOCK_SVG = (
    "data:image/svg+xml,"
    "<svg xmlns='http://www.w3.org/2000/svg' width='512' height='512'>"
    "<rect fill='%236366f1' width='512' height='512'/>"
    "<text fill='white' x='50%25' y='50%25' text-anchor='middle' dy='.3em' "
    "font-size='20'>Mock Image</text></svg>"
)


class MockImageProvider(ImageProvider):
    async def submit(self, prompt: str, model: str = "mock", **kwargs: object) -> dict[str, object]:
        return {"task_id": str(uuid.uuid4()), "status": "processing"}

    async def poll(self, task_id: str) -> dict[str, object]:
        return {"status": "succeeded", "progress": 100, "image_url": _MOCK_SVG}
