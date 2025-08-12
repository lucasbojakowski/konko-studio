from typing import Optional, Literal
from pydantic import BaseModel


class GenerateRequest(BaseModel):
    # What the UI sends
    reference_path: str
    model: Literal["kontext-dev", "kontext-pro", "prunaai-kontext-dev"]
    aspect_ratio: str = "match_input"
    guidance: Optional[float] = None
    go_fast: Optional[bool] = False
    seed: Optional[int] = None
    safety_tolerance: Optional[int] = None
    tile_prompt: Optional[str] = ""
    tuner_text: Optional[str] = ""
    # Optional/unused by the current UI, kept for forward compat
    identity: Optional[dict] = None


class JobInfo(BaseModel):
    id: str
    status: str
    model: str
    prompt_text: str
    input_path: str
    output_path: Optional[str] = None
    error: Optional[str] = None


class PostProcessRequest(BaseModel):
    image_path: str
    grain: float = 0.015
    usm_amount: float = 0.6
    usm_radius: float = 1.0
    highlight_rolloff: float = 0.12
