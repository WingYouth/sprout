"""Basic workspace graph models and builder."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from Sprout.workspace.evidence import EvidenceRef
from Sprout.workspace.models import (
    ReadPlan,
    ResourceRef,
    Workspace,
    WorkspaceGranularity,
)


@dataclass(frozen=True, slots=True)
class WorkspaceNode:
    id: str = field(default_factory=lambda: str(uuid4()))
    resource: ResourceRef | None = None
    kind: str = "resource"
    name: str = ""
    line: int = 0
    qualified_name: str = ""
    granularity: str = WorkspaceGranularity.FILE.value


@dataclass(frozen=True, slots=True)
class WorkspaceEdge:
    id: str = field(default_factory=lambda: str(uuid4()))
    source: str = ""
    target: str = ""
    relation: str = ""
    evidence: tuple[str, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class WorkspaceGraph:
    workspace_id: str
    nodes: tuple[WorkspaceNode, ...] = ()
    edges: tuple[WorkspaceEdge, ...] = ()


class WorkspaceGraphBuilder:
    max_source_bytes: int = 100_000

    def build(self, workspace: Workspace, plan: ReadPlan) -> WorkspaceGraph:
        file_nodes = tuple(
            WorkspaceNode(
                id=self._node_id(workspace.id, ref.path),
                resource=ref,
                kind=ref.kind.value,
                name=ref.path,
                granularity=self._file_granularity(ref.path),
            )
            for ref in plan.resources
        )
        module_nodes, contains_edges = self._module_nodes(workspace, file_nodes)
        frontend_nodes, frontend_edges = self._frontend_nodes(workspace, file_nodes)
        runtime_nodes, runtime_edges = self._runtime_asset_nodes(
            workspace,
            file_nodes,
        )
        symbol_nodes, defines_edges = self._python_symbol_nodes(
            workspace,
            file_nodes,
        )
        generic_symbol_nodes, generic_defines_edges = self._generic_symbol_nodes(
            workspace,
            file_nodes,
        )
        nodes = (
            file_nodes
            + module_nodes
            + frontend_nodes
            + runtime_nodes
            + symbol_nodes
            + generic_symbol_nodes
        )
        nodes_by_path = {node.name: node for node in file_nodes}
        edges = list(
            self._build_python_import_edges(workspace, file_nodes, nodes_by_path)
        )
        edges.extend(contains_edges)
        edges.extend(frontend_edges)
        edges.extend(runtime_edges)
        edges.extend(defines_edges)
        edges.extend(generic_defines_edges)
        symbols = {
            node.qualified_name or node.name: node
            for node in symbol_nodes
        }
        edges.extend(
            self._build_python_symbol_relations(
                workspace,
                file_nodes,
                symbols,
            )
        )
        return WorkspaceGraph(workspace_id=workspace.id, nodes=nodes, edges=tuple(edges))

    def _module_nodes(
        self,
        workspace: Workspace,
        file_nodes: tuple[WorkspaceNode, ...],
    ) -> tuple[tuple[WorkspaceNode, ...], tuple[WorkspaceEdge, ...]]:
        root = Path(workspace.root).resolve()
        module_paths = {
            Path(node.resource.path).resolve().parent
            for node in file_nodes
            if node.resource is not None
        }
        module_nodes: list[WorkspaceNode] = []
        contains_edges: list[WorkspaceEdge] = []

        for directory in sorted(module_paths):
            if directory == root:
                continue
            try:
                relative = directory.relative_to(root).as_posix()
            except ValueError:
                continue
            if not relative or any(part.startswith(".") for part in relative.split("/")):
                continue
            module_node = WorkspaceNode(
                id=f"{workspace.id}:module:{relative}",
                kind="module",
                name=relative,
                granularity=WorkspaceGranularity.MODULE.value,
            )
            module_nodes.append(module_node)
            for file_node in file_nodes:
                if file_node.resource is None:
                    continue
                parent = Path(file_node.resource.path).resolve().parent
                if parent == directory:
                    contains_edges.append(
                        WorkspaceEdge(
                            id=self._edge_id(module_node.id, file_node.id, "contains"),
                            source=module_node.id,
                            target=file_node.id,
                            relation="contains",
                        )
                    )

        return tuple(module_nodes), tuple(contains_edges)

    def _frontend_nodes(
        self,
        workspace: Workspace,
        file_nodes: tuple[WorkspaceNode, ...],
    ) -> tuple[tuple[WorkspaceNode, ...], tuple[WorkspaceEdge, ...]]:
        root = Path(workspace.root).resolve()
        kind_by_directory = {
            "components": "component",
            "pages": "page",
            "routes": "route",
            "hooks": "hook",
            "stores": "store",
        }
        suffixes = {".js", ".jsx", ".ts", ".tsx"}
        nodes: list[WorkspaceNode] = []
        edges: list[WorkspaceEdge] = []
        nodes_by_qualified: dict[str, WorkspaceNode] = {}

        for file_node in file_nodes:
            if file_node.resource is None:
                continue
            path = Path(file_node.resource.path).resolve()
            if path.suffix not in suffixes:
                continue
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            parts = relative.parts[:-1]
            kind = next(
                (
                    kind_by_directory[part]
                    for part in parts
                    if part in kind_by_directory
                ),
                "",
            )
            if not kind:
                continue
            qualified_name = relative.with_suffix("").as_posix()
            node = WorkspaceNode(
                id=f"{workspace.id}:frontend:{qualified_name}",
                resource=file_node.resource,
                kind=kind,
                name=qualified_name,
                qualified_name=qualified_name,
                granularity=WorkspaceGranularity.SYMBOL.value,
            )
            nodes.append(node)
            nodes_by_qualified[qualified_name] = node
            edges.append(
                WorkspaceEdge(
                    id=self._edge_id(file_node.id, node.id, "defines"),
                    source=file_node.id,
                    target=node.id,
                    relation="defines",
                )
            )

        for node in nodes:
            if node.resource is None:
                continue
            path = Path(node.resource.path).resolve()
            for import_name in self._frontend_imports(path):
                target_name = self._resolve_frontend_import(
                    root,
                    path,
                    import_name,
                )
                target = nodes_by_qualified.get(target_name)
                if target is None or target.id == node.id:
                    continue
                edges.append(
                    WorkspaceEdge(
                        id=self._edge_id(node.id, target.id, "component_uses"),
                        source=node.id,
                        target=target.id,
                        relation="component_uses",
                    )
                )

        return tuple(nodes), tuple(edges)

    @staticmethod
    def _frontend_imports(path: Path) -> tuple[str, ...]:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return ()
        matches = re.findall(r"\bfrom\s+[\"']([^\"']+)[\"']", text)
        matches.extend(re.findall(r"\bimport\s+[\"']([^\"']+)[\"']", text))
        return tuple(matches)

    @staticmethod
    def _resolve_frontend_import(
        root: Path,
        source_path: Path,
        import_name: str,
    ) -> str:
        if import_name.startswith("@/"):
            resolved = (root / "src" / import_name[2:]).with_suffix("")
        elif import_name.startswith("."):
            resolved = (source_path.parent / import_name).with_suffix("")
        else:
            return ""
        try:
            return resolved.resolve().relative_to(root).as_posix()
        except ValueError:
            return ""

    def _runtime_asset_nodes(
        self,
        workspace: Workspace,
        file_nodes: tuple[WorkspaceNode, ...],
    ) -> tuple[tuple[WorkspaceNode, ...], tuple[WorkspaceEdge, ...]]:
        root = Path(workspace.root).resolve()
        kind_by_marker = {
            ("routes",): "api_route",
            ("api",): "api_route",
            ("endpoints",): "api_route",
            ("models",): "data_asset",
            ("schema",): "data_asset",
            ("migrations",): "data_asset",
            ("config",): "config_asset",
            ("settings",): "config_asset",
        }
        suffixes = {".py", ".ts", ".js", ".sql", ".toml", ".yaml", ".yml"}
        nodes: list[WorkspaceNode] = []
        edges: list[WorkspaceEdge] = []

        for file_node in file_nodes:
            if file_node.resource is None:
                continue
            path = Path(file_node.resource.path).resolve()
            if path.suffix not in suffixes:
                continue
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            parts = relative.parts[:-1]
            asset_kind = next(
                (
                    kind
                    for markers, kind in kind_by_marker.items()
                    if any(marker in parts for marker in markers)
                ),
                "",
            )
            if not asset_kind:
                continue
            qualified_name = relative.with_suffix("").as_posix()
            node = WorkspaceNode(
                id=f"{workspace.id}:runtime:{qualified_name}",
                resource=file_node.resource,
                kind=asset_kind,
                name=qualified_name,
                qualified_name=qualified_name,
                granularity=WorkspaceGranularity.RUNTIME_ASSET.value,
            )
            nodes.append(node)
            edges.append(
                WorkspaceEdge(
                    id=self._edge_id(file_node.id, node.id, "defines"),
                    source=file_node.id,
                    target=node.id,
                    relation="defines",
                )
            )

        return tuple(nodes), tuple(edges)

    def _build_python_import_edges(
        self,
        workspace: Workspace,
        nodes: tuple[WorkspaceNode, ...],
        nodes_by_path: dict[str, WorkspaceNode],
    ) -> tuple[WorkspaceEdge, ...]:
        edges: list[WorkspaceEdge] = []
        for node in nodes:
            if node.resource is None or node.kind != "source":
                continue
            path = Path(workspace.root) / node.resource.path
            if path.suffix != ".py":
                continue
            imports = self._python_imports(path)
            for module in imports:
                target = self._resolve_module(module, nodes_by_path)
                if target is None or target.id == node.id:
                    continue
                edges.append(
                    WorkspaceEdge(
                        id=self._edge_id(node.id, target.id, "imports"),
                        source=node.id,
                        target=target.id,
                        relation="imports",
                        evidence=(node.resource.path, target.resource.path),
                    )
                )
        return tuple(edges)

    def _build_python_symbol_relations(
        self,
        workspace: Workspace,
        file_nodes: tuple[WorkspaceNode, ...],
        symbols: dict[str, WorkspaceNode],
    ) -> tuple[WorkspaceEdge, ...]:
        edges: list[WorkspaceEdge] = []

        for file_node in file_nodes:
            if file_node.resource is None or not file_node.resource.path.endswith(".py"):
                continue
            path = Path(workspace.root) / file_node.resource.path
            tree = self._parse_python(path)
            if tree is None:
                continue
            self._collect_symbol_relations(
                tree.body,
                file_node,
                symbols,
                edges,
            )
        return tuple(edges)

    def _collect_symbol_relations(
        self,
        body: list[ast.stmt],
        file_node: WorkspaceNode,
        symbols: dict[str, WorkspaceNode],
        edges: list[WorkspaceEdge],
    ) -> None:
        for statement in body:
            if isinstance(statement, ast.ClassDef):
                class_symbol = self._resolve_symbol(
                    statement.name,
                    statement.lineno,
                    symbols,
                )
                if class_symbol is not None:
                    for base in statement.bases:
                        if not isinstance(base, ast.Name):
                            continue
                        target = self._resolve_symbol(
                            base.id,
                            base.lineno,
                            symbols,
                        )
                        if target is not None and target.id != class_symbol.id:
                            edges.append(
                                self._relation_edge(
                                    class_symbol,
                                    target,
                                    "inherits",
                                    base.lineno,
                                )
                            )
                    for member in statement.body:
                        if isinstance(
                            member,
                            ast.FunctionDef | ast.AsyncFunctionDef,
                        ):
                            method_symbol = self._resolve_symbol(
                                f"{statement.name}.{member.name}",
                                member.lineno,
                                symbols,
                            )
                            if method_symbol is not None:
                                self._collect_call_relations(
                                    member,
                                    method_symbol,
                                    symbols,
                                    edges,
                                )
            elif isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
                function_symbol = self._resolve_symbol(
                    statement.name,
                    statement.lineno,
                    symbols,
                )
                if function_symbol is not None:
                    self._collect_call_relations(
                        statement,
                        function_symbol,
                        symbols,
                        edges,
                    )
            else:
                self._collect_module_calls(
                    statement,
                    file_node,
                    symbols,
                    edges,
                )

    def _collect_module_calls(
        self,
        statement: ast.stmt,
        file_node: WorkspaceNode,
        symbols: dict[str, WorkspaceNode],
        edges: list[WorkspaceEdge],
    ) -> None:
        for node in ast.walk(statement):
            if not isinstance(node, ast.Call):
                continue
            target_name = self._call_target(node.func)
            if not target_name:
                continue
            target = self._resolve_symbol(target_name, node.lineno, symbols)
            if target is None:
                continue
            edges.append(
                self._relation_edge(
                    file_node,
                    target,
                    "calls",
                    node.lineno,
                )
            )

    def _collect_call_relations(
        self,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        source: WorkspaceNode,
        symbols: dict[str, WorkspaceNode],
        edges: list[WorkspaceEdge],
    ) -> None:
        for node in ast.walk(function):
            if isinstance(node, ast.Name):
                target = self._resolve_symbol(
                    node.id,
                    node.lineno,
                    symbols,
                )
                if target is not None and target.id != source.id:
                    edges.append(
                        self._relation_edge(
                            source,
                            target,
                            "references",
                            node.lineno,
                        )
                    )
            if not isinstance(node, ast.Call):
                continue
            target_name = self._call_target(node.func)
            if not target_name:
                continue
            target = self._resolve_symbol(target_name, node.lineno, symbols)
            if target is None or target.id == source.id:
                continue
            edges.append(
                self._relation_edge(source, target, "calls", node.lineno)
            )
            if source.kind == "test":
                edges.append(
                    self._relation_edge(source, target, "tests", node.lineno)
                )

    def _relation_edge(
        self,
        source: WorkspaceNode,
        target: WorkspaceNode,
        relation: str,
        line: int,
    ) -> WorkspaceEdge:
        evidence = EvidenceRef(
            source_type="file",
            path=source.resource.path if source.resource else "",
            line=line,
            analyzer="python_ast",
        )
        return WorkspaceEdge(
            id=f"{source.id}->{target.id}:{relation}@{line}",
            source=source.id,
            target=target.id,
            relation=relation,
            evidence=(source.resource.path if source.resource else "",),
            evidence_refs=(evidence,),
            confidence=0.85,
        )

    @staticmethod
    def _resolve_symbol(
        name: str,
        line: int,
        symbols: dict[str, WorkspaceNode],
    ) -> WorkspaceNode | None:
        if name in symbols:
            return symbols[name]
        suffix = f".{name}"
        for qualified, node in symbols.items():
            if qualified.endswith(suffix) and node.line == line:
                return node
        for qualified, node in symbols.items():
            if qualified.endswith(suffix):
                return node
        return None

    def _python_symbol_nodes(
        self,
        workspace: Workspace,
        file_nodes: tuple[WorkspaceNode, ...],
    ) -> tuple[tuple[WorkspaceNode, ...], tuple[WorkspaceEdge, ...]]:
        symbol_nodes: list[WorkspaceNode] = []
        defines_edges: list[WorkspaceEdge] = []

        for file_node in file_nodes:
            if file_node.resource is None or not file_node.resource.path.endswith(".py"):
                continue
            path = Path(workspace.root) / file_node.resource.path
            tree = self._parse_python(path)
            if tree is None:
                continue

            for item in tree.body:
                if isinstance(item, ast.ClassDef):
                    class_node = self._symbol_node(
                        workspace,
                        file_node,
                        item.name,
                        item.lineno,
                        "class",
                    )
                    symbol_nodes.append(class_node)
                    defines_edges.append(
                        self._defines_edge(file_node, class_node)
                    )
                    for member in item.body:
                        if isinstance(
                            member,
                            ast.FunctionDef | ast.AsyncFunctionDef,
                        ):
                            method_node = self._symbol_node(
                                workspace,
                                file_node,
                                f"{item.name}.{member.name}",
                                member.lineno,
                                "method",
                            )
                            symbol_nodes.append(method_node)
                            defines_edges.append(
                                self._defines_edge(file_node, method_node)
                            )
                elif isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    kind = "test" if item.name.startswith("test_") else "function"
                    function_node = self._symbol_node(
                        workspace,
                        file_node,
                        item.name,
                        item.lineno,
                        kind,
                    )
                    symbol_nodes.append(function_node)
                    defines_edges.append(
                        self._defines_edge(file_node, function_node)
                    )

        return tuple(symbol_nodes), tuple(defines_edges)

    def _symbol_node(
        self,
        workspace: Workspace,
        file_node: WorkspaceNode,
        qualified_name: str,
        line: int,
        kind: str,
    ) -> WorkspaceNode:
        resource = file_node.resource
        if resource is None:
            raise ValueError("Python file node has no resource")
        return WorkspaceNode(
            id=self._symbol_node_id(workspace.id, resource.path, qualified_name, line),
            resource=resource,
            kind=kind,
            name=f"{resource.path}:{qualified_name}",
            line=line,
            qualified_name=qualified_name,
            granularity=WorkspaceGranularity.SYMBOL.value,
        )

    def _generic_symbol_nodes(
        self,
        workspace: Workspace,
        file_nodes: tuple[WorkspaceNode, ...],
    ) -> tuple[tuple[WorkspaceNode, ...], tuple[WorkspaceEdge, ...]]:
        """Lightweight symbol extraction for non-Python source files.

        This is intentionally regex-based, not a real parser per language: it
        gives the multi-language analyzer a symbol surface (functions, classes,
        methods, structs) without pulling a tree-sitter grammar for each one.
        """
        symbol_nodes: list[WorkspaceNode] = []
        defines_edges: list[WorkspaceEdge] = []

        for file_node in file_nodes:
            resource = file_node.resource
            if resource is None:
                continue
            suffix = Path(resource.path).suffix.casefold()
            if suffix not in _GENERIC_SYMBOL_SUFFIXES:
                continue
            path = Path(workspace.root) / resource.path
            for name, kind, line in _extract_generic_symbols(path, suffix):
                node = WorkspaceNode(
                    id=self._symbol_node_id(
                        workspace.id,
                        resource.path,
                        name,
                        line,
                    ),
                    resource=resource,
                    kind=kind,
                    name=f"{resource.path}:{name}",
                    line=line,
                    qualified_name=name,
                    granularity=WorkspaceGranularity.SYMBOL.value,
                )
                symbol_nodes.append(node)
                defines_edges.append(self._defines_edge(file_node, node))

        return tuple(symbol_nodes), tuple(defines_edges)

    def _defines_edge(
        self,
        file_node: WorkspaceNode,
        symbol_node: WorkspaceNode,
    ) -> WorkspaceEdge:
        evidence = EvidenceRef(
            source_type="file",
            path=file_node.resource.path if file_node.resource else "",
            line=symbol_node.line,
            analyzer="python_ast",
        )
        return WorkspaceEdge(
            id=self._edge_id(file_node.id, symbol_node.id, "defines"),
            source=file_node.id,
            target=symbol_node.id,
            relation="defines",
            evidence=((file_node.resource.path if file_node.resource else ""),),
            evidence_refs=(evidence,),
            confidence=1.0,
        )

    def _python_imports(self, path: Path) -> set[str]:
        try:
            data = path.read_bytes()
        except OSError:
            return set()
        if len(data) > self.max_source_bytes:
            return set()
        try:
            tree = ast.parse(data, filename=str(path))
        except (SyntaxError, ValueError):
            return set()

        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.add(node.module)
        return modules

    def _parse_python(self, path: Path) -> ast.Module | None:
        try:
            data = path.read_bytes()
        except OSError:
            return None
        if len(data) > self.max_source_bytes:
            return None
        try:
            return ast.parse(data, filename=str(path))
        except (SyntaxError, ValueError):
            return None

    @staticmethod
    def _call_target(func: ast.expr) -> str | None:
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return None

    @staticmethod
    def _resolve_module(
        module: str,
        nodes_by_path: dict[str, WorkspaceNode],
    ) -> WorkspaceNode | None:
        module_parts = tuple(part.casefold() for part in module.split("."))
        for path, node in nodes_by_path.items():
            parts = list(Path(path).parts)
            if parts and parts[-1].casefold().endswith(".py"):
                parts[-1] = parts[-1][: -len(".py")]
            parts = [part.casefold() for part in parts]
            matches = len(parts) >= len(module_parts) and tuple(
                parts[-len(module_parts) :]
            ) == module_parts
            if matches:
                return node
        return None

    @staticmethod
    def _node_id(workspace_id: str, path: str) -> str:
        return f"{workspace_id}:{path}"

    @staticmethod
    def _file_granularity(path: str) -> str:
        name = Path(path).name.casefold()
        if name in {
            "pyproject.toml",
            "package.json",
            "go.mod",
            "cargo.toml",
            "pom.xml",
        }:
            return WorkspaceGranularity.PROJECT.value
        return WorkspaceGranularity.FILE.value

    @staticmethod
    def _symbol_node_id(
        workspace_id: str,
        path: str,
        qualified_name: str,
        line: int,
    ) -> str:
        return f"{workspace_id}:{path}::{qualified_name}@{line}"

    @staticmethod
    def _edge_id(source: str, target: str, relation: str) -> str:
        return f"{source}->{target}:{relation}"


_GENERIC_SYMBOL_SUFFIXES = frozenset({".go", ".rs", ".java", ".js", ".jsx", ".ts", ".tsx"})


def _extract_generic_symbols(path: Path, suffix: str) -> list[tuple[str, str, int]]:
    """Return ``(name, kind, line)`` symbols via lightweight per-language regex."""
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if len(data) > 100_000:
        return []
    text = data.decode("utf-8", errors="replace")

    patterns = _generic_patterns(suffix)
    symbols: list[tuple[str, str, int]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for pattern, kind in patterns:
            match = pattern.search(line)
            if match and match.group(1):
                symbols.append((match.group(1), kind, line_no))
    return symbols


def _generic_patterns(suffix: str) -> tuple[tuple[re.Pattern[str], str], ...]:
    if suffix == ".go":
        return (
            (re.compile(r"func\s+(?:\([^)]*\)\s+)?([A-Za-z_]\w*)\s*\("), "function"),
            (re.compile(r"type\s+([A-Za-z_]\w*)\s+(?:struct|interface)\b"), "class"),
        )
    if suffix == ".rs":
        return (
            (re.compile(r"fn\s+([A-Za-z_]\w*)\s*\("), "function"),
            (re.compile(r"struct\s+([A-Za-z_]\w*)"), "class"),
            (re.compile(r"enum\s+([A-Za-z_]\w*)"), "class"),
            (re.compile(r"impl\s+(?:\w+\s+for\s+)?([A-Za-z_]\w*)"), "class"),
        )
    if suffix == ".java":
        return (
            (re.compile(r"(?:class|interface|enum)\s+([A-Za-z_]\w*)"), "class"),
            (
                re.compile(
                    r"(?:public|private|protected)\s+[\w<>\[\],\.\s]+\s+"
                    r"([A-Za-z_]\w*)\s*\("
                ),
                "method",
            ),
        )
    return (
        (re.compile(r"function\s+([A-Za-z_]\w*)\s*\("), "function"),
        (re.compile(r"class\s+([A-Za-z_]\w*)"), "class"),
        (
            re.compile(
                r"(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?[^=]*=>"
            ),
            "function",
        ),
    )
