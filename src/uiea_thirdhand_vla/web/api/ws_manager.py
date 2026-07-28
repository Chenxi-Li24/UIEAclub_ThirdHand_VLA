"""
WebSocket manager  real-time status push to browser clients.

Channels:
  robot_state   Joint angles, EE pose, connection status
  camera_frame  Encoded JPEG frames (when video.method=websocket-frames)
  task_events   State transitions, detection results, errors
  log_stream    Structured log entries
"""
from fastapi import WebSocket


class WebSocketManager:
    """Manage connected WebSocket clients and broadcast channels."""

    def __init__(self):
        self._clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._clients.append(ws)

    def disconnect(self, ws: WebSocket):
        self._clients.remove(ws)

    async def broadcast(self, data: dict):
        for ws in self._clients:
            try:
                await ws.send_json(data)
            except Exception:
                self._clients.remove(ws)


ws_manager = WebSocketManager()
