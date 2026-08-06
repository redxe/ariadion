from __future__ import annotations

from typing import NewType, TypeAlias


ProgramId = NewType("ProgramId", str)
SnapshotOperationId = NewType("SnapshotOperationId", str)
SourceOperationId = NewType("SourceOperationId", str)
# Snapshot-scoped identity assigned to a native source AST node by a parser.
SyntaxNodeId = NewType("SyntaxNodeId", str)
SourceNodeId = NewType("SourceNodeId", str)
# Pre-allocation identities assigned by resolved quantum semantics.
LogicalQubitId = NewType("LogicalQubitId", str)
LogicalOperationId = NewType("LogicalOperationId", str)
ClassicalBitId = NewType("ClassicalBitId", str)
IrOperationId = NewType("IrOperationId", str)

# Compatibility alias for the pre-v0.1 identity contract. New code should choose
# either a snapshot-local operation ID or a frontend-supplied durable node ID.
OperationId: TypeAlias = SnapshotOperationId
SourceIdentity: TypeAlias = SourceOperationId | SourceNodeId


def require_nonempty_identifier(value: str, *, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
