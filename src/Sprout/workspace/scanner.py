"""Progressive workspace scanning and ReadPlan construction."""

from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from Sprout.task.models import Task
from Sprout.workspace.classification import ResourceClassifier
from Sprout.workspace.models import (
    ReadPlan,
    ReadStage,
    ResourceKind,
    ResourceRef,
    Workspace,
    WorkspaceKind,
    WorkspaceManifest,
)

_MANIFEST_FILES = (
    "pyproject.toml",
    "requirements.txt",
    "Pipfile",
    "setup.py",
    "package.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "package-lock.json",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "Gemfile",
    "composer.json",
    "Package.swift",
    "pubspec.yaml",
    "mix.exs",
    "CMakeLists.txt",
    "Makefile",
    "meson.build",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
)

_MANIFEST_LANGUAGE_HINTS = {
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "pipfile": "python",
    "setup.py": "python",
    "package.json": "node",
    "pnpm-lock.yaml": "node",
    "yarn.lock": "node",
    "package-lock.json": "node",
    "go.mod": "go",
    "cargo.toml": "rust",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "kotlin",
    "settings.gradle": "java",
    "settings.gradle.kts": "kotlin",
    "gemfile": "ruby",
    "composer.json": "php",
    "package.swift": "swift",
    "pubspec.yaml": "dart",
    "mix.exs": "elixir",
    "cmakelists.txt": "c-cpp",
    "makefile": "c-cpp",
    "meson.build": "c-cpp",
}

_EXTENSION_LANGUAGE_HINTS = {
    ".py": "python",
    ".js": "node",
    ".jsx": "node",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".dart": "dart",
    ".ex": "elixir",
    ".exs": "elixir",
    ".cs": "dotnet",
    ".fs": "dotnet",
    ".cpp": "c-cpp",
    ".cc": "c-cpp",
    ".cxx": "c-cpp",
    ".c": "c-cpp",
    ".h": "c-cpp",
    ".hpp": "c-cpp",
    ".tf": "terraform",
    ".sql": "sql",
}

_PROJECT_FILE_PATTERNS = ("*.csproj", "*.fsproj", "*.sln")

_DEFAULT_EXCLUDES = (
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".uv-cache",
    "dist",
    "build",
    "data",
    ".idea",
    ".claude",
    ".pytest_tmp",
    ".pytest-tmp",
)

_KIND_PRIORITY = {
    ResourceKind.SOURCE: 3,
    ResourceKind.TEST: 2,
    ResourceKind.CONFIG: 1,
    ResourceKind.PUBLIC: 1,
    ResourceKind.DOCUMENTATION: 1,
}

_GRAPH_RESOURCE_KINDS = frozenset(
    {
        ResourceKind.SOURCE,
        ResourceKind.TEST,
        ResourceKind.CONFIG,
        ResourceKind.PUBLIC,
        ResourceKind.DOCUMENTATION,
    }
)


