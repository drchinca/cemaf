"""Run the CEMAF web UI."""

import uvicorn

from cemaf.web.app import app

if __name__ == "__main__":
    uvicorn.run(app=app, host="0.0.0.0", port=8420)
