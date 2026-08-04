"""
FastAPI web server entry point.

Routes:
  GET  /              Control console (static)
  GET  /api/robot/status      Robot state
  POST /api/robot/jog         Manual jog
  GET  /api/camera/stream     MJPEG video stream
  GET  /api/camera/snapshot   Single frame capture
  POST /api/task/start        Start a task
  POST /api/task/stop         Stop current task
  GET  /api/task/status       Current task state
  WS   /ws                    Real-time status + frames
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def create_app(config=None) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="UIEA ThirdHand VLA", version="2.0.0")

    # Static files (frontend)
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app


app = create_app()
