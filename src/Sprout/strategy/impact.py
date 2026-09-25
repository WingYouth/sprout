"""Read-only project impact discovery for a requirement."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from Sprout.strategy.models import ImpactItem, ImpactReport, ImpactSource, Requirement

#: Cache Directory Tagging standard marker (bford.info/cachedir). Any directory
#: holding this file is a cache by declaration, whatever it is called.
CACHEDIR_TAG = "CACHEDIR.TAG"


class ImpactAnalyzer:
    """Locate likely interface, database, source, and test touch points.

    This is intentionally conservative: a match is evidence for planning, not
    permission to edit. A later workspace graph query can enrich the report.
    """

    #: Directory names never worth scanning. Mostly a backstop for trees that
    #: carry no CACHEDIR.TAG; kept in step with the repository's .gitignore.
    _ignored = {
        ".git",
        ".venv",
        ".uv-cache",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".idea",
        ".vscode",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        ".tox",
        "site-packages",
    }
    _test_pattern = re.compile(r"(^tests?/|^test_|_test\.|/tests?/|\\tests?\\)", re.I)
    _api_pattern = re.compile(r"(api|route|endpoint|gateway|server|controller|tool)", re.I)
    _db_pattern = re.compile(r"(database|storage|sqlite|migration|schema|model)", re.I)

    def analyze(self, root: str | Path, requirement: Requirement) -> ImpactReport:
        """Backward-compatible alias for the explicit project scan path."""
        return self.analyze_from_scan(root, requirement)

    def analyze_from_scan(self, root: str | Path, requirement: Requirement) -> ImpactReport:
        """Score every candidate file, highest confidence first.

        Note the shape of the result: on a real project almost everything lands
        on the same baseline score, because ``_terms`` only extracts English
        tokens — a Chinese requirement over an English codebase contributes one
        or two keywords, and the rest is "this is source code". Consumers must
        therefore bound their input by *ranking* (``ImpactReport.top_items``),
        not by thresholding on confidence: a threshold cannot separate the
        relevant files from the rest, so it drops both.
        """
        project_root = Path(root).resolve()
        terms = self._terms(requirement.text)
        items: list[ImpactItem] = []
        for path in self._files(project_root):
            relative = path.relative_to(project_root).as_posix()
            haystack = f"{relative} {path.stem}".casefold()
            score = sum(1 for term in terms if term in haystack)
            category = self._category(relative)
            baseline = self._is_project_source(relative)
            if score or category in {"interface", "database"} or baseline:
                reason = (
                    "requirement keyword match"
                    if score
                    else "project scan architecture evidence"
                )
                items.append(
                    ImpactItem(
                        path=relative,
                        category=category,
                        reason=reason,
                        confidence=min(1.0, 0.2 + score * 0.2 + (0.15 if baseline else 0)),
                        matched=bool(score),
                    )
                )

        items.sort(key=lambda item: (-item.confidence, item.path))
        return ImpactReport(
            items=tuple(items),
            interfaces=tuple(item.path for item in items if item.category == "interface"),
            databases=tuple(item.path for item in items if item.category == "database"),
            # Tests are the exception to the architecture-inclusion rule below:
            # a repository has hundreds, and "every test file" is not evidence
            # about a requirement. On this repo it turned into 73 "test files
            # to update" in the coding prompt, none of them keyword-matched.
            # Only requirement-matched tests are evidence; an empty answer lets
            # the caller propose a new test instead of touching all of them.
            tests=tuple(
                item.path
                for item in items
                if item.category == "test" and item.matched
            ),
            related_code=tuple(item.path for item in items if item.category == "code"),
            source=ImpactSource.PROJECT_SCAN,
        )

    async def analyze_from_project_database(
        self,
        requirement: Requirement,
        search: Callable[[str, int], Awaitable[Sequence[Any]]],
    ) -> ImpactReport:
        """Read persisted project knowledge without walking the filesystem.

        ``search`` is normally ``KnowledgeStore.search``. Keeping it injected
        lets the strategy layer use SQLite, a vector store, or a test double
        without coupling it to a particular storage implementation.
        """
        records = await search(requirement.text, 50)
        items = [self._database_item(record) for record in records]
        items = [item for item in items if item is not None]
        return self._report(tuple(items), ImpactSource.PROJECT_DATABASE)

    async def analyze_cross_validated(
        self,
        root: str | Path,
        requirement: Requirement,
        search: Callable[[str, int], Awaitable[Sequence[Any]]],
    ) -> ImpactReport:
        """Compare project-database evidence with a fresh full project scan."""
        scan = self.analyze_from_scan(root, requirement)
        database = await self.analyze_from_project_database(requirement, search)
        scan_paths = {item.path for item in scan.items}
        database_paths = {item.path for item in database.items}
        conflicts = tuple(sorted(database_paths ^ scan_paths))
        merged: dict[str, ImpactItem] = {item.path: item for item in scan.items}
        for item in database.items:
            if item.path in merged:
                existing = merged[item.path]
                merged[item.path] = ImpactItem(
                    path=item.path,
                    category=existing.category,
                    reason="database and scan evidence agree",
                    confidence=min(1.0, max(existing.confidence, item.confidence) + 0.2),
                    symbols=existing.symbols + item.symbols,
                )
            else:
                merged[item.path] = item
        return self._report(tuple(merged.values()), ImpactSource.CROSS_VALIDATED, conflicts)

    @staticmethod
    def _database_item(record: Any) -> ImpactItem | None:
        content = str(getattr(record, "content", getattr(record, "statement", record)))
        path_match = re.search(r"(?:^|\s)([\w./-]+\.(?:py|js|jsx|ts|tsx|sql|db))(?:$|\s)", content)
        if path_match is None:
            return None
        path = path_match.group(1)
        category = "test" if "test" in path.casefold() else "database" if any(
            token in path.casefold() for token in ("db", "database", "schema", "sql", "storage")
        ) else "interface" if any(
            token in path.casefold() for token in ("api", "route", "gateway", "tool", "server")
        ) else "code"
        return ImpactItem(path, category, "project database evidence", 0.7)

    @staticmethod
    def _report(
        items: tuple[ImpactItem, ...],
        source: ImpactSource,
        conflicts: tuple[str, ...] = (),
    ) -> ImpactReport:
        ordered = tuple(sorted(items, key=lambda item: (-item.confidence, item.path)))
        return ImpactReport(
            items=ordered,
            interfaces=tuple(item.path for item in ordered if item.category == "interface"),
            databases=tuple(item.path for item in ordered if item.category == "database"),
            # Matched-only, for the same reason as in ``analyze_from_scan``.
            tests=tuple(
                item.path
                for item in ordered
                if item.category == "test" and item.matched
            ),
            related_code=tuple(item.path for item in ordered if item.category == "code"),
            source=source,
            conflicts=conflicts,
        )

    def _files(self, root: Path):
        """Yield candidate source files, skipping caches and vendored trees.

        Two filters, because one is not enough. The name list covers the usual
        suspects that carry no marker (``.pytest_cache``, ``.idea``); the
        ``CACHEDIR.TAG`` check covers everything that follows the cache-dir
        convention, including directories nobody thought to add here. On this
        repository the marker alone removes 664 files — ``.uv-cache`` alone
        was 61% of every "impact" the planner reported.
        """
        if not root.exists():
            raise FileNotFoundError(root)
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if self._ignored.intersection(path.parts):
                continue
            if self._in_cache_dir(path, root):
                continue
            yield path

    def _in_cache_dir(self, path: Path, root: Path) -> bool:
        """True when any directory between ``root`` and ``path`` is a cache.

        Non-recursive on purpose: ``rglob`` already walks the tree, and this
        only inspects the components of one path.
        """
        relative = path.relative_to(root)
        for parent in relative.parents:
            if parent == Path("."):
                break
            if (root / parent / CACHEDIR_TAG).is_file():
                return True
        return False

    def _category(self, relative: str) -> str:
        if self._test_pattern.search(relative):
            return "test"
        if self._db_pattern.search(relative):
            return "database"
        if self._api_pattern.search(relative):
            return "interface"
        return "code"

    @staticmethod
    def _is_project_source(relative: str) -> bool:
        path = Path(relative)
        return (
            path.suffix.casefold() in {".py", ".js", ".jsx", ".ts", ".tsx", ".sql"}
            and path.parts
            and path.parts[0] in {"src", "web", "app", "lib", "tests"}
        )

    @staticmethod
    def _terms(text: str) -> tuple[str, ...]:
        normalized = text.casefold()
        english = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", normalized)
        return tuple(dict.fromkeys(english))
