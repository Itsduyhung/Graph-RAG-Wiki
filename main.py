# main.py
# Backward compatibility wrapper - redirects to new pipeline module
from pipeline.query_pipeline import ask_agent

__all__ = ["ask_agent"]
