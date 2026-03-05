import asyncio
import sys
from pathlib import Path

import uvicorn


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Ensure local project code is imported first (not stale site-packages build).
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=18010)
