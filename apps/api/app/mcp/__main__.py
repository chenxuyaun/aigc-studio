"""python -m app.mcp → stdio 模式（本地 AI 客户端）。"""

from app.mcp.server import mcp

if __name__ == "__main__":
    mcp.run()
