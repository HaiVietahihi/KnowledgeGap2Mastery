"""
KG2M - core/utils.py
Utilities and helpers for the KG2M project.
"""

import os
import time
import json as _json
import requests
from dotenv import load_dotenv

load_dotenv()

_MIN_INTERVAL = 7.0
_last_call_time = 0.0

# Đọc cấu hình Ollama từ biến môi trường
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "https://research.neu.edu.vn/ollama")
OLLAMA_MODEL    = os.environ.get("OLLAMA_MODEL", "gemma4:26b")

def _throttle():
    global _last_call_time
    elapsed = time.time() - _last_call_time
    wait = _MIN_INTERVAL - elapsed
    if wait > 0:
        time.sleep(wait)
    _last_call_time = time.time()

# ─────────────────────────────────────────────────────────────────────────────

class DummyResponse:
    def __init__(self, text):
        self.text = text

def generate_with_retry(prompt, model_name=None, max_retries=5, initial_delay=10.0) -> DummyResponse:
    """
    Helper function to call Ollama generate API with exponential backoff.
    URL và model được đọc từ biến môi trường OLLAMA_BASE_URL và OLLAMA_MODEL.
    """
    if model_name is None:
        model_name = OLLAMA_MODEL

    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": True
    }

    delay = initial_delay
    for attempt in range(max_retries):
        try:
            _throttle()  # Đợi đủ khoảng cách trước mỗi request
            response = requests.post(url, json=payload, timeout=300, stream=True)
            response.raise_for_status()
            full_content = ""
            for line in response.iter_lines():
                if line:
                    chunk_data = _json.loads(line)
                    full_content += chunk_data.get("response", "")
            return DummyResponse(full_content)
        except Exception as e:
            print(f"[KG2M] API Request failed (Attempt {attempt + 1}/{max_retries}): {e}. Waiting {delay:.1f}s...")
            time.sleep(delay)
            delay *= 2

    raise Exception(f"Failed to generate content after {max_retries} retries.")