"""Compatibility shim: the six-lane check now lives in the package.

The implementation moved to :func:`Sprout.storage.lanediag.check_lanes`, reached
through the CLI as ``sprout storage check`` (``python -m Sprout storage check``
inside the runner image, which does not install the console script). This file
stays so the documented ``docker compose run --rm -T sprout-app python
/app/docker/six_lane_probe.py`` recipe and ``sprout-app``'s default command keep
working.

Exit codes come from the report: 0 all six lanes hold the data, 1 a lane failed,
2 no six-lane fan-out is configured, 3 a stale Milvus embedding width.
"""

from __future__ import annotations

import asyncio
import sys

from Sprout.config.loader import load_settings
from Sprout.storage.lanediag import check_lanes


def main() -> int:
    report = asyncio.run(check_lanes(load_settings()))
    print(report.plain())
    return report.status


if __name__ == "__main__":
    sys.exit(main())
