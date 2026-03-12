# llm/llm_client.py
"""LLM client dùng YEScale (Gemini 2.0 Flash) thay cho Ollama."""

import os
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


def call_llm(
    prompt: str,
    model: Optional[str] = None,
    stream: bool = False,  # chưa hỗ trợ stream trong client này
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> str:
    """
    Gọi LLM qua YEScale (Gemini 2.0 Flash) với API kiểu OpenAI chat/completions.
    """
    if not YESCALE_API_KEY:
        raise RuntimeError(
            "YESCALE_API_KEY chưa được cấu hình trong environment (.env)."
        )

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

    try:
        response = requests.post(
            YESCALE_BASE_URL,
            json=payload,
            headers=headers,
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        # OpenAI‑style response
        return data["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException as e:
        raise ConnectionError(
            f"Không thể kết nối đến YEScale tại {YESCALE_BASE_URL}. Error: {e}"
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
