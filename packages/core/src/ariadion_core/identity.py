from __future__ import annotations

from typing import NewType, TypeAlias


ProgramId = NewType("ProgramId", str)
SnapshotOperationId = NewType("SnapshotOperationId", str)
SourceNodeId = NewType("SourceNodeId", str)
IrOperationId = NewType("IrOperationId", str)

# Compatibility alias for the pre-v0.1 identity contract. New code should choose
# either a snapshot-local operation ID or a frontend-supplied durable node ID.
OperationId: TypeAlias = SnapshotOperationId
SourceIdentity: TypeAlias = SnapshotOperationId | SourceNodeId


def require_nonempty_identifier(value: str, *, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
