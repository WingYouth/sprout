"""SEAM_Sprout web application package (frontend-adjacent backend under web/)."""

from .app import create_app
from .database import WebDatabase

__all__ = ["WebDatabase", "create_app"]
