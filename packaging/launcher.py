"""PyInstaller entry point (absolute import, unlike package __main__)."""

from plotdeck.app import main

if __name__ == "__main__":
    raise SystemExit(main())
