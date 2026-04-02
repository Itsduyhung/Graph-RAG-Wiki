# llm/llm_client.py
"""LLM client dùng YEScale (Gemini 2.0 Flash) thay cho Ollama."""

import os
import time
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

# YEScale / Gemini configuration
YESCALE_BASE_URL = os.getenv(
    "YESCALE_BASE_URL",
    "https://api.yescale.io/v1/chat/completions",
)
YESCALE_MODEL = os.getenv("YESCALE_MODEL", "gemini-2.0-flash")
YESCALE_API_KEY = os.getenv("YESCALE_API_KEY")
YESCALE_TIMEOUT = int(os.getenv("YESCALE_TIMEOUT", "300" if "2.5-pro" in os.getenv("YESCALE_MODEL", "") else "120"))
YESCALE_MAX_RETRIES = int(os.getenv("YESCALE_MAX_RETRIES", "3"))


def call_llm(
    prompt: str,
    model: Optional[str] = None,
    stream: bool = False,  # chưa hỗ trợ stream trong client này
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> str:
    """
    Gọi LLM qua YEScale (Gemini 2.0 Flash) với API kiểu OpenAI chat/completions.
    Có retry logic với exponential backoff.
    """
    if not YESCALE_API_KEY:
        raise RuntimeError(
            "YESCALE_API_KEY chưa được cấu hình trong environment (.env)."
        )

    # Auto-detect timeout based on model (slow models need longer timeout)
    effective_model = model or YESCALE_MODEL
    if "2.5" in effective_model:
        timeout = 300
    else:
        timeout = 120
    print(f"[DEBUG] call_llm: model={effective_model}, timeout={timeout}")

    payload = {
        "model": model or YESCALE_MODEL,
        "messages": [
            {"role": "user", "content": prompt},
        ],
    }

    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    headers = {
        "Authorization": f"Bearer {YESCALE_API_KEY}",
        "Content-Type": "application/json",
    }

    # Retry logic with exponential backoff
    last_error = None
    for attempt in range(YESCALE_MAX_RETRIES):
        try:
            response = requests.post(
                YESCALE_BASE_URL,
                json=payload,
                headers=headers,
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
            # OpenAI‑style response
            return data["choices"][0]["message"]["content"]
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else None
            # 524 = Gateway Timeout - retry
            if status_code == 524:
                wait_time = (attempt + 1) * 10  # 10, 20, 30 seconds
                print(f"[RETRY] YEScale timeout (524), attempt {attempt + 1}/{YESCALE_MAX_RETRIES}, waiting {wait_time}s...")
                time.sleep(wait_time)
                last_error = e
                continue
            # Other HTTP errors - don't retry
            raise ConnectionError(
                f"Không thể kết nối đến YEScale. HTTP Error: {e}"
            )
        except requests.exceptions.RequestException as e:
            # Connection errors - retry with backoff
            wait_time = (attempt + 1) * 5
            print(f"[RETRY] YEScale connection error, attempt {attempt + 1}/{YESCALE_MAX_RETRIES}, waiting {wait_time}s...")
            time.sleep(wait_time)
            last_error = e
            continue

    # All retries exhausted
    raise ConnectionError(
        f"Không thể kết nối đến YEScale sau {YESCALE_MAX_RETRIES} lần thử. Error: {last_error}"
    )


def call_llm_with_context(
    prompt: str,
    context: str,
    model: Optional[str] = None,
    **kwargs
) -> str:
    """
    Gọi LLM với context được thêm vào prompt.
    
    Args:
        prompt: Câu hỏi chính
        context: Context được thêm vào
        model: Tên model
        **kwargs: Các tham số khác cho call_llm
    
    Returns:
        Response text từ LLM
    """
    full_prompt = f"{context}\n\nQuestion: {prompt}"
    return call_llm(full_prompt, model=model, **kwargs)


# Backward compatibility - alias cho các tên cũ nếu cần
call_ollama = call_llm
