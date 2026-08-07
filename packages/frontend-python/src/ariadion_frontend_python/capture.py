from __future__ import annotations

import ast
import hashlib
import inspect
import json
import textwrap
from collections.abc import Callable
from dataclasses import dataclass, field
from math import isfinite, pi, tau
from typing import Never

from ariadion_core import (
    ClassicalBitId,
    LogicalOperationId,
    LogicalQubitId,
    ProgramId,
    SourceOperationId,
    SourceRange,
    SourceRef,
    require_nonempty_identifier,
)
from ariadion_language import (
    Basis,
    Qubit,
    basis as basis_namespace,
    cx,
    deg,
    h,
    rad,
    rx,
    ry,
    rz,
    turns,
    x,
    z,
)
from ariadion_semantics import (
    LogicalGateOpCode,
    LogicalGateOperation,
    LogicalProgram,
    LogicalQubitValue,
    LogicalRotationOperation,
    NoneReturn,
    Observation,
    ObservationReason,
    ObservationResultValue,
    QuantumParameter,
    ReturnValueKind,
    ReturnValueRef,
    RotationAxis,
    ScalarReturn,
    SemanticAngle,
    SemanticAngleUnit,
    TupleReturn,
)

from .diagnostics import FrontendDiagnostic, PythonFrontendError
from .source import (
    ExplicitSourceProvider,
    InspectSourceProvider,
    PythonFunctionSource,
    PythonSourceProvider,
    SourceUnavailableError,
)


PYTHON_FRONTEND_SCHEMA_VERSION = 1
_FUNCTION_METADATA_NAMES = frozenset(
    {"__name__", "__qualname__", "__module__", "__doc__", "__wrapped__"}
)
_MISSING = object()

_GATE_MARKERS = {
    h: LogicalGateOpCode.H,
    x: LogicalGateOpCode.X,
    z: LogicalGateOpCode.Z,
    cx: LogicalGateOpCode.CX,
}
_ROTATION_MARKERS = {
    rx: RotationAxis.X,
    ry: RotationAxis.Y,
    rz: RotationAxis.Z,
}
_ANGLE_MARKERS = {
    deg: SemanticAngleUnit.DEGREES,
    rad: SemanticAngleUnit.RADIANS,
    turns: SemanticAngleUnit.TURNS,
}


@dataclass(frozen=True, slots=True)
class QuantumFunctionConfig:
    """Immutable capture policy for one Python quantum function."""

    default_basis: Basis = basis_namespace.z
    program_id: ProgramId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.default_basis, Basis):
            raise ValueError("quantum function default_basis must be Basis")
        if self.program_id is not None:
            require_nonempty_identifier(self.program_id, label="quantum function program ID")


