import os
import sys

# Ensure the repo root is importable as `app.*` regardless of where pytest
# is invoked from (app/ has no __init__.py, so it relies on the root being
# on sys.path as a namespace package).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
