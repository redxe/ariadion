from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ariadion_core import ProgramId, SourceRange, canonical_json, require_nonempty_identifier


class FrontendDiagnosticSeverity(str, Enum):
    """The severity of a source-linked Python frontend diagnostic."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class FrontendDiagnostic:
    """One structured failure while resolving valid Python into logical semantics."""

    code: str
    message: str
    severity: FrontendDiagnosticSeverity = FrontendDiagnosticSeverity.ERROR
    source_range: SourceRange | None = None
    program_id: ProgramId | None = None

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.code, label="frontend diagnostic code")
        require_nonempty_identifier(self.message, label="frontend diagnostic message")
        if not isinstance(self.severity, FrontendDiagnosticSeverity):
            raise ValueError("frontend diagnostic severity must be a FrontendDiagnosticSeverity")
        if self.source_range is not None and not isinstance(self.source_range, SourceRange):
            raise ValueError("frontend diagnostic source_range must be SourceRange")
        if self.program_id is not None:
            require_nonempty_identifier(self.program_id, label="frontend diagnostic program ID")

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "source_range": (
                self.source_range.to_dict() if self.source_range is not None else None
            ),
            "program_id": self.program_id,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


class PythonFrontendError(ValueError):
    """Raised when Python source cannot be safely captured into `LogicalProgram`."""

    def __init__(self, diagnostics: tuple[FrontendDiagnostic, ...]) -> None:
        if not diagnostics:
            raise ValueError("Python frontend errors require at least one diagnostic")
        self.diagnostics = diagnostics
        super().__init__("; ".join(f"{item.code} {item.message}" for item in diagnostics))
