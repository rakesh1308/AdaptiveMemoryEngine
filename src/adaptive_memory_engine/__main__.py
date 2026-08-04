"""Allow `python -m adaptive_memory_engine` to dispatch to the CLI."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())