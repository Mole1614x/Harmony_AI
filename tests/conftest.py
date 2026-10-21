import os
import sys
from pathlib import Path

# Run Qt without a display and keep QtWebEngine happy in containers/CI.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu"
)

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
