# llm/llm_client.py
"""LLM client cho Ollama - đơn giản và tập trung."""
import os
import requests
from typing import Optional, Dict, Any
from dotenv import load_dotenv

load_dotenv()

# Ollama configuration
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")


def call_llm(
    prompt: str, 
    model: Optional[str] = None, 
    stream: bool = False,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None
) -> str:
    """
    Gọi Ollama LLM API - đơn giản và trực tiếp.
    
    Args:
        prompt: Câu hỏi hoặc prompt
        model: Tên model (mặc định từ env OLLAMA_MODEL)
        stream: Có stream response không (chưa support streaming output)
        temperature: Temperature cho generation
        max_tokens: Số tokens tối đa
    
    Returns:
        Response text từ LLM
    
    Examples:
        >>> response = call_llm("Ai là người sáng lập của Fintech X?")
        >>> response = call_llm("Hello", model="llama2", temperature=0.7)
    """
    payload = {
        "model": model or OLLAMA_MODEL,
        "prompt": prompt,
        "stream": stream
    }
    
    # Thêm optional parameters nếu có
    if temperature is not None:
        payload["options"] = payload.get("options", {})
        payload["options"]["temperature"] = temperature
    
    if max_tokens is not None:
        payload["options"] = payload.get("options", {})
        payload["options"]["num_predict"] = max_tokens
    
    try:
        response = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=120  # Timeout 120s cho các prompt dài
        )
        response.raise_for_status()
        
        result = response.json()
        return result.get("response", "")
    
    except requests.exceptions.RequestException as e:
        raise ConnectionError(f"Không thể kết nối đến Ollama tại {OLLAMA_URL}. "
                            f"Đảm bảo Ollama đang chạy: ollama serve. Error: {e}")


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
