"""
Robot REST API  /api/robot/*
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/robot", tags=["robot"])

@router.get("/status")
async def get_status():
    return {"connected": False, "joints": [], "pose": [], "state": "unknown"}

@router.post("/jog")
async def jog(dx: float = 0, dy: float = 0, dz: float = 0):
    return {"status": "ok", "command": f"jog dx={dx} dy={dy} dz={dz}"}

@router.post("/home")
async def go_home():
    return {"status": "ok", "command": "home"}

@router.post("/estop")
async def emergency_stop():
    return {"status": "ok", "command": "estop"}
