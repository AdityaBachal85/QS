"""Provenance: every derived value records what produced it.

Section H.3 of the brief asks for a derivation panel -- click any grey number
and see where it came from.  That is only possible if the engine records it at
the moment of calculation, so provenance is part of the result type rather than
something reconstructed later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass(frozen=True)
class Input:
    """One named input to a calculation, with its value and where it came from."""

    name: str
    value: Any
    source: str = ""

    def __str__(self) -> str:
        val = f"{self.value:,.4f}" if isinstance(self.value, (int, float)) else str(self.value)
        return f"{self.name} = {val}" + (f"  [{self.source}]" if self.source else "")


@dataclass(frozen=True)
class Derivation:
    """How a single derived value was produced."""

    rule: str
    expression: str
    inputs: tuple[Input, ...] = ()
    #: The originating workbook cell, when this value was imported or is being
    #: reconciled against one.  Lets any figure be traced to ``Flat Sizes!D12``.
    excel_ref: str = ""
    note: str = ""

    def explain(self) -> str:
        lines = [f"{self.rule}: {self.expression}"]
        lines.extend(f"    {i}" for i in self.inputs)
        if self.excel_ref:
            lines.append(f"    source cell: {self.excel_ref}")
        if self.note:
            lines.append(f"    note: {self.note}")
        return "\n".join(lines)


@dataclass(frozen=True)
class Derived:
    """A value together with its derivation.  The engine's unit of output."""

    value: Any
    derivation: Derivation

    def __str__(self) -> str:
        val = f"{self.value:,.4f}" if isinstance(self.value, (int, float)) else str(self.value)
        return val


def derive(value: Any, rule: str, expression: str,
           inputs: Sequence[Input] = (), *, excel_ref: str = "", note: str = "") -> Derived:
    return Derived(value, Derivation(rule, expression, tuple(inputs),
                                     excel_ref=excel_ref, note=note))
