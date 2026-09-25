"""ContextBuilder assembles an AgentContext for each online turn."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from Sprout.config.settings import ContextSettings
from Sprout.context.context import PROGRESSIVE, AgentContext
from Sprout.context.retrieval import KnowledgeRetriever
from Sprout.context.workspace import (
    WorkspaceContext,
    WorkspaceGraphEdgeContext,
    WorkspaceGraphNodeContext,
)
from Sprout.memory.budget import BudgetAllocator
from Sprout.memory.composer import ContextComposer
from Sprout.memory.estimator import CharEstimator
from Sprout.message.models import Message
from Sprout.session.models import Session

if TYPE_CHECKING:
    from Sprout.skills.models import Skill
    from Sprout.storage.bundle import StorageBundle
    from Sprout.storage.contracts.knowledge import KnowledgeItem
    from Sprout.tools.base import Tool
    from Sprout.workspace.intelligence import WorkspaceAnalysis


class ContextBuilder:
    def __init__(
        self,
        storage: StorageBundle,
        *,
        context_settings: ContextSettings | None = None,
        model_window: int | None = None,
        workspace_analysis_provider: (
            Callable[[str], Awaitable[WorkspaceAnalysis]] | None
        ) = None,
        skill_disclosure: str = "",
    ) -> None:
        self._storage = storage
        # ``progressive`` (the default) injects only the L0 index; ``eager``
        # keeps the legacy full-body injection (design §6.1).
        self._skill_disclosure = skill_disclosure
        self._retriever = (
            KnowledgeRetriever(storage.knowledge)
            if storage.knowledge is not None
            else None
        )
        self._session_store = storage.session_store()
        self._settings = context_settings or ContextSettings()
        self._workspace_analysis_provider = workspace_analysis_provider
        self._memory_store = storage.memory
        estimator = CharEstimator()
        self._allocator = BudgetAllocator(self._settings)
        self._composer = ContextComposer(
            settings=self._settings,
            memory_store=self._memory_store,
            estimator=estimator,
            allocator=self._allocator,
            model_window=model_window,
        )

    async def build(
        self,
        *,
        message: Message,
        session: Session,
        tools: Mapping[str, Tool],
        skills: Mapping[str, Skill],
    ) -> AgentContext:
        knowledge = (
            await self._retriever.retrieve_for(message) if self._retriever else ()
        )
        history = await self._session_store.recent_turns(
            session.id, limit=self._settings.working_window
        )
        recalled = (
            await self._storage.session_search.search(
                message.content, limit=10, session_id=session.id
            )
            if self._storage.session_search is not None
            else ()
        )
        memory = await self._composer.assemble(
            session=session,
            history=history,
            recalled=recalled,
            knowledge=knowledge,
        )
        metadata = dict(message.metadata)
        workspace_context = None
        if self._workspace_analysis_provider is not None:
            workspace_id = metadata.get("workspace_id")
            if isinstance(workspace_id, str) and workspace_id:
                analysis = await self._workspace_analysis_provider(workspace_id)
                summary = analysis.context_summary()
                metadata["workspace_context"] = summary
                workspace_context = self._build_workspace_context(
                    analysis,
                    message,
                )
        await self._persist_context(session, history, memory)
        return AgentContext(
            session=session,
            memory=memory,
            knowledge=knowledge,
            tools=tools,
            skills=skills,
            user={"id": message.user_id},
            files=tuple(message.metadata.get("files", ())),
            metadata=metadata,
            workspace=workspace_context,
            skill_disclosure=self._skill_disclosure or PROGRESSIVE,
        )

    def _build_workspace_context(
        self,
        analysis,
        message: Message,
    ) -> WorkspaceContext:
        tokens = self._message_tokens(message.content)
        seeds = [
            node
            for node in analysis.graph.nodes
            if node.kind in {"class", "function", "method", "test"}
            and any(token in node.name.casefold() for token in tokens)
        ][:3]

        nodes: dict[str, WorkspaceGraphNodeContext] = {}
        edges: dict[str, WorkspaceGraphEdgeContext] = {}
        query = analysis.query()
        if seeds:
            for seed in seeds:
                subgraph = query.subgraph(seed.name, max_depth=2)
                for node in subgraph.nodes:
                    context_node = WorkspaceGraphNodeContext(
                        id=node.id,
                        kind=node.kind,
                        name=node.name,
                        qualified_name=node.qualified_name,
                        line=node.line,
                        granularity=node.granularity,
                    )
                    nodes[node.id] = context_node
                for edge in subgraph.edges:
                    context_edge = WorkspaceGraphEdgeContext(
                        source=edge.source,
                        target=edge.target,
                        relation=edge.relation,
                        confidence=edge.confidence,
                    )
                    edges[edge.id] = context_edge
        else:
            for node in analysis.graph.nodes[:30]:
                nodes[node.id] = WorkspaceGraphNodeContext(
                    id=node.id,
                    kind=node.kind,
                    name=node.name,
                    qualified_name=node.qualified_name,
                    line=node.line,
                    granularity=node.granularity,
                )
            for edge in analysis.graph.edges[:40]:
                edges[edge.id] = WorkspaceGraphEdgeContext(
                    source=edge.source,
                    target=edge.target,
                    relation=edge.relation,
                    confidence=edge.confidence,
                )

        return WorkspaceContext(
            workspace_id=analysis.workspace.id,
            summary=analysis.context_summary(),
            knowledge=tuple(item.statement for item in analysis.knowledge.items[:10]),
            graph_nodes=tuple(nodes.values()),
            graph_edges=tuple(edges.values()),
            stale_knowledge_ids=analysis.stale_knowledge_ids,
        )

    @staticmethod
    def _message_tokens(content: str) -> tuple[str, ...]:
        import re

        tokens = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", content.casefold())
        stopwords = {"the", "a", "an", "is", "are", "in", "of", "and"}
        return tuple(token for token in tokens if token not in stopwords)[:8]

    async def _persist_context(
        self,
        session: Session,
        history: Sequence,
        memory: Any,
    ) -> None:
        """Land the composed context in its lanes when the six-lane fan-out is on.

        One :class:`~Sprout.storage.contracts.context.ContextRecord` per turn:
        the durable authority (SQLite/JSONL), the Redis hot copy, the Milvus
        snapshot vector, the Neo4j projection, and the blobstore for oversized
        bodies. The rendered memory block also warms the Redis prefix cache.
        """
        lanes = getattr(self._storage, "lanes", None)
        if lanes is None:
            return
        from Sprout.memory.snapshot import render_snapshot
        from Sprout.storage.contracts.context import ContextRecord

        snapshot = render_snapshot(memory, header=f"session {session.id}")
        record = ContextRecord(
            session_id=session.id,
            snapshot_hash=snapshot.hash,
            text=snapshot.text,
            turn_seq=history[-1].seq if history else 0,
            token_estimate=max(len(snapshot.text) // 4, 1),
        )
        await lanes.persist_context(record)
        await lanes.cache_memory_block(session.id, snapshot.text, snapshot.hash)

    def build_node_context(
        self,
        *,
        user_id: str,
        node_id: str,
        tools: Mapping[str, Tool] | None = None,
        skills: Mapping[str, Skill] | None = None,
        knowledge: Sequence[KnowledgeItem] = (),
        files: tuple[str, ...] = (),
        memory: Sequence[Any] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> AgentContext:
        """Build the minimal context for one ExecutionNode.

        A node context carries only what that node needs: its own resources,
        its own tools, and no inherited conversation history (spec 7.2). The
        session object is synthetic and never persisted, so node execution does
        not pollute the online session store.
        """
        return AgentContext(
            session=Session(id=f"node-{node_id}", user_id=user_id),
            memory=memory,
            knowledge=knowledge,
            tools=dict(tools or {}),
            skills=dict(skills or {}),
            user={"id": user_id},
            files=files,
            metadata={"node_id": node_id, **(dict(metadata or {}))},
        )
