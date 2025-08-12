import mimetypes
import secrets
from pathlib import Path
from typing import Any, Dict

import requests
from fastapi import BackgroundTasks, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI

from models import GenerateRequest, PostProcessRequest  # noqa: F401  (kept for future)
from prompts import PromptBuilder
from pipeline import create_job, run_job, JOBS, RUNS

APP_DIR = Path(__file__).parent.resolve()

# Load all *.yaml found in ./prompts (if exists) or project root
prompt_dirs = [APP_DIR / "prompts", APP_DIR]
yaml_files = []
for d in prompt_dirs:
    if d.exists():
        yaml_files += list(d.glob("*.yaml"))
pbs = [PromptBuilder(f) for f in yaml_files]
if not pbs:
    # If no yaml found, raise a clear error to avoid confusing 500s later
    raise RuntimeError("No prompt YAML found. Add one (e.g., example.yaml) to the project root or ./prompts/.")

app = FastAPI(title="Vibe Studio — Kontext")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static mounts
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
app.mount("/runs", StaticFiles(directory=str(RUNS)), name="runs")


@app.get("/", response_class=HTMLResponse)
def index():
    """Serve the SPA index (expects index.html at project root)."""
    return (APP_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/prompts")
def api_prompts():
    """Expose tiles built from YAML so the UI can render 'vibes'."""
    vibes = []
    for pb in pbs:
        for c in pb.config.categories:
            for t in c.tiles:
                vibes.append(
                    {
                        "category": c.id,
                        "tile": t.id,
                        "title": t.title,
                        "prompt": pb.build(f"{c.id}.{t.id}", overrides={}),
                        "template": t.defaults,
                    }
                )
    print(vibes)
    return {"vibes": vibes}


@app.get("/api/models")
def api_models():
    """Minimal list for the dropdown expected by the frontend."""
    return {
        "models": [
            {"key": "kontext-dev", "title": "Kontext Dev — BFL"},
            {"key": "kontext-pro", "title": "Kontext Pro — BFL"},
            {"key": "prunaai-kontext-dev", "title": "Kontext Dev — PrunaAI"},
        ]
    }


@app.post("/api/references")
async def upload_reference(file: UploadFile = File(None), url: str = Form(None)):
    """Accept an uploaded file or fetch from a URL; return a public path under /runs/refs/.."""
    dest_dir = RUNS / "refs"
    dest_dir.mkdir(parents=True, exist_ok=True)

    if file is not None:
        ext = Path(file.filename).suffix.lower() or ".png"
        if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
            return JSONResponse({"error": "Unsupported file type"}, status_code=400)
        out = dest_dir / f"ref_{secrets.token_hex(3)}{ext}"
        out.write_bytes(await file.read())
        # return a path that the frontend can GET directly
        return {"path": f"runs/refs/{out.name}"}

    if url:
        try:
            resp = requests.get(url, timeout=30)
        except Exception as e:
            return JSONResponse({"error": f"Failed to fetch url: {e}"}, status_code=400)
        if resp.status_code >= 400:
            return JSONResponse({"error": f"Failed to fetch url: {url}"}, status_code=400)
        out = dest_dir / f"ref_{secrets.token_hex(3)}.png"
        out.write_bytes(resp.content)
        return {"path": f"runs/refs/{out.name}"}

    return JSONResponse({"error": "Provide file or url"}, status_code=400)


@app.post("/api/generate")
async def api_generate(req: GenerateRequest, bg: BackgroundTasks):
    # Enqueue the job; the worker will run in a FastAPI background task
    print(req)
    job_id = create_job(req.model_dump())
    bg.add_task(run_job, job_id)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return JSONResponse({"error": "not found"}, status_code=404)
    return job


@app.get("/api/jobs/{job_id}/download")
def api_download(job_id: str):
    job = JOBS.get(job_id)
    if not job or not job.get("output_path"):
        return JSONResponse({"error": "not found"}, status_code=404)
    path = Path(job["output_path"])
    filename = f"{job_id}_{path.name}"
    return FileResponse(
        str(path),
        filename=filename,
        media_type=mimetypes.guess_type(str(path))[0] or "image/png",
    )
