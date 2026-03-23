# prompts.py
# Backward compatibility wrapper - redirects to new llm module
from llm.prompt_templates import INTENT_PROMPT, ANSWER_PROMPT

__all__ = ["INTENT_PROMPT", "ANSWER_PROMPT"]
