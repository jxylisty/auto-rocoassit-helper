from __future__ import annotations

import threading
import time
import traceback
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .solver import build_request_from_web, solve_exact


class InventoryPayload(BaseModel):
    shinyMaleStocks: list[int] = Field(..., min_length=16, max_length=16)
    shinyFemaleStocks: list[int] = Field(..., min_length=16, max_length=16)
    statuses: list[str] = Field(..., min_length=16, max_length=16)


class SolvePayload(BaseModel):
    maleCount: int = Field(..., ge=0, le=20)
    femaleCount: int = Field(..., ge=0, le=20)
    nestCount: int = Field(..., ge=1, le=20)
    mode: str = Field(default="collection")
    inventory: InventoryPayload


app = FastAPI(title="Roco Nest Optimizer", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()


def _set_job(job_id: str, **fields: Any) -> None:
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(fields)


def _run_job(job_id: str, payload: dict) -> None:
    started = time.time()

    def progress(stage: str, current: int, total: int) -> None:
        _set_job(
            job_id,
            status="running",
            stage=stage,
            progress_current=current,
            progress_total=total,
            elapsed_seconds=round(time.time() - started, 1),
        )

    try:
        request = build_request_from_web(payload)
        result = solve_exact(request, progress_callback=progress)
        _set_job(
            job_id,
            status="done",
            stage="求解完成",
            progress_current=4,
            progress_total=4,
            elapsed_seconds=round(time.time() - started, 1),
            result=result,
        )
    except ValueError as exc:
        print("[nest-optimizer] 400 ValueError:", str(exc))
        _set_job(
            job_id,
            status="error",
            stage="输入校验失败",
            error=str(exc),
            elapsed_seconds=round(time.time() - started, 1),
        )
    except Exception as exc:
        print("[nest-optimizer] 500 UnexpectedError:", repr(exc))
        traceback.print_exc()
        _set_job(
            job_id,
            status="error",
            stage="求解异常",
            error=str(exc),
            elapsed_seconds=round(time.time() - started, 1),
        )


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/solve")
def solve(payload: SolvePayload) -> dict:
    if payload.maleCount + payload.femaleCount != payload.nestCount:
        raise HTTPException(status_code=400, detail="雄性数量 + 雌性数量 必须等于小窝总数。")
    try:
        request = build_request_from_web(payload.model_dump())
        return solve_exact(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="本地求解服务出现未预期错误。") from exc


@app.post("/solve_async")
def solve_async(payload: SolvePayload) -> dict:
    if payload.maleCount + payload.femaleCount != payload.nestCount:
        raise HTTPException(status_code=400, detail="雄性数量 + 雌性数量 必须等于小窝总数。")
    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "stage": "等待开始",
            "progress_current": 0,
            "progress_total": 4,
            "elapsed_seconds": 0.0,
            "result": None,
            "error": None,
        }
    thread = threading.Thread(target=_run_job, args=(job_id, payload.model_dump()), daemon=True)
    thread.start()
    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在。")
        return job.copy()
