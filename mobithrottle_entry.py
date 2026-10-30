"""PyInstaller entry point (a script, so the package's relative imports work).
Equivalent to `python -m mobithrottle`."""
import sys

from mobithrottle.app import main

if __name__ == "__main__":
    sys.exit(main())
