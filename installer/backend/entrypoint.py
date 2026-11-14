"""PyInstaller script entrypoint; keep application imports in their package."""
from multiprocessing import freeze_support

from platon.backend.desktop_runtime import main

if __name__ == "__main__":
    freeze_support()
    main()
