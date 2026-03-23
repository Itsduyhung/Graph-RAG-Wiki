# graph.py
# Backward compatibility wrapper - redirects to new graph module
from graph.storage import GraphDB

__all__ = ["GraphDB"]
