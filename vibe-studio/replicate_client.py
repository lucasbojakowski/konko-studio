import os
from typing import Any, Dict, List, Union

import replicate
import requests
from dotenv import load_dotenv

load_dotenv()

def _client():
    token = os.getenv("REPLICATE_API_TOKEN")
    if not token:
        raise RuntimeError("Missing REPLICATE_API_TOKEN")
    return replicate.Client(api_token=token)


def model_ref_for_key(model_key: str) -> str:
    mapping = {
        "kontext-dev": os.getenv("KONTEXT_DEV_MODEL", "black-forest-labs/flux-kontext-dev"),
        "kontext-pro": os.getenv("KONTEXT_PRO_MODEL", "black-forest-labs/flux-kontext-pro"),
        "prunaai-kontext-dev": os.getenv("PRUNAAI_DEV_MODEL", "prunaai/flux-kontext-dev"),
    }
    if model_key not in mapping:
        raise ValueError(f"Unknown model key: {model_key}")
    return mapping[model_key]


def generate(model_ref: str, inputs: Dict[str, Any]) -> bytes:
    c = _client()
    print(model_ref, inputs)
    result: Union[str, List[str]] = c.run(ref=model_ref, input=inputs)
    url: str
    if isinstance(result, list):
        if not result:
            raise RuntimeError("Model returned an empty list")
        url = result[0]
    else:
        url = result
    resp = requests.get(url, timeout=300)
    resp.raise_for_status()
    return resp.content
