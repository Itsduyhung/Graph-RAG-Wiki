# tests/test_env.py
"""Test environment configuration."""
from dotenv import load_dotenv
import os

load_dotenv()

def test_env_variables():
    """Test that environment variables are loaded."""
    print("NEO4J_URI =", os.getenv("NEO4J_URI"))
    print("NEO4J_USER =", os.getenv("NEO4J_USER"))
    print("NEO4J_PASSWORD =", os.getenv("NEO4J_PASSWORD"))
    print("NEO4J_DB =", os.getenv("NEO4J_DB"))

if __name__ == "__main__":
    test_env_variables()


