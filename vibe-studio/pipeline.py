import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict

from replicate_client import generate as replicate_generate, model_ref_for_key

RUNS = Path(os.getenv("RUNS_DIR", Path(__file__).parent / "runs")).resolve()
RUNS_OUTPUTS = RUNS / "outputs"
RUNS_LOGS = RUNS / "logs"
RUNS_OUTPUTS.mkdir(parents=True, exist_ok=True)
RUNS_LOGS.mkdir(parents=True, exist_ok=True)

JOBS: Dict[str, Dict[str, Any]] = {}


def create_job(payload: Dict[str, Any]) -> str:
    job_id = str(uuid.uuid4())[:8]
    JOBS[job_id] = {
        "id": job_id,
        "status": "queued",
        "payload": payload,
        "output_path": None,
        "error": None,
        "created_at": time.time(),
    }
    return job_id


def run_job(job_id: str):
    job = JOBS[job_id]
    job["status"] = "running"
    pl: dict = job["payload"]

    # Compose prompt on the server to be robust to FE drift
    final_prompt = " ".join(
        [str(pl.get("tile_prompt") or "").strip(), str(pl.get("tuner_text") or "").strip()]
    ).strip()
    model_key = pl["model"]
    model_ref = model_ref_for_key(model_key)

    # Map to model-specific inputs
    ref_path = pl.get("reference_path")
    inputs: Dict[str, Any] = {"prompt": final_prompt}
    if model_key == "prunaai-kontext-dev":
        inputs["img_cond_path"] = Path(ref_path).open("rb")
        if pl.get("guidance") is not None:
            inputs["guidance"] = float(pl["guidance"])
    else:
        inputs["input_image"] = Path(ref_path).open("rb")
        if pl.get("guidance") is not None:
            inputs["guidance"] = float(pl["guidance"])
        if pl.get("go_fast") is not None:
            inputs["go_fast"] = bool(pl["go_fast"])
        if pl.get("safety_tolerance") is not None:
            inputs["safety_tolerance"] = int(pl["safety_tolerance"])
        inputs["disable_safety_checker"] = True
        inputs["num_inference_steps"] = 50

    if pl.get("aspect_ratio"):
        inputs["aspect_ratio"] = pl["aspect_ratio"]
    if pl.get("seed") is not None:
        inputs["seed"] = int(pl["seed"])

    try:
        img_bytes = replicate_generate(model_ref, inputs)
        out_dir = RUNS_OUTPUTS / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "gen.png"
        out_path.write_bytes(img_bytes)

        job["output_path"] = str(out_path)
        job["status"] = "succeeded"

        log = {
            "job_id": job_id,
            "model": model_ref,
            "inputs": {k: v for k, v in inputs.items() if k != "input_image" and k != "img_cond_path"},
            "reference_path": ref_path,
            "output_path": str(out_path),
            "prompt": final_prompt,
            "ts": time.time(),
        }
        (RUNS_LOGS / "runs.jsonl").open("a", encoding="utf-8").write(json.dumps(log) + "\n")
    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)
        print(e)
