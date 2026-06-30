import os
import tempfile

# Point the SQLite history DB at a throwaway file for the whole test session,
# before any test module imports app.storage (which reads DB_PATH at import
# time). This keeps tests from writing into the repo's real data/ directory.
# Force the override (not setdefault) — if DB_PATH is already set in the
# environment (e.g. a developer's shell, or a future CI config), tests must
# still never touch that path.
os.environ["DB_PATH"] = os.path.join(
    tempfile.mkdtemp(prefix="pulseframe-tests-"), "metrics.db"
)
