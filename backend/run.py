import os
import sys

# Ensure backend directory is in Python path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import uvicorn
from app.core import config

if __name__ == "__main__":
    print(f"Starting FindIT backend server on http://{config.HOST}:{config.PORT} ...")
    reload_enabled = os.getenv("FINDIT_RELOAD", "0").lower() in {"1", "true", "yes"}
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, reload=reload_enabled)
