"""
KG2M - core/utils.py
Utilities and helpers for the KG2M project.
"""

import time
import re
import requests

_MIN_INTERVAL = 7.0
_last_call_time = 0.0

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

def generate_with_retry(prompt, model_name="gemma4:26b", max_retries=5, initial_delay=10.0) -> DummyResponse:
    """
    Helper function to call Ollama generate API with exponential backoff.
    """
    url = "https://research.neu.edu.vn/ollama/api/generate"
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
                    chunk_data = response.json() if not line.strip().startswith(b"{") else __import__('json').loads(line)
                    full_content += chunk_data.get("response", "")
            return DummyResponse(full_content)
        except Exception as e:
            print(f"[KG2M] API Request failed (Attempt {attempt + 1}/{max_retries}): {e}. Waiting {delay:.1f}s...")
            time.sleep(delay)
            delay *= 2
    
    raise Exception(f"Failed to generate content after {max_retries} retries.")