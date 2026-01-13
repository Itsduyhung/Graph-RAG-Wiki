# llm.py
# Backward compatibility wrapper - redirects to new llm module
from llm.llm_client import call_llm

__all__ = ["call_llm"]
