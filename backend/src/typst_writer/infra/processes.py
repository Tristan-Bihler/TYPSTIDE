"""Settings shared by every child process (LTeX+, Tinymist, claude)."""

import subprocess
import sys

# The Windows app has no console; without this flag every console program it starts
# (java.exe for LTeX+, tinymist.exe, claude.exe) would open its own console window.
if sys.platform == "win32":
    NO_WINDOW: int = subprocess.CREATE_NO_WINDOW
else:
    NO_WINDOW: int = 0
