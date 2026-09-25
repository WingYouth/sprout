"""Skill sources (design §7.3)."""

from Sprout.skills.sources.base import SkillBundle, SkillSource, SkillStub
from Sprout.skills.sources.catalog import CatalogSource
from Sprout.skills.sources.cli import (
    CliResult,
    CliRunner,
    ProcessBrokerRunner,
    SubprocessRunner,
)
from Sprout.skills.sources.crawl import CrawlSource, build_crawl_source
from Sprout.skills.sources.github import GitHubSource
from Sprout.skills.sources.local import LocalDirSource
from Sprout.skills.sources.url import UrlSource
from Sprout.skills.sources.wellknown import WellKnownSource

__all__ = [
    "CatalogSource",
    "CliResult",
    "CliRunner",
    "CrawlSource",
    "GitHubSource",
    "LocalDirSource",
    "ProcessBrokerRunner",
    "SkillBundle",
    "SkillSource",
    "SkillStub",
    "SubprocessRunner",
    "UrlSource",
    "WellKnownSource",
    "build_crawl_source",
]
