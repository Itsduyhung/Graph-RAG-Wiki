# llm/llm_client.py
"""LLM client dùng YEScale (Gemini 2.0 Flash) thay cho Ollama."""

import json
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
YESCALE_MODEL = os.getenv("YESCALE_MODEL", "gemini-2.5-flash")
YESCALE_API_KEY = os.getenv("YESCALE_API_KEY")
YESCALE_TIMEOUT = int(os.getenv("YESCALE_TIMEOUT", "300" if "2.5-pro" in os.getenv("YESCALE_MODEL", "") else "120"))
YESCALE_MAX_RETRIES = int(os.getenv("YESCALE_MAX_RETRIES", "5"))  # Increased from 3 to 5 for 524 timeouts


def call_llm(
    prompt: str,
    model: Optional[str] = None,
    stream: bool = False,  # chưa hỗ trợ stream trong client này
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout: Optional[int] = None,  # Custom timeout in seconds
) -> str:
    """
    Gọi LLM qua YEScale (Gemini 2.0 Flash) với API kiểu OpenAI chat/completions.
    Có retry logic với exponential backoff.
    """
    if not YESCALE_API_KEY:
        raise RuntimeError(
            "YESCALE_API_KEY chưa được cấu hình trong environment (.env)."
        )

    # Use custom timeout if provided, otherwise auto-detect based on model
    if timeout is None:
        effective_model = model or YESCALE_MODEL
        if "2.5" in effective_model:
            timeout = 300
        else:
            timeout = 120
    
    effective_model = model or YESCALE_MODEL
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
            
            # If status_code not extracted, try to extract from error message
            if status_code is None:
                error_str = str(e)
                if "524" in error_str:
                    status_code = 524
                elif "503" in error_str:
                    status_code = 503
            
            # 503 (Service Unavailable) and 524 (Gateway Timeout) - retry with exponential backoff
            if status_code in [503, 524]:
                wait_time = (2 ** attempt) * 15  # 15s, 30s, 60s, 120s (exponential)
                error_name = "Service Unavailable (503)" if status_code == 503 else "Gateway Timeout (524)"
                print(f"[RETRY] YEScale {error_name}, attempt {attempt + 1}/{YESCALE_MAX_RETRIES}, waiting {wait_time}s...")
                time.sleep(wait_time)
                last_error = e
                continue
            # Other HTTP errors - don't retry
            print(f"[ERROR] HTTP Error {status_code}: {e}")
            raise ConnectionError(
                f"Không thể kết nối đến YEScale. HTTP Error: {e}"
            )
        except requests.exceptions.Timeout as e:
            # Timeout - retry with exponential backoff
            wait_time = (2 ** attempt) * 20
            print(f"[RETRY] Request timeout, attempt {attempt + 1}/{YESCALE_MAX_RETRIES}, waiting {wait_time}s...")
            time.sleep(wait_time)
            last_error = e
            continue
        except requests.exceptions.RequestException as e:
            # Connection errors - retry with backoff
            wait_time = (attempt + 1) * 5
            print(f"[RETRY] YEScale connection error, attempt {attempt + 1}/{YESCALE_MAX_RETRIES}, waiting {wait_time}s...")
            time.sleep(wait_time)
            last_error = e
            continue

    # All retries exhausted
    print(f"[ERROR] All {YESCALE_MAX_RETRIES} retries exhausted. Last error: {last_error}")
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


def call_llm_stream(
    prompt: str,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
):
    """
    Gọi LLM với streaming - trả về text chunks từng chút một (real-time).
    Generator yields text chunks as they arrive.
    
    Args:
        prompt: The prompt to send
        model: Model name
        temperature: Temperature for generation
        max_tokens: Max tokens to generate
        
    Yields:
        Text chunks as they arrive from the API
    """
    if not YESCALE_API_KEY:
        raise RuntimeError("YESCALE_API_KEY chưa được cấu hình trong environment (.env).")

    effective_model = model or YESCALE_MODEL
    if "2.5" in effective_model:
        timeout = 300
    else:
        timeout = 120
    
    print(f"[DEBUG] call_llm_stream: model={effective_model}, timeout={timeout}")

    payload = {
        "model": model or YESCALE_MODEL,
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "stream": True,  # Enable streaming
    }

    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    headers = {
        "Authorization": f"Bearer {YESCALE_API_KEY}",
        "Content-Type": "application/json",
    }

    last_error = None
    for attempt in range(YESCALE_MAX_RETRIES):
        try:
            response = requests.post(
                YESCALE_BASE_URL,
                json=payload,
                headers=headers,
                timeout=timeout,
                stream=True,
            )
            response.raise_for_status()
            
            # Stream the response line by line
            for line in response.iter_lines():
                if not line:
                    continue
                
                # Parse SSE format (data: {...})
                line_str = line.decode('utf-8') if isinstance(line, bytes) else line
                if line_str.startswith("data: "):
                    try:
                        data = json.loads(line_str[6:])  # Skip "data: " prefix
                        if "choices" in data and len(data["choices"]) > 0:
                            delta = data["choices"][0].get("delta", {})
                            if "content" in delta:
                                yield delta["content"]
                    except json.JSONDecodeError:
                        continue
            return
            
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else None
            
            # If status_code not extracted, try to extract from error message
            if status_code is None:
                error_str = str(e)
                if "524" in error_str:
                    status_code = 524
                elif "503" in error_str:
                    status_code = 503
            
            if status_code in [503, 524]:
                wait_time = (2 ** attempt) * 15  # 15s, 30s, 60s, 120s (exponential)
                error_name = "Service Unavailable (503)" if status_code == 503 else "Gateway Timeout (524)"
                print(f"[RETRY] YEScale {error_name}, attempt {attempt + 1}/{YESCALE_MAX_RETRIES}, waiting {wait_time}s...")
                time.sleep(wait_time)
                last_error = e
                continue
            print(f"[ERROR] HTTP Error {status_code}: {e}")
            raise ConnectionError(f"HTTP Error {status_code}: {e}")
        except requests.exceptions.Timeout as e:
            wait_time = (2 ** attempt) * 20
            print(f"[RETRY] Request timeout, attempt {attempt + 1}/{YESCALE_MAX_RETRIES}, waiting {wait_time}s...")
            time.sleep(wait_time)
            last_error = e
            continue
        except requests.exceptions.RequestException as e:
            wait_time = (attempt + 1) * 5
            print(f"[RETRY] Connection error, attempt {attempt + 1}/{YESCALE_MAX_RETRIES}, waiting {wait_time}s...")
            time.sleep(wait_time)
            last_error = e
            continue

    print(f"[ERROR] All {YESCALE_MAX_RETRIES} retries exhausted. Last error: {last_error}")
    raise ConnectionError(
        f"Không thể kết nối đến YEScale sau {YESCALE_MAX_RETRIES} lần thử. Error: {last_error}"
    )


# Backward compatibility - alias cho các tên cũ nếu cần
call_ollama = call_llm
