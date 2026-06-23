"""FastAPI web dashboard server for Second Innings."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

import yaml

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

HERE = Path(__file__).parent
TEMPLATES_DIR = HERE / "templates"
STATIC_DIR = HERE / "static"

app = FastAPI(title="Second Innings", version="2.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Global state — populated when server starts
_config: dict[str, Any] = {}
_base_dir: Path = Path(".")
_db = None  # JobRepository instance


def init_server(config: dict[str, Any], base_dir: Path) -> None:
    global _config, _base_dir, _db
    _config = config
    _base_dir = base_dir
    from ..config import resolve_db_path
    from ..db import get_repo
    _db = get_repo(resolve_db_path(config, base_dir))


# ---------------------------------------------------------------------------
# HTML page
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    html = (TEMPLATES_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# API — Stats
# ---------------------------------------------------------------------------

@app.get("/api/stats")
async def get_stats():
    if _db is None:
        raise HTTPException(503, "Server not initialised")
    stats = _db.get_pipeline_stats()
    breakdown = _db.get_source_breakdown()
    return {"pipeline": stats, "sources": breakdown}


# ---------------------------------------------------------------------------
# API — Jobs
# ---------------------------------------------------------------------------

class JobStatusUpdate(BaseModel):
    status: str
    note: Optional[str] = ""
    applied_date: Optional[str] = ""
    next_action: Optional[str] = ""


@app.get("/api/jobs")
async def get_jobs(
    status: Optional[str] = None,
    apply_type: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    if _db is None:
        raise HTTPException(503, "Server not initialised")
    jobs = _db.get_jobs(
        status=status,
        apply_type=apply_type,
        source=source,
        limit=limit,
        offset=offset,
    )
    return [j.to_row() for j in jobs]


@app.post("/api/jobs/{job_id}/status")
async def update_job_status(job_id: str, body: JobStatusUpdate):
    if _db is None:
        raise HTTPException(503, "Server not initialised")
    _db.update_job_status(
        job_id,  # source_url used as ID
        body.status,
        applied_date=body.applied_date or "",
        note=body.note or "",
        next_action=body.next_action or "",
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# API — Pending answers (notification bell)
# ---------------------------------------------------------------------------

@app.get("/api/pending-answers")
async def get_pending_answers():
    if _db is None:
        raise HTTPException(503, "Server not initialised")
    pending = _db.get_pending_inputs()
    count = _db.count_pending_inputs()
    return {"count": count, "items": pending}


class AnswerSubmit(BaseModel):
    pending_id: int
    answer: str


@app.post("/api/pending-answers/answer")
async def submit_answer(body: AnswerSubmit):
    if _db is None:
        raise HTTPException(503, "Server not initialised")
    question = _db.answer_pending_input(body.pending_id, body.answer)
    if not question:
        raise HTTPException(404, "Pending question not found")
    return {"ok": True, "question": question}


# ---------------------------------------------------------------------------
# API — Scrape runs history
# ---------------------------------------------------------------------------

@app.get("/api/scrape-history")
async def scrape_history(limit: int = 30):
    if _db is None:
        raise HTTPException(503, "Server not initialised")
    return _db.get_scrape_history(limit=limit)


# ---------------------------------------------------------------------------
# API — Trigger scrape / apply (background)
# ---------------------------------------------------------------------------

_running_task: dict[str, bool] = {"scrape": False, "apply": False}


@app.post("/api/scrape")
async def trigger_scrape(background_tasks: BackgroundTasks, sources: Optional[str] = None):
    if _running_task.get("scrape"):
        return {"ok": False, "message": "Scrape already running"}
    src_list = [s.strip() for s in sources.split(",")] if sources else None
    background_tasks.add_task(_run_scrape_bg, src_list)
    return {"ok": True, "message": "Scrape started"}


@app.post("/api/apply")
async def trigger_apply(background_tasks: BackgroundTasks):
    if _running_task.get("apply"):
        return {"ok": False, "message": "Apply already running"}
    background_tasks.add_task(_run_apply_bg)
    return {"ok": True, "message": "Apply started"}


@app.get("/api/task-status")
async def task_status():
    return _running_task


async def _run_scrape_bg(sources):
    from ..scraper.orchestrator import run_scraper
    _running_task["scrape"] = True
    try:
        await run_scraper(_config, _base_dir, sources)
    finally:
        _running_task["scrape"] = False


async def _run_apply_bg():
    from ..applier.orchestrator import run_applier
    _running_task["apply"] = True
    try:
        await run_applier(_config, _base_dir)
    finally:
        _running_task["apply"] = False


# ---------------------------------------------------------------------------
# API — Content generation
# ---------------------------------------------------------------------------

class ContentRequest(BaseModel):
    company: str
    role: str
    jd_text: Optional[str] = ""
    hiring_manager: Optional[str] = ""
    target_name: Optional[str] = ""
    profile_url: Optional[str] = ""
    job_url: Optional[str] = ""


@app.post("/api/content/cover-letter")
async def gen_cover_letter(body: ContentRequest):
    from ..content.ai_client import AIClient
    from ..content.cover_letter import generate_cover_letter
    from ..models import Job
    ai = AIClient(_config)
    job = Job(source="", company=body.company, role=body.role, source_url="",
               jd_text=body.jd_text or "")
    profile = _config.get("profile", {})
    text = await generate_cover_letter(job, profile, ai)
    if body.job_url:
        _db.save_content_draft(body.job_url, "cover_letter", text)
    return {"content": text}


@app.post("/api/content/cold-email")
async def gen_cold_email(body: ContentRequest):
    from ..content.ai_client import AIClient
    from ..content.cold_email import generate_cold_email
    ai = AIClient(_config)
    profile = _config.get("profile", {})
    result = await generate_cold_email(
        body.company, body.role, profile, ai,
        hiring_manager=body.hiring_manager or "",
        jd_text=body.jd_text or "",
    )
    if body.job_url:
        _db.save_content_draft(body.job_url, "cold_email",
                               f"Subject: {result['subject']}\n\n{result['body']}")
    return result


@app.post("/api/content/linkedin-dm")
async def gen_linkedin_dm(body: ContentRequest):
    from ..content.ai_client import AIClient
    from ..content.linkedin_dm import generate_linkedin_dm
    ai = AIClient(_config)
    profile = _config.get("profile", {})
    text = await generate_linkedin_dm(
        body.company, body.role, profile, ai,
        target_name=body.target_name or "",
        profile_url=body.profile_url or "",
    )
    if body.job_url:
        _db.save_content_draft(body.job_url, "linkedin_dm", text)
    return {"content": text}


# ---------------------------------------------------------------------------
# API — Settings (live config read/write)
# ---------------------------------------------------------------------------

_config_path: Optional[Path] = None


def _get_config_path() -> Path:
    if _config_path:
        return _config_path
    # Walk up from base_dir to find config.yaml
    for candidate in [_base_dir / "config.yaml", Path("config.yaml")]:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("config.yaml not found")


ALL_SCRAPER_SITES = ["linkedin", "naukri", "indeed", "hirist", "wellfound", "cutshort"]
ALL_APPLIER_SITES = ["LinkedIn", "Naukri", "Indeed", "Hirist", "Wellfound", "Cutshort"]


@app.get("/api/settings")
async def get_settings():
    try:
        cfg_path = _get_config_path()
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        scraper_cfg = raw.get("scraper", {})
        searches = scraper_cfg.get("searches", {})
        scraper_sources = scraper_cfg.get("sources", list(searches.keys()))
        return {
            "profile": raw.get("profile", {}),
            "ai": raw.get("ai", {}),
            "scraper": {
                "max_jobs_per_search": scraper_cfg.get("max_jobs_per_search", 15),
                "fresh_only_days": scraper_cfg.get("fresh_only_days", 7),
                "enrich_details": scraper_cfg.get("enrich_details", True),
                "enrich_limit_per_search": scraper_cfg.get("enrich_limit_per_search", 8),
                "sources": scraper_sources,
            },
            "scoring": raw.get("scoring", {}),
            "applier": raw.get("applier", {}),
            "all_scraper_sites": ALL_SCRAPER_SITES,
            "all_applier_sites": ALL_APPLIER_SITES,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


class SettingsSave(BaseModel):
    section: str  # "profile", "ai", "scraper", "scoring", "applier"
    data: dict[str, Any]


@app.post("/api/settings")
async def save_settings(body: SettingsSave):
    try:
        cfg_path = _get_config_path()
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

        allowed = {"profile", "ai", "scraper", "scoring", "applier"}
        if body.section not in allowed:
            raise HTTPException(400, f"Section '{body.section}' is not editable via UI")

        # Deep-merge the submitted data into the section
        section = raw.get(body.section, {})
        if isinstance(section, dict):
            section.update(body.data)
        else:
            section = body.data
        raw[body.section] = section

        # Write back
        cfg_path.write_text(yaml.dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")

        # Hot-reload into in-memory _config so changes take effect without restart
        global _config
        _config = raw

        return {"ok": True, "message": "Settings saved and applied live."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ---------------------------------------------------------------------------
# Launcher
# ---------------------------------------------------------------------------

def run_ui_server(config: dict[str, Any], base_dir: Path, port: int = 8080) -> None:
    """Start the uvicorn server and open browser."""
    import uvicorn

    init_server(config, base_dir)

    url = f"http://localhost:{port}"
    print(f"\n[ui] Second Innings dashboard → {url}")
    print("[ui] Press Ctrl+C to stop\n")

    # Open browser
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
