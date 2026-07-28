"""
Camera REST API  /api/camera/*
"""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/camera", tags=["camera"])

@router.get("/stream")
async def video_stream():
    return {"status": "stream not available"}  # TODO: implement MJPEG

@router.get("/snapshot")
async def snapshot():
    return {"status": "snapshot not available"}  # TODO: implement

@router.get("/info")
async def camera_info():
    return {"model": "unknown", "resolution": "1280x720", "fps": 30}
