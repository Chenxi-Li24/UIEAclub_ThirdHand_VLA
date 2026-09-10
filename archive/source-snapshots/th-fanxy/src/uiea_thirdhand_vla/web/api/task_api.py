"""
Task REST API  /api/task/*
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/task", tags=["task"])

@router.get("/list")
async def list_tasks():
    return {"tasks": ["pick_place", "ar_tag_sort"]}

@router.post("/start")
async def start_task(task_name: str = "pick_place"):
    return {"status": "ok", "task": task_name, "state": "running"}

@router.post("/stop")
async def stop_task():
    return {"status": "ok", "state": "idle"}

@router.post("/pause")
async def pause_task():
    return {"status": "ok", "state": "paused"}

@router.post("/resume")
async def resume_task():
    return {"status": "ok", "state": "running"}

@router.get("/status")
async def task_status():
    return {"task": None, "state": "idle", "elapsed": 0}
