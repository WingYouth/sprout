"""Command-line interface for SEAM Sprout.

The public objects are loaded lazily so ``python -m Sprout.cli.app`` does not
import the module once through the package and then execute it a second time.
That duplicate import also initialized gRPC/Temporal state too early.
"""

__all__ = ["app", "main"]


def __getattr__(name: str):
    if name in __all__:
        from Sprout.cli.app import app, main

        return app if name == "app" else main
    raise AttributeError(name)
