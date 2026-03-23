# test_env.py
# Backward compatibility - redirects to new test module
from tests.test_env import test_env_variables

if __name__ == "__main__":
    test_env_variables()
