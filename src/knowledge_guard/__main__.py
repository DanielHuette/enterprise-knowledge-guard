"""Run the API with uvicorn: `python -m knowledge_guard`.

Context: Local start without Docker. | Input: HOST and PORT environment variables.
| Output: running HTTP server.
"""

import os

import uvicorn

uvicorn.run(
    "knowledge_guard.api:app",
    host=os.getenv("HOST", "127.0.0.1"),
    port=int(os.getenv("PORT", "8000")),
)
