# Present so pytest treats the repo root as rootdir. Add the backend source root
# so tests can keep importing packages such as analytics, toqan, and home_news.
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parent / "backend"
if str(BACKEND_ROOT) not in sys.path:
	sys.path.insert(0, str(BACKEND_ROOT))
