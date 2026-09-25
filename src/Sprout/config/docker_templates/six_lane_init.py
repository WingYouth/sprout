"""Compatibility shim: the six-lane initialisation now lives in the package.

The implementation moved to :func:`Sprout.storage.lanediag.init_lanes`, reached
through the CLI as ``sprout storage init`` (``python -m Sprout storage init``
inside the runner image, which does not install the console script). This file
stays so the documented ``docker compose run --rm -T sprout-app python
/app/docker/six_lane_init.py`` recipe keeps working.

Exit codes come from the report: 0 everything configured was created, 1 a lane
failed.
"""

from __future__ import annotations

import asyncio
import sys

from Sprout.config.loader import load_settings
from Sprout.storage.lanediag import init_lanes


def main() -> int:
    report = asyncio.run(init_lanes(load_settings()))
    print(report.plain())
    return report.status


if __name__ == "__main__":
    sys.exit(main())
