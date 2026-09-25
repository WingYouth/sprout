"""Basic project knowledge models and builder."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from Sprout.workspace.models import Workspace, WorkspaceManifest


@dataclass(frozen=True, slots=True)
class ProjectKnowledgeItem:
    id: str = field(default_factory=lambda: str(uuid4()))
    statement: str = ""
    kind: str = "fact"
    scope: str = "workspace"
    evidence_ids: tuple[str, ...] = ()
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class ProjectKnowledge:
    workspace_id: str
    items: tuple[ProjectKnowledgeItem, ...] = ()


class ProjectKnowledgeBuilder:
    def build(self, workspace: Workspace, manifest: WorkspaceManifest) -> ProjectKnowledge:
        items: list[ProjectKnowledgeItem] = []
        evidence: list[str] = []
        root = Path(workspace.root)

        pyproject = root / "pyproject.toml"
        if pyproject.is_file():
            evidence.append(pyproject.resolve().as_posix())
            project = self._read_pyproject(pyproject)
            if project.get("name"):
                items.append(
                    self._item(
                        workspace,
                        len(items),
                        f"Project name: {project['name']}",
                        evidence,
                    )
                )
            if project.get("description"):
                items.append(
                    self._item(
                        workspace,
                        len(items),
                        f"Project description: {project['description']}",
                        evidence,
                    )
                )

        package_json = root / "package.json"
        if package_json.is_file():
            evidence.append(package_json.resolve().as_posix())
            package = self._read_json(package_json)
            if package.get("name"):
                items.append(
                    self._item(
                        workspace,
                        len(items),
                        f"Node package: {package['name']}",
                        evidence,
                    )
                )
            scripts = package.get("scripts")
            if isinstance(scripts, dict) and scripts:
                items.append(
                    self._item(
                        workspace,
                        len(items),
                        "Node scripts: " + ", ".join(scripts),
                        evidence,
                    )
                )
            dependencies = package.get("dependencies")
            if isinstance(dependencies, dict) and dependencies:
                items.append(
                    self._item(
                        workspace,
                        len(items),
                        "Node dependencies: " + ", ".join(dependencies),
                        evidence,
                    )
                )

        go_mod = root / "go.mod"
        if go_mod.is_file():
            evidence.append(go_mod.resolve().as_posix())
            module = self._go_module(go_mod)
            if module:
                items.append(
                    self._item(
                        workspace,
                        len(items),
                        f"Go module: {module}",
                        evidence,
                    )
                )

        cargo = root / "Cargo.toml"
        if cargo.is_file():
            evidence.append(cargo.resolve().as_posix())
            package = self._read_toml(cargo).get("package", {})
            if isinstance(package, dict) and package.get("name"):
                items.append(
                    self._item(
                        workspace,
                        len(items),
                        f"Rust crate: {package['name']}",
                        evidence,
                    )
                )

        items.extend(
            self._project_surface_items(
                workspace,
                root,
                start_index=len(items),
            )
        )
        if manifest.detected_languages:
            items.append(
                self._item(
                    workspace,
                    len(items),
                    f"Detected languages: {', '.join(manifest.detected_languages)}",
                    evidence,
                )
            )
        if manifest.test_commands:
            items.append(
                self._item(
                    workspace,
                    len(items),
                    f"Test commands: {', '.join(manifest.test_commands)}",
                    evidence,
                )
            )
        if manifest.entry_points:
            items.append(
                self._item(
                    workspace,
                    len(items),
                    f"Entry points: {', '.join(manifest.entry_points)}",
                    evidence,
                )
            )
        if manifest.framework_hints:
            items.append(
                self._item(
                    workspace,
                    len(items),
                    f"Framework hints: {', '.join(manifest.framework_hints)}",
                    evidence,
                )
            )
        items.extend(
            self._inferences(
                workspace,
                manifest,
                evidence,
                start_index=len(items),
            )
        )
        return ProjectKnowledge(workspace_id=workspace.id, items=tuple(items))

    def _project_surface_items(
        self,
        workspace: Workspace,
        root: Path,
        *,
        start_index: int,
    ) -> list[ProjectKnowledgeItem]:
        items: list[ProjectKnowledgeItem] = []

        categories = (
            (
                "Documentation files",
                self._find_by_names(root, _DOCUMENTATION_NAMES),
                "documentation",
            ),
            (
                "Docker assets",
                self._find_by_predicate(root, _is_docker_asset),
                "runtime",
            ),
            (
                "Compose assets",
                self._find_by_names(root, _COMPOSE_NAMES),
                "runtime",
            ),
            (
                "Package manifests",
                self._find_by_predicate(root, _is_package_manifest),
                "dependency",
            ),
            (
                "Interface contracts",
                self._find_by_predicate(root, _is_interface_asset),
                "interface",
            ),
            (
                "Project database assets",
                self._find_by_predicate(root, _is_project_database_asset),
                "project_database",
            ),
            (
                "Infrastructure assets",
                self._find_by_predicate(root, _is_infrastructure_asset),
                "infrastructure",
            ),
        )

        for label, paths, kind in categories:
            if not paths:
                continue
            statement = f"{label}: " + ", ".join(self._relative_paths(root, paths))
            items.append(
                self._item(
                    workspace,
                    start_index + len(items),
                    statement,
                    self._evidence(paths),
                    kind=kind,
                    confidence=0.95,
                )
            )

        env_files = self._find_by_predicate(root, _is_env_file)
        if env_files:
            names = ", ".join(self._relative_paths(root, env_files))
            env_keys = self._env_keys(env_files)
            suffix = f" keys: {', '.join(env_keys)}" if env_keys else ""
            items.append(
                self._item(
                    workspace,
                    start_index + len(items),
                    f"Environment files: {names}{suffix}",
                    self._evidence(env_files),
                    kind="environment",
                    confidence=0.9,
                )
            )

        sprout_db = self._sprout_database_statement(root)
        if sprout_db is not None:
            statement, evidence_ids = sprout_db
            items.append(
                self._item(
                    workspace,
                    start_index + len(items),
                    statement,
                    evidence_ids,
                    kind="sprout_database",
                    confidence=1.0,
                )
            )

        return items

    @staticmethod
    def _item(
        workspace: Workspace,
        index: int,
        statement: str,
        evidence_ids: list[str],
        *,
        kind: str = "fact",
        confidence: float = 1.0,
    ) -> ProjectKnowledgeItem:
        return ProjectKnowledgeItem(
            id=f"{workspace.id}:knowledge:{index}",
            statement=statement,
            kind=kind,
            scope="workspace",
            evidence_ids=tuple(evidence_ids),
            confidence=confidence,
        )

    def _inferences(
        self,
        workspace: Workspace,
        manifest: WorkspaceManifest,
        evidence: list[str],
        *,
        start_index: int,
    ) -> list[ProjectKnowledgeItem]:
        items: list[ProjectKnowledgeItem] = []
        languages = set(manifest.detected_languages)
        root = Path(workspace.root)

        if "python" in languages and (root / "src").is_dir():
            evidence_ids = [*evidence, (root / "src").resolve().as_posix()]
            items.append(
                self._item(
                    workspace,
                    start_index + len(items),
                    "Likely uses a src-layout Python package",
                    evidence_ids,
                    kind="inference",
                    confidence=0.8,
                )
            )

        has_tests = (root / "tests").is_dir() or any(
            root.rglob("test_*.py")
        )
        if "python" in languages and has_tests:
            evidence_ids = [*evidence, (root / "tests").resolve().as_posix()]
            items.append(
                self._item(
                    workspace,
                    start_index + len(items),
                    "Project follows a pytest-style testing convention",
                    evidence_ids,
                    kind="inference",
                    confidence=0.75,
                )
            )

        if len(languages) > 1:
            items.append(
                self._item(
                    workspace,
                    start_index + len(items),
                    f"Polyglot repository: {', '.join(sorted(languages))}",
                    evidence,
                    kind="inference",
                    confidence=0.7,
                )
            )

        return items

    @staticmethod
    def _read_pyproject(path: Path) -> dict:
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return {}
        project = data.get("project", {})
        return project if isinstance(project, dict) else {}

    @staticmethod
    def _read_json(path: Path) -> dict:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _read_toml(path: Path) -> dict:
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _go_module(path: Path) -> str:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return ""
        match = re.search(r"(?m)^module\s+(.+)$", text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _find_by_names(root: Path, names: set[str]) -> list[Path]:
        matches: list[Path] = []
        for path in root.rglob("*"):
            if _skip_path(root, path) or not path.is_file():
                continue
            if path.name.casefold() in names:
                matches.append(path)
        return sorted(matches)[:20]

    @staticmethod
    def _find_by_predicate(root: Path, predicate) -> list[Path]:
        matches: list[Path] = []
        for path in root.rglob("*"):
            if _skip_path(root, path) or not path.is_file():
                continue
            if predicate(root, path):
                matches.append(path)
        return sorted(matches)[:30]

    @staticmethod
    def _relative_paths(root: Path, paths: list[Path]) -> list[str]:
        output: list[str] = []
        for path in paths:
            try:
                output.append(path.relative_to(root).as_posix())
            except ValueError:
                output.append(path.name)
        return output

    @staticmethod
    def _evidence(paths: list[Path]) -> list[str]:
        return [path.resolve().as_posix() for path in paths]

    @staticmethod
    def _env_keys(paths: list[Path]) -> list[str]:
        keys: set[str] = set()
        for path in paths:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key = stripped.split("=", 1)[0].strip()
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                    keys.add(key)
        return sorted(keys)[:30]

    @staticmethod
    def _sprout_database_statement(root: Path) -> tuple[str, list[str]] | None:
        topology = root / "src" / "Sprout" / "storage" / "topology.py"
        if not topology.is_file():
            return None
        statement = (
            "Sprout database topology: runtime storage ownership is declared in "
            "src/Sprout/storage/topology.py; this is Sprout's own database layer, "
            "separate from project database assets."
        )
        return statement, [topology.resolve().as_posix()]


_SKIP_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".uv-cache",
    "dist",
    "build",
    ".idea",
}

_DOCUMENTATION_NAMES = {
    "readme",
    "readme.md",
    "readme.rst",
    "readme.txt",
    "contributing.md",
    "changelog.md",
    "license",
    "license.md",
}

_COMPOSE_NAMES = {
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
}

_PACKAGE_MANIFEST_NAMES = {
    "pyproject.toml",
    "requirements.txt",
    "pipfile",
    "poetry.lock",
    "uv.lock",
    "setup.py",
    "setup.cfg",
    "package.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "package-lock.json",
    "go.mod",
    "go.sum",
    "cargo.toml",
    "cargo.lock",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "gemfile",
    "composer.json",
    "package.swift",
    "pubspec.yaml",
    "mix.exs",
    "cmakelists.txt",
    "makefile",
    "meson.build",
}

_INTERFACE_NAMES = {
    "openapi.yaml",
    "openapi.yml",
    "openapi.json",
    "swagger.yaml",
    "swagger.yml",
    "swagger.json",
    "schema.graphql",
    "schema.gql",
}

_DATABASE_NAMES = {
    "schema.prisma",
    "schema.sql",
    "structure.sql",
    "database.sql",
    "alembic.ini",
    "knexfile.js",
    "knexfile.ts",
    "ormconfig.json",
    "ormconfig.js",
    "ormconfig.ts",
}


def _skip_path(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    return any(part in _SKIP_PARTS for part in relative.parts)


def _is_docker_asset(root: Path, path: Path) -> bool:
    del root
    name = path.name.casefold()
    return name == "dockerfile" or name.startswith("dockerfile.")


def _is_package_manifest(root: Path, path: Path) -> bool:
    del root
    name = path.name.casefold()
    return name in _PACKAGE_MANIFEST_NAMES or name.endswith((".csproj", ".fsproj", ".sln"))


def _is_interface_asset(root: Path, path: Path) -> bool:
    del root
    name = path.name.casefold()
    parts = {part.casefold() for part in path.parts}
    return (
        name in _INTERFACE_NAMES
        or path.suffix.casefold() == ".proto"
        or "routes" in parts
        or "controllers" in parts
        or "endpoints" in parts
        or "api" in parts
    )


def _is_project_database_asset(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    parts = {part.casefold() for part in relative.parts}
    name = path.name.casefold()
    suffix = path.suffix.casefold()
    return (
        name in _DATABASE_NAMES
        or suffix == ".sql"
        or "migrations" in parts
        or "migration" in parts
        or "schema" in parts
        or "prisma" in parts
        or "alembic" in parts
        or "typeorm" in parts
        or "sequelize" in parts
        or "knex" in parts
    )


def _is_infrastructure_asset(root: Path, path: Path) -> bool:
    del root
    return path.suffix.casefold() in {".tf", ".tfvars"} or path.name.casefold() in {
        "helmfile.yaml",
        "kustomization.yaml",
    }


def _is_env_file(root: Path, path: Path) -> bool:
    del root
    name = path.name.casefold()
    return name == ".env" or name.startswith(".env.") or name.endswith(".env")