@dataclass(slots=True)
class WorkspaceScanner:
    max_resources: int = 30
    #: ``[security.classify]`` overrides, applied by the shared classifier.
    classify_overrides: Mapping[str, str] = field(default_factory=dict)

    def scan(self, workspace: Workspace) -> WorkspaceManifest:
        root = workspace.root
        detected: set[str] = set()
        hints: set[str] = set()
        manifests: list[Path] = []

        for name in _MANIFEST_FILES:
            candidate = root / name
            if candidate.is_file():
                manifests.append(candidate)
                language = _MANIFEST_LANGUAGE_HINTS.get(name.casefold())
                if language:
                    detected.add(language)

        for pattern in _PROJECT_FILE_PATTERNS:
            if any(root.glob(pattern)):
                detected.add("dotnet")

        self._detect_languages_from_tree(root, detected)
        self._detect_framework_hints(root, hints)
        if (root / ".github" / "workflows").exists():
            hints.add("github-actions")

        entry_points = tuple(sorted(self._entry_points(root)))
        test_commands = self._test_commands(detected)
        build_commands = self._build_commands(detected)
        framework_hints = tuple(sorted(hints))

        return WorkspaceManifest(
            workspace_id=workspace.id,
            revision=workspace.revision,
            detected_languages=tuple(sorted(detected)),
            framework_hints=framework_hints,
            entry_points=entry_points,
            test_commands=test_commands,
            build_commands=build_commands,
        )

    def build_read_plan(
        self,
        workspace: Workspace,
        task: Task,
        *,
        purpose: str | None = None,
        required_paths: tuple[str, ...] = (),
    ) -> ReadPlan:
        root = workspace.root
        resources: list[ResourceRef] = []

        for name in _MANIFEST_FILES:
            path = root / name
            if path.is_file():
                resources.append(self._ref(workspace.id, path, root))

        readmes = sorted(
            [path for path in root.iterdir() if path.name.casefold().startswith("readme")]
        )
        for path in readmes[:3]:
            resources.append(self._ref(workspace.id, path, root))

        for relative in required_paths:
            if not isinstance(relative, str) or not relative.strip():
                continue
            path = (root / relative).resolve()
            try:
                path.relative_to(root.resolve())
            except ValueError:
                continue
            if not path.is_file() or self._excluded(path, root):
                continue
            kind = ResourceClassifier.classify(
                path, root=root, overrides=self.classify_overrides
            )
            if kind in {
                ResourceKind.SECRET,
                ResourceKind.EXTERNAL,
                ResourceKind.BINARY,
                ResourceKind.OTHER,
            }:
                continue
            ref = self._ref(workspace.id, path, root)
            if ref not in resources:
                resources.append(ref)

        candidates: list[tuple[int, Path]] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if self._excluded(path, root):
                continue
            kind = ResourceClassifier.classify(
                path, root=root, overrides=self.classify_overrides
            )
            if kind in {
                ResourceKind.SECRET,
                ResourceKind.EXTERNAL,
                ResourceKind.BINARY,
                ResourceKind.OTHER,
            }:
                continue
            score = self._relevance_score(path, task.instruction)
            score += _KIND_PRIORITY.get(kind, 0)
            candidates.append((score, path))

        candidates.sort(key=lambda item: (-item[0], item[1].as_posix()))
        for _, path in candidates[: self.max_resources]:
            ref = self._ref(workspace.id, path, root)
            if ref not in resources:
                resources.append(ref)

        return ReadPlan(
            task_id=task.id,
            purpose=purpose or task.instruction,
            resources=tuple(resources),
            excludes=_DEFAULT_EXCLUDES,
            stage=ReadStage.TARGETED_READ,
        )

    def collect_resources(self, workspace: Workspace) -> tuple[ResourceRef, ...]:
        """Collect every readable resource for full-graph construction.

        Unlike :meth:`build_read_plan`, this is not task-targeted or capped by
        ``max_resources``; the workspace graph needs the whole source tree so
        import/call edges between sibling source files are discoverable.
        """
        root = workspace.root
        resources: list[ResourceRef] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if self._excluded(path, root):
                continue
            kind = ResourceClassifier.classify(
                path, root=root, overrides=self.classify_overrides
            )
            if kind not in _GRAPH_RESOURCE_KINDS:
                continue
            resources.append(self._ref(workspace.id, path, root))
        return tuple(resources)

    def _ref(
        self, workspace_id: str, path: Path, root: Path | None = None
    ) -> ResourceRef:
        return ResourceRef(
            workspace_id=workspace_id,
            path=path.as_posix(),
            kind=ResourceClassifier.classify(
                path, root=root, overrides=self.classify_overrides
            ),
        )

    @staticmethod
    def _detect_languages_from_tree(root: Path, detected: set[str]) -> None:
        for path in root.rglob("*"):
            if not path.is_file() or WorkspaceScanner._excluded(path, root):
                continue
            language = _EXTENSION_LANGUAGE_HINTS.get(path.suffix.casefold())
            if language:
                detected.add(language)

    @staticmethod
    def _detect_framework_hints(root: Path, hints: set[str]) -> None:
        if (root / "Dockerfile").is_file() or any(root.glob("Dockerfile.*")):
            hints.add("docker")
        if any((root / name).is_file() for name in _compose_names()):
            hints.add("docker-compose")
        if (root / "openapi.yaml").is_file() or (root / "openapi.yml").is_file():
            hints.add("openapi")
        if (root / "schema.graphql").is_file() or (root / "graphql").is_dir():
            hints.add("graphql")
        if (root / "proto").is_dir() or any(root.rglob("*.proto")):
            hints.add("protobuf")
        if (root / "prisma" / "schema.prisma").is_file():
            hints.add("prisma")
        if (root / "alembic").is_dir() or (root / "migrations").is_dir():
            hints.add("project-database")
        if any(root.glob("*.tf")):
            hints.add("terraform")

    @staticmethod
    def _entry_points(root: Path) -> list[str]:
        entry_points: list[str] = []
        entry_points.extend(WorkspaceScanner._python_entry_points(root))
        package = WorkspaceScanner._read_json(root, "package.json")
        for key in ("main", "module", "bin"):
            value = package.get(key)
            if isinstance(value, str):
                entry_points.append(value)
            elif isinstance(value, dict):
                entry_points.extend(str(item) for item in value.values())
        if (root / "cmd").is_dir():
            entry_points.append("cmd/")
        if (root / "src" / "main.rs").is_file():
            entry_points.append("src/main.rs")
        if (root / "src" / "main").is_dir():
            entry_points.append("src/main/")
        return entry_points

    @staticmethod
    def _python_entry_points(root: Path) -> list[str]:
        pyproject = root / "pyproject.toml"
        if not pyproject.is_file():
            return []
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            scripts = data.get("project", {}).get("scripts", {})
            return list(scripts)
        except (OSError, tomllib.TOMLDecodeError):
            return []

    @staticmethod
    def _test_commands(languages: set[str]) -> tuple[str, ...]:
        commands: list[str] = []
        if "python" in languages:
            commands.append("pytest")
        if "node" in languages:
            commands.append("npm test")
        if "go" in languages:
            commands.append("go test ./...")
        if "rust" in languages:
            commands.append("cargo test")
        if "java" in languages:
            commands.append("mvn test")
        if "kotlin" in languages:
            commands.append("gradle test")
        if "ruby" in languages:
            commands.append("bundle exec rspec")
        if "php" in languages:
            commands.append("composer test")
        if "swift" in languages:
            commands.append("swift test")
        if "dart" in languages:
            commands.append("dart test")
        if "elixir" in languages:
            commands.append("mix test")
        if "dotnet" in languages:
            commands.append("dotnet test")
        return tuple(commands)

    @staticmethod
    def _build_commands(languages: set[str]) -> tuple[str, ...]:
        commands: list[str] = []
        if "node" in languages:
            commands.append("npm run build")
        if "go" in languages:
            commands.append("go build ./...")
        if "rust" in languages:
            commands.append("cargo build")
        if "java" in languages:
            commands.append("mvn package")
        if "kotlin" in languages:
            commands.append("gradle build")
        if "ruby" in languages:
            commands.append("bundle install")
        if "php" in languages:
            commands.append("composer install")
        if "swift" in languages:
            commands.append("swift build")
        if "dart" in languages:
            commands.append("dart compile exe")
        if "elixir" in languages:
            commands.append("mix compile")
        if "dotnet" in languages:
            commands.append("dotnet build")
        if "c-cpp" in languages:
            commands.append("cmake --build build")
        return tuple(commands)

    @staticmethod
    def _excluded(path: Path, root: Path) -> bool:
        try:
            relative = path.relative_to(root)
        except ValueError:
            return True
        parts = relative.parts
        return any(part in _DEFAULT_EXCLUDES for part in parts)

    @staticmethod
    def _relevance_score(path: Path, instruction: str) -> int:
        text = f"{path.as_posix()} {instruction}".casefold()
        score = 0
        for keyword in ("login", "auth", "rate", "limit", "api"):
            if keyword in text:
                score += 1
        return score

    @staticmethod
    def workspace_kind(root: Path) -> WorkspaceKind:
        if (root / ".git").exists():
            return WorkspaceKind.GIT_REPOSITORY
        return WorkspaceKind.LOCAL_DIRECTORY

    @staticmethod
    def _read_json(root: Path, name: str) -> dict:
        path = root / name
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}


def _compose_names() -> tuple[str, ...]:
    return (
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
    )
