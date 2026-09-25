"""Workspace Intelligence assembly and persistence."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from Sprout.task.models import Task
from Sprout.workspace.graph import WorkspaceGraph, WorkspaceGraphBuilder
from Sprout.workspace.invalidation import WorkspaceFingerprint
from Sprout.workspace.knowledge import (
    ProjectKnowledge,
    ProjectKnowledgeBuilder,
    ProjectKnowledgeItem,
)
from Sprout.workspace.models import ReadPlan, ReadStage, Workspace, WorkspaceManifest
from Sprout.workspace.query import WorkspaceQuery
from Sprout.workspace.scanner import WorkspaceScanner
from Sprout.workspace.skills import SkillWorkspaceAnalyzer

if TYPE_CHECKING:
    from Sprout.storage.contracts.graph import GraphStore
    from Sprout.storage.contracts.knowledge import KnowledgeItem, KnowledgeStore
    from Sprout.storage.contracts.vectors import VectorStore


@dataclass(frozen=True, slots=True)
class WorkspaceAnalysis:
    workspace: Workspace
    manifest: WorkspaceManifest
    read_plan: ReadPlan
    graph: WorkspaceGraph
    knowledge: ProjectKnowledge
    fingerprint: WorkspaceFingerprint
    changed_resources: tuple[str, ...] = ()
    stale_knowledge_ids: tuple[str, ...] = ()
    stale_knowledge_items: tuple[ProjectKnowledgeItem, ...] = ()

    def query(self) -> WorkspaceQuery:
        return WorkspaceQuery(self)

    def context_summary(
        self,
        *,
        knowledge_limit: int = 5,
        edge_limit: int = 20,
    ) -> str:
        """Render a compact workspace context block for agent metadata."""
        lines: list[str] = [f"Workspace: {self.workspace.id}"]
        languages = ", ".join(self.manifest.detected_languages) or "unknown"
        lines.append(f"Languages: {languages}")

        facts = [
            item.statement
            for item in self.knowledge.items
            if item.kind == "fact"
        ][:knowledge_limit]
        inferences = [
            item.statement
            for item in self.knowledge.items
            if item.kind == "inference"
        ][:knowledge_limit]
        if facts:
            lines.append("Facts:")
            lines.extend(f"- {item}" for item in facts)
        if inferences:
            lines.append("Inferences:")
            lines.extend(f"- {item}" for item in inferences)
        if self.stale_knowledge_ids:
            lines.append(f"Stale knowledge: {len(self.stale_knowledge_ids)} item(s)")

        lines.append(
            f"Graph: {len(self.graph.nodes)} nodes, {len(self.graph.edges)} edges"
        )
        relations = sorted({edge.relation for edge in self.graph.edges})
        if relations:
            lines.append("Relations: " + ", ".join(relations))
        for edge in self.graph.edges[:edge_limit]:
            lines.append(f"- {edge.relation}: {edge.source} -> {edge.target}")

        return "\n".join(lines)


class WorkspaceIntelligence:
    """Builds and optionally persists a workspace analysis snapshot."""

    def __init__(
        self,
        *,
        scanner: WorkspaceScanner | None = None,
        graph_builder: WorkspaceGraphBuilder | None = None,
        knowledge_builder: ProjectKnowledgeBuilder | None = None,
        knowledge_store: KnowledgeStore | None = None,
        vector_store: VectorStore | None = None,
        skills_dir: str | None = None,
        graph_store: GraphStore | None = None,
    ) -> None:
        self._scanner = scanner or WorkspaceScanner()
        self._graph_builder = graph_builder or WorkspaceGraphBuilder()
        self._knowledge_builder = knowledge_builder or ProjectKnowledgeBuilder()
        self._knowledge_store = knowledge_store
        self._vector_store = vector_store
        # Match the Milvus collection width (1536) and the six-lane fan-out so
        # knowledge vectors land in the same schema as every other layer. The
        # import is lazy because ``Sprout.storage`` pulls in the rootstock and
        # execution layers, which would circular-import the workspace package.
        from Sprout.storage.embeddings import make_embedder

        self._vectorizer = make_embedder()
        self._skills_dir = skills_dir
        self._graph_store = graph_store

    async def analyze(
        self,
        workspace: Workspace,
        task: Task,
        *,
        previous: WorkspaceAnalysis | None = None,
    ) -> WorkspaceAnalysis:
        manifest = workspace.manifest or self._scanner.scan(workspace)
        enriched = Workspace(
            id=workspace.id,
            root=workspace.root,
            kind=workspace.kind,
            revision=workspace.revision,
            manifest=manifest,
        )
        read_plan = self._scanner.build_read_plan(enriched, task)
        fingerprint = WorkspaceFingerprint.compute(enriched, read_plan)
        if previous is not None and not fingerprint.is_stale(previous.fingerprint):
            return previous

        graph_resources = self._scanner.collect_resources(enriched)
        graph_plan = ReadPlan(
            task_id=task.id,
            purpose=read_plan.purpose,
            resources=graph_resources,
            excludes=read_plan.excludes,
            stage=read_plan.stage,
        )
        graph = self._graph_builder.build(enriched, graph_plan)
        knowledge = self._knowledge_builder.build(enriched, manifest)
        if self._skills_dir is not None:
            skill_analysis = SkillWorkspaceAnalyzer().analyze(
                enriched.id,
                self._skills_dir,
            )
            graph = replace(
                graph,
                nodes=graph.nodes + skill_analysis.nodes,
                edges=graph.edges + skill_analysis.edges,
            )
            knowledge = replace(
                knowledge,
                items=knowledge.items + skill_analysis.knowledge_items,
            )
        read_plan = self._refine_read_plan(read_plan, graph, knowledge)
        changed_resources = fingerprint.changed_resources(
            previous.fingerprint if previous is not None else None
        )
        stale_knowledge_ids = self._stale_knowledge_ids(
            previous,
            set(changed_resources),
        )
        stale_knowledge_items = self._stale_knowledge_items(
            previous,
            stale_knowledge_ids,
        )
        if previous is not None and changed_resources:
            graph = self._merge_graph(
                previous.graph,
                graph,
                set(changed_resources),
            )

        if self._knowledge_store is not None:
            await self._persist_knowledge(knowledge)
        if self._graph_store is not None:
            await self._persist_graph(graph)

        return WorkspaceAnalysis(
            workspace=enriched,
            manifest=manifest,
            read_plan=read_plan,
            graph=graph,
            knowledge=knowledge,
            fingerprint=fingerprint,
            changed_resources=changed_resources,
            stale_knowledge_ids=stale_knowledge_ids,
            stale_knowledge_items=stale_knowledge_items,
        )

    async def _persist_graph(self, graph: WorkspaceGraph) -> None:
        for node in graph.nodes:
            await self._graph_store.merge_node(
                "WorkspaceNode",
                "id",
                {
                    "id": node.id,
                    "kind": node.kind,
                    "name": node.name,
                    "qualified_name": node.qualified_name,
                    "line": node.line,
                    "granularity": node.granularity,
                },
            )
        for edge in graph.edges:
            await self._graph_store.merge_relation(
                "WorkspaceNode",
                edge.source,
                edge.relation,
                "WorkspaceNode",
                edge.target,
                props={"edge_id": edge.id},
            )

    @staticmethod
    def _stale_knowledge_ids(
        previous: WorkspaceAnalysis | None,
        changed_resources: set[str],
    ) -> tuple[str, ...]:
        if previous is None or not changed_resources:
            return ()
        return tuple(
            item.id
            for item in previous.knowledge.items
            if any(
                evidence in changed_resources
                for evidence in item.evidence_ids
            )
        )

    @staticmethod
    def _stale_knowledge_items(
        previous: WorkspaceAnalysis | None,
        stale_ids: tuple[str, ...],
    ) -> tuple[ProjectKnowledgeItem, ...]:
        if previous is None or not stale_ids:
            return ()
        stale_set = set(stale_ids)
        return tuple(
            item
            for item in previous.knowledge.items
            if item.id in stale_set
        )

    def _merge_graph(
        self,
        previous: WorkspaceGraph,
        current: WorkspaceGraph,
        changed_resources: set[str],
    ) -> WorkspaceGraph:
        """Replace only graph nodes/edges whose resource path changed."""
        removed_ids = {
            node.id
            for node in previous.nodes
            if node.resource is not None and node.resource.path in changed_resources
        }
        kept_nodes = tuple(
            node for node in previous.nodes if node.id not in removed_ids
        )
        kept_edges = tuple(
            edge
            for edge in previous.edges
            if edge.source not in removed_ids and edge.target not in removed_ids
        )
        kept_edge_ids = {edge.id for edge in kept_edges}
        kept_node_ids = {node.id for node in kept_nodes}

        new_nodes = tuple(
            node
            for node in current.nodes
            if node.resource is not None and node.resource.path in changed_resources
        )
        new_node_ids = {node.id for node in new_nodes}
        new_edges = tuple(
            edge
            for edge in current.edges
            if edge.id not in kept_edge_ids
            and (
                edge.source in new_node_ids
                or edge.target in new_node_ids
                or edge.source in kept_node_ids and edge.target in new_node_ids
                or edge.target in kept_node_ids and edge.source in new_node_ids
            )
        )
        return WorkspaceGraph(
            workspace_id=current.workspace_id,
            nodes=kept_nodes + new_nodes,
            edges=kept_edges + new_edges,
        )

    def _refine_read_plan(
        self,
        read_plan: ReadPlan,
        graph: WorkspaceGraph,
        knowledge: ProjectKnowledge,
    ) -> ReadPlan:
        scores: dict[str, int] = {}

        for edge in graph.edges:
            weight = {
                "imports": 3,
                "calls": 2,
                "inherits": 2,
                "tests": 2,
                "defines": 1,
            }.get(edge.relation, 1)
            self._bump_edge_score(graph, edge.source, scores, weight)
            self._bump_edge_score(graph, edge.target, scores, weight)

        for item in knowledge.items:
            if item.kind != "fact":
                continue
            for evidence_id in item.evidence_ids:
                scores[evidence_id] = scores.get(evidence_id, 0) + 2

        core_kinds = {"public", "documentation", "config"}
        resources = list(read_plan.resources)
        core = [
            resource
            for resource in resources
            if resource.kind.value in core_kinds
        ]
        ranked = [
            resource
            for resource in resources
            if resource.kind.value not in core_kinds
        ]
        ranked.sort(
            key=lambda resource: (-scores.get(resource.path, 0), resources.index(resource))
        )
        return replace(
            read_plan,
            resources=tuple([*core, *ranked]),
            stage=ReadStage.KNOWLEDGE,
        )

    @staticmethod
    def _bump_edge_score(
        graph: WorkspaceGraph,
        node_id: str,
        scores: dict[str, int],
        weight: int,
    ) -> None:
        for node in graph.nodes:
            if node.id == node_id and node.resource is not None:
                scores[node.resource.path] = scores.get(node.resource.path, 0) + weight
                return

    async def _persist_knowledge(self, knowledge: ProjectKnowledge) -> None:
        from Sprout.storage.contracts.knowledge import KnowledgeItem
        from Sprout.storage.contracts.vectors import KNOWLEDGE_CHUNKS

        for item in knowledge.items:
            await self._knowledge_store.put(
                KnowledgeItem(
                    id=item.id,
                    content=item.statement,
                    kind=item.kind,
                    evidence_ids=item.evidence_ids,
                )
            )
            if self._vector_store is not None:
                await self._vector_store.upsert(
                    item.id,
                    await self._vectorizer.embed(item.statement),
                    namespace=KNOWLEDGE_CHUNKS,
                    metadata={"item_id": item.id},
                )

    async def search_knowledge(
        self,
        query: str,
        *,
        limit: int = 5,
    ) -> tuple[KnowledgeItem, ...]:
        """Search persisted knowledge, using vector search when available."""
        if self._knowledge_store is None:
            return ()
        if self._vector_store is None:
            return tuple(await self._knowledge_store.search(query, limit=limit))

        from Sprout.storage.contracts.vectors import KNOWLEDGE_CHUNKS

        hits = await self._vector_store.search(
            await self._vectorizer.embed(query),
            limit=limit,
            namespace=KNOWLEDGE_CHUNKS,
        )
        items: list[KnowledgeItem] = []
        for hit in hits:
            item_id = str(hit.metadata.get("item_id", ""))
            if not item_id:
                continue
            item = await self._knowledge_store.get(item_id)
            if item is not None:
                items.append(item)
        if items:
            return tuple(items)
        return tuple(await self._knowledge_store.search(query, limit=limit))


__all__ = ["WorkspaceAnalysis", "WorkspaceIntelligence"]
