from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ariadion_core import require_nonempty_identifier


@dataclass(frozen=True, slots=True)
class PythonFunctionSource:
    """The exact Python text and origin facts supplied to the frontend."""

    text: str
    file: str | None
    starting_line: int
    module_name: str
    qualified_name: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("Python function source text must be non-empty")
        if isinstance(self.starting_line, bool) or not isinstance(self.starting_line, int):
            raise ValueError("Python function source starting_line must be an integer")
        if self.starting_line < 1:
            raise ValueError("Python function source starting_line must be one-based")
        if self.file is not None:
            require_nonempty_identifier(self.file, label="Python function source file")
        require_nonempty_identifier(self.module_name, label="Python function source module")
        require_nonempty_identifier(
            self.qualified_name,
            label="Python function source qualified name",
        )


class PythonSourceProvider(Protocol):
    """A source boundary that can later be satisfied by an IDE buffer."""

    def source_for(self, function: Callable[..., object]) -> PythonFunctionSource:
        """Return source text without calling the function body."""


class SourceUnavailableError(ValueError):
    """Internal source-provider failure normalized to frontend diagnostic `P100`."""


@dataclass(frozen=True, slots=True)
class InspectSourceProvider:
    """Read ordinary file-backed function source through Python inspection."""

    def source_for(self, function: Callable[..., object]) -> PythonFunctionSource:
        try:
            lines, starting_line = inspect.getsourcelines(function)
            file = inspect.getsourcefile(function) or inspect.getfile(function)
        except (OSError, IOError, TypeError) as error:
            raise SourceUnavailableError(
                "Python source is unavailable. Interactive definitions, dynamically generated "
                "functions, stripped source distributions, and some notebook environments "
                "require an ExplicitSourceProvider."
            ) from error
        return PythonFunctionSource(
            text="".join(lines),
            file=file,
            starting_line=starting_line,
            module_name=function.__module__ or "__main__",
            qualified_name=function.__qualname__,
        )


@dataclass(frozen=True, slots=True)
class ExplicitSourceProvider:
    """Use caller-supplied source, including an unsaved editor buffer, deterministically."""

    source: PythonFunctionSource

    def source_for(self, function: Callable[..., object]) -> PythonFunctionSource:
        del function
        return self.source
