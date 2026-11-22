"""Allow ``python -m dictionary_agent`` as an alternative entry point."""

from .cli import main

raise SystemExit(main())