@dataclass(frozen=True, slots=True)
class QuantumFunction:
    """A lazily captured function that never calls its Python body to find semantics."""

    python_function: Callable[..., object]
    config: QuantumFunctionConfig
    source_provider: PythonSourceProvider = field(
        default_factory=InspectSourceProvider,
        repr=False,
        compare=False,
    )
    _capture_cache: dict[str, LogicalProgram] = field(
        default_factory=dict,
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not inspect.isfunction(self.python_function):
            raise ValueError("quantum function python_function must be a Python function")
        if not isinstance(self.config, QuantumFunctionConfig):
            raise ValueError("quantum function config must be QuantumFunctionConfig")
        if not callable(getattr(self.source_provider, "source_for", None)):
            raise ValueError("quantum function source_provider must define source_for")

    def __getattribute__(self, name: str) -> object:
        if name in _FUNCTION_METADATA_NAMES:
            function = object.__getattribute__(self, "python_function")
            if name == "__wrapped__":
                return function
            return getattr(function, name)
        return object.__getattribute__(self, name)

    def __call__(self, *args: object, **kwargs: object) -> Never:
        del args, kwargs
        raise RuntimeError(
            "Quantum functions are compiled rather than called as ordinary Python. "
            "Use ariadion.run(function) for a closed function."
        )

    def to_logical_program(self) -> LogicalProgram:
        fallback_program_id = self.config.program_id or _default_program_id(
            self.python_function.__module__ or "__main__",
            self.python_function.__qualname__,
        )
        try:
            source = self.source_provider.source_for(self.python_function)
        except SourceUnavailableError as error:
            raise PythonFrontendError(
                (
                    FrontendDiagnostic(
                        "P100",
                        str(error),
                        program_id=fallback_program_id,
                    ),
                )
            ) from error
        except Exception as error:
            raise PythonFrontendError(
                (
                    FrontendDiagnostic(
                        "P100",
                        "Python source is unavailable. Provide an ExplicitSourceProvider.",
                        program_id=fallback_program_id,
                    ),
                )
            ) from error
        if not isinstance(source, PythonFunctionSource):
            raise PythonFrontendError(
                (
                    FrontendDiagnostic(
                        "P100",
                        "Python source providers must return PythonFunctionSource.",
                        program_id=fallback_program_id,
                    ),
                )
            )

        program_id = self.config.program_id or _default_program_id(
            source.module_name,
            source.qualified_name,
        )
        fingerprint = _source_fingerprint(source, self.config, program_id)
        cached = self._capture_cache.get(fingerprint)
        if cached is not None:
            return cached

        try:
            program = _CaptureState(
                function=self.python_function,
                source=source,
                program_id=program_id,
                default_basis=self.config.default_basis,
            ).capture()
        except _CaptureAbort as error:
            raise PythonFrontendError((error.diagnostic,)) from None
        self._capture_cache[fingerprint] = program
        return program


def quantum(
    function: Callable[..., object] | None = None,
    *,
    basis: Basis = basis_namespace.z,
    program_id: ProgramId | None = None,
    source_provider: PythonSourceProvider | None = None,
) -> QuantumFunction | Callable[[Callable[..., object]], QuantumFunction]:
    """Mark a valid Python function for lazy AST capture without executing its body."""

    config = QuantumFunctionConfig(default_basis=basis, program_id=program_id)
    provider = source_provider or InspectSourceProvider()

    def decorate(target: Callable[..., object]) -> QuantumFunction:
        return QuantumFunction(target, config, provider)

    if function is None:
        return decorate
    if not callable(function):
        raise TypeError("@quantum expects a function or decorator keyword arguments")
    return decorate(function)


def capture_python_function(
    function: Callable[..., object],
    *,
    config: QuantumFunctionConfig | None = None,
    source_provider: PythonSourceProvider | None = None,
) -> LogicalProgram:
    """Capture a function through an explicit provider boundary for IDEs and tests."""

    return QuantumFunction(
        function,
        config or QuantumFunctionConfig(),
        source_provider or InspectSourceProvider(),
    ).to_logical_program()


def explicit_quantum_function(
    function: Callable[..., object],
    source: PythonFunctionSource,
    *,
    config: QuantumFunctionConfig | None = None,
) -> QuantumFunction:
    """Create a quantum wrapper backed by supplied text instead of file inspection."""

    return QuantumFunction(
        function,
        config or QuantumFunctionConfig(),
        ExplicitSourceProvider(source),
    )


@dataclass(frozen=True, slots=True)
class _ExpectedLeaf:
    kind: ReturnValueKind


@dataclass(frozen=True, slots=True)
class _ExpectedTuple:
    items: tuple[_ExpectedReturn, ...]


@dataclass(frozen=True, slots=True)
class _ExpectedNone:
    pass


_ExpectedReturn = _ExpectedLeaf | _ExpectedTuple | _ExpectedNone


class _CaptureAbort(Exception):
    def __init__(self, diagnostic: FrontendDiagnostic) -> None:
        self.diagnostic = diagnostic


class _CaptureState:
    def __init__(
        self,
        *,
        function: Callable[..., object],
        source: PythonFunctionSource,
        program_id: ProgramId,
        default_basis: Basis,
    ) -> None:
        self.function = function
        self.source = source
        self.program_id = program_id
        self.default_basis = default_basis
        self.globals = function.__globals__
        self._source_ordinals: dict[tuple[str, int, int], int] = {}
        self._bindings: dict[str, LogicalQubitValue] = {}
        self._qubits: list[LogicalQubitValue] = []
        self._parameters: list[QuantumParameter] = []
        self._instructions: list[
            LogicalGateOperation | LogicalRotationOperation | Observation
        ] = []
        self._classical_bits: list[ObservationResultValue] = []
        self._classical_return_qubit_ids: set[LogicalQubitId] = set()
        self._quantum_return_qubit_ids: set[LogicalQubitId] = set()
        self._dedented_text = textwrap.dedent(source.text)
        self._indent_width = _dedent_width(source.text, self._dedented_text)

    def capture(self) -> LogicalProgram:
        function_def = self._parse_function()
        expected_return = self._parse_return_annotation(function_def)
        self._capture_parameters(function_def)
        return_shape = self._capture_body(function_def, expected_return)
        try:
            return LogicalProgram(
                id=self.program_id,
                name=self.source.qualified_name,
                qubits=tuple(self._qubits),
                instructions=tuple(self._instructions),
                classical_bits=tuple(self._classical_bits),
                return_shape=return_shape,
                parameters=tuple(self._parameters),
            )
        except ValueError as error:
            self._fail(
                "P101",
                f"Resolved quantum function violates a semantic invariant: {error}",
                function_def,
            )

    def _parse_function(self) -> ast.FunctionDef:
        try:
            module = ast.parse(
                self._dedented_text,
                filename=self.source.file or f"<{self.source.qualified_name}>",
                mode="exec",
            )
        except SyntaxError as error:
            line = self.source.starting_line + (error.lineno or 1) - 1
            column = self._indent_width + (error.offset or 1)
            source_range = SourceRange(
                file=self.source.file,
                line=line,
                column=column,
                end_line=line,
                end_column=column,
            )
            self._raise_diagnostic(
                "P101",
                f"Python parser rejected the decorated function: {error.msg}",
                source_range,
            )

        matching = tuple(
            item
            for item in module.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == _source_function_name(self.source.qualified_name)
        )
        if len(matching) != 1:
            self._fail(
                "P101",
                "The supplied source must contain exactly one matching function definition.",
                module,
            )
        function_def = matching[0]
        if isinstance(function_def, ast.AsyncFunctionDef):
            self._fail("P101", "Async quantum functions are not supported.", function_def)
        return function_def

    def _capture_parameters(self, function_def: ast.FunctionDef) -> None:
        arguments = function_def.args
        if (
            arguments.posonlyargs
            or arguments.kwonlyargs
            or arguments.vararg is not None
            or arguments.kwarg is not None
            or arguments.defaults
            or any(default is not None for default in arguments.kw_defaults)
        ):
            self._fail(
                "P108",
                "Only flat positional Qubit parameters without defaults are supported.",
                function_def,
            )
        for position, argument in enumerate(arguments.args):
            if not _is_name(argument.annotation, "Qubit"):
                self._fail(
                    "P108",
                    "Quantum parameters must be annotated exactly as Qubit.",
                    argument.annotation or argument,
                )
            source = self._source_for(argument, "parameter")
            logical_qubit_id = LogicalQubitId(f"{source.source_operation_id}:qubit")
            value = LogicalQubitValue(logical_qubit_id, argument.arg, source)
            self._declare_value(argument.arg, value, argument)
            self._parameters.append(
                QuantumParameter(argument.arg, position, logical_qubit_id, source)
            )

    def _parse_return_annotation(self, function_def: ast.FunctionDef) -> _ExpectedReturn:
        if function_def.returns is None:
            self._fail(
                "P111",
                "Quantum functions require an explicit return annotation.",
                function_def,
            )
        return self._parse_annotation(function_def.returns, allow_none=True)

    def _parse_annotation(self, node: ast.expr, *, allow_none: bool) -> _ExpectedReturn:
        if isinstance(node, ast.Constant) and node.value is None:
            if allow_none:
                return _ExpectedNone()
            self._fail(
                "P109",
                "None is only supported as the whole-function return annotation.",
                node,
            )
        if _is_name(node, "Bit"):
            return _ExpectedLeaf(ReturnValueKind.CLASSICAL_BIT)
        if _is_name(node, "Qubit"):
            return _ExpectedLeaf(ReturnValueKind.QUANTUM_VALUE)
        if isinstance(node, ast.Subscript) and _is_name(node.value, "tuple"):
            items = _subscript_items(node.slice)
            if not items:
                self._fail("P109", "Tuple annotations must contain at least one item.", node)
            parsed_items = tuple(
                self._parse_annotation(item, allow_none=False)
                for item in items
            )
            return _ExpectedTuple(parsed_items)
        self._fail(
            "P109",
            "Supported annotations are None, Bit, Qubit, and nested built-in tuple forms.",
            node,
        )

    def _capture_body(
        self,
        function_def: ast.FunctionDef,
        expected_return: _ExpectedReturn,
    ) -> ScalarReturn | TupleReturn | NoneReturn:
        statements = list(function_def.body)
        if statements and _is_docstring(statements[0]):
            statements.pop(0)
        return_statement: ast.Return | None = None
        for index, statement in enumerate(statements):
            if isinstance(statement, ast.Assign):
                if return_statement is not None:
                    self._fail("P101", "Return must be the terminal statement.", statement)
                self._capture_assignment(statement)
            elif isinstance(statement, ast.Expr):
                if return_statement is not None:
                    self._fail("P101", "Return must be the terminal statement.", statement)
                self._capture_call_statement(statement)
            elif isinstance(statement, ast.Return):
                if return_statement is not None or index != len(statements) - 1:
                    self._fail(
                        "P101",
                        "Only one terminal return statement is supported.",
                        statement,
                    )
                return_statement = statement
            else:
                self._fail(
                    "P102",
                    f"Unsupported statement in @quantum function: {type(statement).__name__}.",
                    statement,
                )

        if return_statement is None:
            if isinstance(expected_return, _ExpectedNone):
                return NoneReturn()
            self._fail(
                "P110",
                "The return annotation requires a terminal return expression.",
                function_def,
            )
        return self._align_return(expected_return, return_statement.value, return_statement)

    def _capture_assignment(self, statement: ast.Assign) -> None:
        if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
            self._fail(
                "P101",
                "Only one simple name target is supported for quantum assignments.",
                statement,
            )
        target = statement.targets[0]
        if target.id in _known_intrinsic_names() or target.id in {"Qubit", "Bit"}:
            self._fail("P103", "Intrinsic names cannot be rebound inside @quantum.", target)
        if target.id in self._bindings:
            self._fail("P107", f"Reassignment of `{target.id}` is not supported.", target)

        if isinstance(statement.value, ast.Name):
            source_value = self._bindings.get(statement.value.id)
            if source_value is None:
                self._fail(
                    "P106",
                    f"Unknown quantum value `{statement.value.id}` in alias assignment.",
                    statement.value,
                )
            self._bindings[target.id] = source_value
            return
        if not isinstance(statement.value, ast.Call):
            self._fail(
                "P103",
                "Assignments may only create Qubit() values or aliases.",
                statement.value,
            )
        self._capture_qubit_declaration(target, statement.value)

    def _capture_qubit_declaration(self, target: ast.Name, call: ast.Call) -> None:
        marker = self._resolve_call_marker(call.func, (Qubit,), "Qubit constructor")
        if marker is not Qubit:  # pragma: no cover - guarded by _resolve_call_marker
            self._fail("P103", "Only Qubit() declarations are supported.", call)
        if call.args or call.keywords:
            self._fail("P105", "Qubit() does not accept arguments in @quantum functions.", call)
        source = self._source_for(call, "qubit-declaration")
        logical_qubit_id = LogicalQubitId(f"{source.source_operation_id}:qubit")
        value = LogicalQubitValue(logical_qubit_id, target.id, source)
        self._declare_value(target.id, value, target)

    def _capture_call_statement(self, statement: ast.Expr) -> None:
        if not isinstance(statement.value, ast.Call):
            self._fail(
                "P102",
                "Only supported intrinsic calls may be expression statements.",
                statement,
            )
        call = statement.value
        marker = self._resolve_call_marker(
            call.func,
            tuple(_GATE_MARKERS) + tuple(_ROTATION_MARKERS),
            "quantum intrinsic",
        )
        if marker in _GATE_MARKERS:
            self._capture_gate(call, _GATE_MARKERS[marker])
            return
        self._capture_rotation(call, _ROTATION_MARKERS[marker])

    def _capture_gate(self, call: ast.Call, opcode: LogicalGateOpCode) -> None:
        if call.keywords:
            self._fail("P105", "Quantum intrinsics do not accept keyword arguments.", call)
        expected_arity = 2 if opcode is LogicalGateOpCode.CX else 1
        if len(call.args) != expected_arity:
            self._fail(
                "P105",
                f"{opcode.value} expects exactly {expected_arity} quantum argument(s).",
                call,
            )
        values = tuple(self._bound_qubit(argument) for argument in call.args)
        source = self._source_for(call, f"gate-{opcode.value}")
        operation_id = LogicalOperationId(f"{source.source_operation_id}:operation")
        if opcode is LogicalGateOpCode.CX:
            control, target = values
            if control.id == target.id:
                self._fail(
                    "P105",
                    "cx requires distinct control and target quantum values.",
                    call,
                )
            self._instructions.append(
                LogicalGateOperation(operation_id, opcode, (target.id,), (control.id,), source)
            )
            return
        self._instructions.append(
            LogicalGateOperation(operation_id, opcode, (values[0].id,), source=source)
        )

    def _capture_rotation(self, call: ast.Call, axis: RotationAxis) -> None:
        if call.keywords or len(call.args) != 2:
            self._fail(
                "P105",
                f"r{axis.value} expects one quantum argument and one explicit angle.",
                call,
            )
        target = self._bound_qubit(call.args[0])
        angle = self._parse_angle(call.args[1])
        source = self._source_for(call, f"rotation-{axis.value}")
        operation_id = LogicalOperationId(f"{source.source_operation_id}:operation")
        self._instructions.append(
            LogicalRotationOperation(operation_id, axis, target.id, angle, source)
        )

    def _parse_angle(self, node: ast.expr) -> SemanticAngle:
        if not isinstance(node, ast.Call) or node.keywords or len(node.args) != 1:
            self._fail(
                "P112",
                "Rotations require deg(...), rad(...), or turns(...) with one numeric literal.",
                node,
            )
        marker = self._resolve_call_marker(
            node.func,
            tuple(_ANGLE_MARKERS),
            "angle constructor",
            code="P112",
        )
        source_value = _numeric_literal(node.args[0])
        if source_value is None or not isfinite(source_value):
            self._fail(
                "P112",
                "Rotation angles require one finite numeric literal.",
                node.args[0],
            )
        unit = _ANGLE_MARKERS[marker]
        radians = source_value * {
            SemanticAngleUnit.DEGREES: pi / 180,
            SemanticAngleUnit.RADIANS: 1.0,
            SemanticAngleUnit.TURNS: tau,
        }[unit]
        if not isfinite(radians):
            self._fail(
                "P112",
                "Rotation angles must produce finite canonical radians.",
                node.args[0],
            )
        return SemanticAngle(source_value, unit, radians)

    def _align_return(
        self,
        expected: _ExpectedReturn,
        expression: ast.expr | None,
        statement: ast.Return,
    ) -> ScalarReturn | TupleReturn | NoneReturn:
        if isinstance(expected, _ExpectedNone):
            if expression is None or (
                isinstance(expression, ast.Constant) and expression.value is None
            ):
                return NoneReturn()
            self._fail(
                "P110",
                "The None return annotation requires `return` or `return None`.",
                expression,
            )
        if isinstance(expected, _ExpectedTuple):
            if not isinstance(expression, ast.Tuple):
                self._fail(
                    "P110",
                    "The return expression must match the annotated tuple shape.",
                    expression or statement,
                )
            if len(expression.elts) != len(expected.items):
                self._fail(
                    "P110",
                    "The returned tuple arity does not match its annotation.",
                    expression,
                )
            return TupleReturn(
                tuple(
                    self._align_return(item, value, statement)
                    for item, value in zip(expected.items, expression.elts, strict=True)
                )
            )
        if not isinstance(expression, ast.Name):
            self._fail(
                "P110",
                "Scalar quantum returns must be bound quantum value names.",
                expression or statement,
            )
        value = self._bindings.get(expression.id)
        if value is None:
            self._fail("P106", f"Unknown quantum value `{expression.id}` in return.", expression)
        if expected.kind is ReturnValueKind.QUANTUM_VALUE:
            if value.id in self._classical_return_qubit_ids:
                self._fail(
                    "P110",
                    "A quantum value cannot be returned as both Bit and Qubit.",
                    expression,
                )
            self._quantum_return_qubit_ids.add(value.id)
            return ScalarReturn(ReturnValueRef(ReturnValueKind.QUANTUM_VALUE, value.id))
        if value.id in self._quantum_return_qubit_ids:
            self._fail(
                "P110",
                "A quantum value cannot be returned as both Bit and Qubit.",
                expression,
            )
        self._classical_return_qubit_ids.add(value.id)
        result_source = self._source_for(expression, "observation-result")
        result_id = ClassicalBitId(f"{result_source.source_operation_id}:classical-bit")
        display_name = f"{value.display_name or expression.id}_result"
        result = ObservationResultValue(result_id, display_name, result_source)
        observation_source = self._source_for(expression, "inferred-observation")
        observation = Observation(
            LogicalOperationId(f"{observation_source.source_operation_id}:operation"),
            value.id,
            result_id,
            self.default_basis,
            ObservationReason.CLASSICAL_RETURN,
            observation_source,
        )
        self._classical_bits.append(result)
        self._instructions.append(observation)
        return ScalarReturn(ReturnValueRef(ReturnValueKind.CLASSICAL_BIT, result_id))

    def _declare_value(
        self,
        name: str,
        value: LogicalQubitValue,
        node: ast.AST,
    ) -> None:
        if name in self._bindings:
            self._fail("P107", f"Reassignment of `{name}` is not supported.", node)
        self._bindings[name] = value
        self._qubits.append(value)

    def _bound_qubit(self, node: ast.expr) -> LogicalQubitValue:
        if not isinstance(node, ast.Name):
            self._fail(
                "P106",
                "Quantum intrinsic arguments must be bound quantum value names.",
                node,
            )
        value = self._bindings.get(node.id)
        if value is None:
            self._fail("P106", f"Unknown quantum value `{node.id}`.", node)
        return value

    def _resolve_call_marker(
        self,
        function: ast.expr,
        supported: tuple[object, ...],
        label: str,
        *,
        code: str = "P103",
    ) -> object:
        if not isinstance(function, ast.Name):
            self._fail(code, f"Only named {label} calls are supported.", function)
        if function.id in self._bindings:
            self._fail(
                "P104",
                f"`{function.id}` is locally shadowed and is not an intrinsic.",
                function,
            )
        resolved = self.globals.get(function.id, _MISSING)
        for marker in supported:
            if resolved is marker:
                return marker
        known_names = {_callable_name(marker) for marker in supported}
        if function.id in known_names:
            self._fail(
                "P104",
                f"`{function.id}` does not resolve to the Ariadion {label}.",
                function,
            )
        self._fail("P103", f"Unsupported call `{function.id}` in @quantum function.", function)

    def _source_for(self, node: ast.AST, kind: str) -> SourceRef:
        source_range = self._range_for(node)
        line = (
            source_range.line
            if source_range is not None and source_range.line is not None
            else 0
        )
        column = (
            source_range.column
            if source_range is not None and source_range.column is not None
            else 0
        )
        key = (kind, line, column)
        ordinal = self._source_ordinals.get(key, 0)
        self._source_ordinals[key] = ordinal + 1
        source_operation_id = SourceOperationId(
            f"{self.program_id}:python:{kind}:{line}:{column}:{ordinal}"
        )
        return SourceRef.from_range(
            program_id=self.program_id,
            source_range=source_range,
            source_operation_id=source_operation_id,
        )

    def _range_for(self, node: ast.AST) -> SourceRange | None:
        line = getattr(node, "lineno", None)
        column = getattr(node, "col_offset", None)
        if line is None or column is None:
            return None
        end_line = getattr(node, "end_lineno", line)
        end_column = getattr(node, "end_col_offset", column)
        return SourceRange(
            file=self.source.file,
            line=self.source.starting_line + line - 1,
            column=self._indent_width + column + 1,
            end_line=self.source.starting_line + end_line - 1,
            end_column=self._indent_width + end_column + 1,
        )

    def _fail(self, code: str, message: str, node: ast.AST) -> Never:
        self._raise_diagnostic(code, message, self._range_for(node))

    def _raise_diagnostic(
        self,
        code: str,
        message: str,
        source_range: SourceRange | None,
    ) -> Never:
        raise _CaptureAbort(
            FrontendDiagnostic(
                code,
                message,
                source_range=source_range,
                program_id=self.program_id,
            )
        )


def _default_program_id(module_name: str, qualified_name: str) -> ProgramId:
    return ProgramId(f"python:{module_name}:{qualified_name}")


def _source_function_name(qualified_name: str) -> str:
    """Return the terminal source function name from a qualified name."""

    return qualified_name.rsplit(".", 1)[-1]


def _source_fingerprint(
    source: PythonFunctionSource,
    config: QuantumFunctionConfig,
    program_id: ProgramId,
) -> str:
    normalized_text = "\n".join(
        line.rstrip() for line in textwrap.dedent(source.text).strip().splitlines()
    )
    payload = {
        "default_basis": config.default_basis.name,
        "file": source.file,
        "frontend_schema_version": PYTHON_FRONTEND_SCHEMA_VERSION,
        "module_name": source.module_name,
        "program_id": program_id,
        "qualified_name": source.qualified_name,
        "starting_line": source.starting_line,
        "text": normalized_text,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _dedent_width(original: str, dedented: str) -> int:
    for before, after in zip(original.splitlines(), dedented.splitlines(), strict=False):
        if before.strip() and after.strip():
            return max(0, len(before) - len(after))
    return 0


def _is_name(node: ast.AST | None, expected: str) -> bool:
    return isinstance(node, ast.Name) and node.id == expected


def _is_docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _subscript_items(node: ast.expr) -> tuple[ast.expr, ...]:
    if isinstance(node, ast.Tuple):
        return tuple(node.elts)
    return (node,)


def _numeric_literal(node: ast.expr) -> float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        if isinstance(node.value, bool):
            return None
        try:
            return float(node.value)
        except OverflowError:
            return None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        value = _numeric_literal(node.operand)
        return -value if value is not None else None
    return None


def _callable_name(marker: object) -> str:
    name = getattr(marker, "name", None)
    if isinstance(name, str):
        return name
    return getattr(marker, "__name__", "")


def _known_intrinsic_names() -> frozenset[str]:
    return frozenset(
        _callable_name(marker)
        for marker in tuple(_GATE_MARKERS) + tuple(_ROTATION_MARKERS) + tuple(_ANGLE_MARKERS)
    )
