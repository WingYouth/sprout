"""``python -m Sprout`` — the same entry point as the ``sprout`` console script.

Matters for the Docker runner image: it does not install the package (the source
arrives as a read-only bind mount and ``PYTHONPATH`` points at ``/app/src``), so
there is no ``sprout`` executable on ``PATH`` inside the container.
"""

from __future__ import annotations

from Sprout.cli.app import main

if __name__ == "__main__":
    main()
