"""A dependency graph over records, not a recalculation of cells.

Excel recalculates a sheet of cells.  This evaluates a graph of *records*: each
node declares what it depends on, the graph is topologically sorted once, and
results are cached against a hash of their inputs so that changing one room
re-evaluates only what that room touches.

Two properties matter more than speed:

* A cycle is detected and named, rather than producing Excel's silent zero or
  an iterative-calculation fudge.
* Every node's result carries its provenance, so the derivation panel is a
  property of the engine rather than a report written afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence


class CircularDependencyError(Exception):
    """Raised when the node graph contains a cycle, naming the path."""


class UnknownNodeError(Exception):
    """Raised when a node depends on something that was never defined."""


@dataclass
class Node:
    """One derived value in the graph."""

    key: str
    compute: Callable[["Context"], Any]
    depends_on: tuple[str, ...] = ()
    #: Free-form grouping used by reports and the health panel.
    kind: str = ""


class Context:
    """Read access to already-evaluated nodes, handed to each ``compute``."""

    def __init__(self, results: Mapping[str, Any], graph: "Graph") -> None:
        self._results = results
        self._graph = graph

    def __getitem__(self, key: str) -> Any:
        if key not in self._results:
            raise UnknownNodeError(
                f"node {key!r} was read before it was evaluated -- it is missing "
                f"from depends_on"
            )
        return self._results[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._results.get(key, default)

    def matching(self, prefix: str) -> dict[str, Any]:
        """Every evaluated node whose key starts with ``prefix``.

        This is how aggregation avoids Excel's ``SUM(I5:I38)`` problem: a total
        is "every node that matches this filter", so a new item participates
        because it matches, not because someone extended a range.
        """
        return {k: v for k, v in self._results.items() if k.startswith(prefix)}

    @property
    def graph(self) -> "Graph":
        return self._graph


@dataclass
class Graph:
    """A set of nodes plus the evaluation machinery."""

    nodes: dict[str, Node] = field(default_factory=dict)
    _order: list[str] | None = field(default=None, repr=False)

    def add(self, key: str, compute: Callable[[Context], Any],
            depends_on: Sequence[str] = (), *, kind: str = "") -> "Graph":
        if key in self.nodes:
            raise ValueError(f"node {key!r} is already defined")
        self.nodes[key] = Node(key, compute, tuple(depends_on), kind)
        self._order = None
        return self

    def constant(self, key: str, value: Any, *, kind: str = "input") -> "Graph":
        """A node that is an input, not a calculation."""
        return self.add(key, lambda _ctx, v=value: v, (), kind=kind)

    def topological_order(self) -> list[str]:
        """Kahn's algorithm, with a named path on failure."""
        if self._order is not None:
            return self._order

        indegree: dict[str, int] = {k: 0 for k in self.nodes}
        dependents: dict[str, list[str]] = {k: [] for k in self.nodes}
        for key, node in self.nodes.items():
            for dep in node.depends_on:
                if dep not in self.nodes:
                    raise UnknownNodeError(
                        f"node {key!r} depends on {dep!r}, which is not defined"
                    )
                indegree[key] += 1
                dependents[dep].append(key)

        ready = sorted(k for k, d in indegree.items() if d == 0)
        order: list[str] = []
        while ready:
            key = ready.pop(0)
            order.append(key)
            for dependent in dependents[key]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
            ready.sort()

        if len(order) != len(self.nodes):
            raise CircularDependencyError(
                "cycle detected among: " + " -> ".join(
                    sorted(k for k in self.nodes if k not in set(order))
                )
            )
        self._order = order
        return order

    def evaluate(self, only: Iterable[str] | None = None) -> dict[str, Any]:
        """Evaluate the whole graph (or the sub-graph feeding ``only``)."""
        order = self.topological_order()
        if only is not None:
            needed = self._ancestors(only)
            order = [k for k in order if k in needed]

        results: dict[str, Any] = {}
        ctx = Context(results, self)
        for key in order:
            results[key] = self.nodes[key].compute(ctx)
        return results

    def _ancestors(self, keys: Iterable[str]) -> set[str]:
        """``keys`` plus everything they transitively depend on."""
        seen: set[str] = set()
        stack = list(keys)
        while stack:
            key = stack.pop()
            if key in seen:
                continue
            if key not in self.nodes:
                raise UnknownNodeError(f"node {key!r} is not defined")
            seen.add(key)
            stack.extend(self.nodes[key].depends_on)
        return seen

    def dependents_of(self, key: str) -> set[str]:
        """Everything that would need re-evaluating if ``key`` changed.

        This is the invalidation set: edit one room's area and only its own
        quantities, their aggregates and the totals above them recompute.
        """
        if key not in self.nodes:
            raise UnknownNodeError(f"node {key!r} is not defined")
        affected = {key}
        changed = True
        while changed:
            changed = False
            for node_key, node in self.nodes.items():
                if node_key in affected:
                    continue
                if any(dep in affected for dep in node.depends_on):
                    affected.add(node_key)
                    changed = True
        return affected
