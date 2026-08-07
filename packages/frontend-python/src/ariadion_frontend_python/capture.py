from __future__ import annotations

import ast
import builtins
import inspect
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
    Bit,
    Qubit,
    basis as basis_namespace,
    cx,
    deg,
    h,
    observe,
    rad,
    reset,
    rx,
    ry,
    rz,
    turns,
    x,
    z,
)
from ariadion_semantics import (
    LogicalCallOperation,
    LogicalGateOpCode,
    LogicalGateOperation,
    LogicalModule,
    LogicalProgram,
    LogicalQubitValue,
    LogicalResetOperation,
    LogicalRotationOperation,
    NoneReturn,
    Observation,
    ObservationReason,
    ObservationResultValue,
    QuantumArgumentBinding,
    QuantumCallResult,
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
_OBSERVATION_MARKERS = frozenset({observe})
_RESET_MARKERS = frozenset({reset})
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
        """Capture current source and bindings without retaining stale semantic state."""

        context = _CaptureContext()
        try:
            return context.capture(self)
        except _CaptureAbort as error:
            raise PythonFrontendError((error.diagnostic,)) from None

    def to_logical_module(self) -> LogicalModule:
        """Capture one resolved, acyclic module rooted at this quantum function."""

        context = _CaptureContext()
        try:
            entry_program = context.capture(self)
            return LogicalModule(entry_program.id, context.programs)
        except _CaptureAbort as error:
            raise PythonFrontendError((error.diagnostic,)) from None
        except ValueError as error:
            raise PythonFrontendError(
                (
                    FrontendDiagnostic(
                        "P101",
                        f"Resolved quantum function violates a semantic invariant: {error}",
                        program_id=self.config.program_id,
                    ),
                )
            ) from None

    def _source_and_program_id(self) -> tuple[PythonFunctionSource, ProgramId]:
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
        return source, program_id


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


@dataclass(frozen=True, slots=True)
class _QuantumCallResultBinding:
    """A source-level name that aliases a scalar quantum call result."""

    id: LogicalQubitId
    display_name: str


_BoundQuantumValue = LogicalQubitValue | _QuantumCallResultBinding
_BoundValue = _BoundQuantumValue | ObservationResultValue


class _CaptureAbort(Exception):
    def __init__(self, diagnostic: FrontendDiagnostic) -> None:
        self.diagnostic = diagnostic


class _CaptureContext:
    """One deterministic capture traversal over the currently resolved globals."""

    def __init__(self) -> None:
        self._programs_by_id: dict[ProgramId, LogicalProgram] = {}
        self._functions_by_program_id: dict[ProgramId, QuantumFunction] = {}
        self._programs_in_capture_order: list[LogicalProgram] = []
        self._active_functions_by_program_id: dict[ProgramId, QuantumFunction] = {}

    @property
    def programs(self) -> tuple[LogicalProgram, ...]:
        return tuple(self._programs_in_capture_order)

    def capture(
        self,
        function: QuantumFunction,
        *,
        invocation_source: SourceRef | None = None,
    ) -> LogicalProgram:
        source, program_id = function._source_and_program_id()
        active_function = self._active_functions_by_program_id.get(program_id)
        if active_function is function:
            raise _CaptureAbort(
                FrontendDiagnostic(
                    "P115",
                    "Recursive quantum call graphs are not supported.",
                    source_range=(
                        invocation_source.source_range
                        if invocation_source is not None
                        else None
                    ),
                    program_id=(
                        invocation_source.program_id
                        if invocation_source is not None
                        else program_id
                    ),
                )
            )
        if active_function is not None:
            raise _CaptureAbort(
                self._program_id_collision_diagnostic(program_id, invocation_source)
            )
        existing = self._programs_by_id.get(program_id)
        if existing is not None:
            if self._functions_by_program_id[program_id] is not function:
                raise _CaptureAbort(
                    self._program_id_collision_diagnostic(program_id, invocation_source)
                )
            return existing

        self._active_functions_by_program_id[program_id] = function
        try:
            program = _CaptureState(
                function=function.python_function,
                source=source,
                program_id=program_id,
                default_basis=function.config.default_basis,
                capture_context=self,
            ).capture()
        finally:
            del self._active_functions_by_program_id[program_id]
        self._programs_by_id[program_id] = program
        self._functions_by_program_id[program_id] = function
        self._programs_in_capture_order.append(program)
        return program

    @staticmethod
    def _program_id_collision_diagnostic(
        program_id: ProgramId,
        invocation_source: SourceRef | None,
    ) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            "P117",
            "Distinct quantum functions cannot share a logical program ID.",
            source_range=(
                invocation_source.source_range if invocation_source is not None else None
            ),
            program_id=(
                invocation_source.program_id if invocation_source is not None else program_id
            ),
        )


class _CaptureState:
    def __init__(
        self,
        *,
        function: Callable[..., object],
        source: PythonFunctionSource,
        program_id: ProgramId,
        default_basis: Basis,
        capture_context: _CaptureContext,
    ) -> None:
        self.function = function
        self.source = source
        self.program_id = program_id
        self.default_basis = default_basis
        self.capture_context = capture_context
        self.globals = function.__globals__
        self._source_ordinals: dict[tuple[str, int, int], int] = {}
        self._quantum_bindings: dict[str, _BoundQuantumValue] = {}
        self._observation_bindings: dict[str, ObservationResultValue] = {}
        self._qubits: list[LogicalQubitValue] = []
        self._parameters: list[QuantumParameter] = []
        self._instructions: list[
            LogicalGateOperation
            | LogicalRotationOperation
            | LogicalResetOperation
            | Observation
            | LogicalCallOperation
        ] = []
        self._classical_bits: list[ObservationResultValue] = []
        self._classical_return_qubit_ids: set[LogicalQubitId] = set()
        self._quantum_return_qubit_ids: set[LogicalQubitId] = set()
        self._dedented_text = textwrap.dedent(source.text)
        self._indent_width = _dedent_width(source.text, self._dedented_text)

    def capture(self) -> LogicalProgram:
        function_def = self._parse_function()
        self._reject_closure(function_def)
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

    def _reject_closure(self, function_def: ast.FunctionDef) -> None:
        if self.function.__code__.co_freevars:
            self._fail(
                "P114",
                "Quantum functions with free-variable closure state are not supported.",
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
            if not self._annotation_resolves_to(argument.annotation, "Qubit", Qubit):
                self._fail(
                    "P108",
                    "Quantum parameters must be annotated exactly as the Ariadion Qubit class.",
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
        if self._annotation_resolves_to(node, "Bit", Bit):
            return _ExpectedLeaf(ReturnValueKind.CLASSICAL_BIT)
        if self._annotation_resolves_to(node, "Qubit", Qubit):
            return _ExpectedLeaf(ReturnValueKind.QUANTUM_VALUE)
        if (
            isinstance(node, ast.Subscript)
            and self._annotation_resolves_to(node.value, "tuple", builtins.tuple)
        ):
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

    def _annotation_resolves_to(
        self,
        node: ast.AST | None,
        name: str,
        expected: object,
    ) -> bool:
        return _is_name(node, name) and self._resolve_global_or_builtin_name(name) is expected

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
        if self._binding_for_name(target.id) is not None:
            self._fail("P107", f"Reassignment of `{target.id}` is not supported.", target)

        if isinstance(statement.value, ast.Name):
            source_value = self._binding_for_name(statement.value.id)
            if source_value is None:
                self._fail(
                    "P106",
                    f"Unknown managed value `{statement.value.id}` in alias assignment.",
                    statement.value,
                )
            if isinstance(source_value, ObservationResultValue):
                self._observation_bindings[target.id] = source_value
            else:
                self._quantum_bindings[target.id] = source_value
            return
        if not isinstance(statement.value, ast.Call):
            self._fail(
                "P103",
                "Assignments may only create Qubit() values, aliases, or scalar "
                "quantum call results.",
                statement.value,
            )
        if isinstance(statement.value.func, ast.Name):
            if self._binding_for_name(statement.value.func.id) is not None:
                self._fail(
                    "P104",
                    f"`{statement.value.func.id}` is locally shadowed and is not a quantum "
                    "callable.",
                    statement.value.func,
                )
            resolved = self._resolve_global_name(statement.value.func.id)
            if resolved is observe:
                self._capture_observation(statement.value, result_target=target)
                return
            if resolved is reset:
                self._fail(
                    "P105",
                    "reset does not return a value and must be an expression statement.",
                    statement.value,
                )
            if isinstance(resolved, QuantumFunction):
                self._capture_quantum_function_call(
                    statement.value,
                    resolved,
                    result_target=target,
                )
                return
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
        if not isinstance(call.func, ast.Name):
            self._fail("P103", "Only named quantum calls are supported.", call.func)
        if self._binding_for_name(call.func.id) is not None:
            self._fail(
                "P104",
                f"`{call.func.id}` is locally shadowed and is not a quantum callable.",
                call.func,
            )
        resolved = self._resolve_global_name(call.func.id)
        for marker, opcode in _GATE_MARKERS.items():
            if resolved is marker:
                self._capture_gate(call, opcode)
                return
        for marker, axis in _ROTATION_MARKERS.items():
            if resolved is marker:
                self._capture_rotation(call, axis)
                return
        if resolved is observe:
            self._capture_observation(call)
            return
        if resolved is reset:
            self._capture_reset(call)
            return
        if isinstance(resolved, QuantumFunction):
            self._capture_quantum_function_call(call, resolved)
            return
        known_intrinsics = (
            tuple(_GATE_MARKERS)
            + tuple(_ROTATION_MARKERS)
            + tuple(_OBSERVATION_MARKERS)
            + tuple(_RESET_MARKERS)
        )
        if call.func.id in {_callable_name(marker) for marker in known_intrinsics}:
            self._fail(
                "P104",
                f"`{call.func.id}` does not resolve to the Ariadion quantum intrinsic.",
                call.func,
            )
        self._fail("P103", f"Unsupported call `{call.func.id}` in @quantum function.", call.func)

    def _capture_quantum_function_call(
        self,
        call: ast.Call,
        callee_function: QuantumFunction,
        *,
        result_target: ast.Name | None = None,
    ) -> None:
        if call.keywords:
            self._fail("P105", "Quantum function calls do not accept keyword arguments.", call)
        source = self._source_for(call, "quantum-call")
        callee_program = self.capture_context.capture(
            callee_function,
            invocation_source=source,
        )
        if len(call.args) != len(callee_program.parameters):
            self._fail(
                "P105",
                "Quantum function call arity must match the callee quantum parameter count.",
                call,
            )
        values = tuple(self._bound_qubit(argument) for argument in call.args)
        self._validate_composed_callee(
            callee_program,
            call,
            expects_quantum_result=result_target is not None,
        )
        arguments = tuple(
            QuantumArgumentBinding(parameter.logical_qubit_id, value.id)
            for parameter, value in zip(callee_program.parameters, values, strict=True)
        )
        result = None
        if result_target is not None:
            assert isinstance(callee_program.return_shape, ScalarReturn)
            result_source = self._source_for(result_target, "quantum-call-result")
            result_value_id = LogicalQubitId(
                f"{source.source_operation_id}:call-result:qubit"
            )
            result = QuantumCallResult(
                caller_value_id=result_value_id,
                callee_value_id=LogicalQubitId(callee_program.return_shape.value.value_id),
                caller_binding_name=result_target.id,
                source=result_source,
            )
            self._quantum_bindings[result_target.id] = _QuantumCallResultBinding(
                id=result_value_id,
                display_name=result_target.id,
            )
        self._instructions.append(
            LogicalCallOperation(
                id=LogicalOperationId(f"{source.source_operation_id}:operation"),
                callee_program_id=callee_program.id,
                arguments=arguments,
                source=source,
                result=result,
            )
        )

    def _validate_composed_callee(
        self,
        callee_program: LogicalProgram,
        call: ast.Call,
        *,
        expects_quantum_result: bool,
    ) -> None:
        if any(isinstance(instruction, Observation) for instruction in callee_program.instructions):
            self._fail(
                "P116",
                "Composed quantum callees cannot contain observations.",
                call,
            )
        if expects_quantum_result:
            if (
                not isinstance(callee_program.return_shape, ScalarReturn)
                or callee_program.return_shape.value.kind is not ReturnValueKind.QUANTUM_VALUE
            ):
                self._fail(
                    "P116",
                    "Assigned quantum function calls require a scalar Qubit return.",
                    call,
                )
            return
        if not isinstance(callee_program.return_shape, NoneReturn):
            self._fail(
                "P116",
                "Quantum function calls with a return value must be assigned to one name; "
                "bare calls must return None.",
                call,
            )

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

    def _capture_observation(
        self,
        call: ast.Call,
        *,
        result_target: ast.Name | None = None,
    ) -> None:
        if call.keywords or len(call.args) != 1:
            self._fail(
                "P105",
                "observe expects exactly one quantum argument.",
                call,
            )
        qubit = self._bound_qubit(call.args[0])
        observation_source = self._source_for(call, "explicit-observation")
        if result_target is None:
            result_source = self._source_for(call, "discarded-observation-result")
            display_name = None
        else:
            result_source = self._source_for(result_target, "observation-result")
            display_name = result_target.id
        result_id = ClassicalBitId(f"{result_source.source_operation_id}:classical-bit")
        result = ObservationResultValue(result_id, display_name, result_source)
        self._classical_bits.append(result)
        self._instructions.append(
            Observation(
                LogicalOperationId(f"{observation_source.source_operation_id}:operation"),
                qubit.id,
                result.id,
                self.default_basis,
                ObservationReason.EXPLICIT,
                observation_source,
            )
        )
        if result_target is not None:
            self._observation_bindings[result_target.id] = result

    def _capture_reset(self, call: ast.Call) -> None:
        if call.keywords or len(call.args) != 1:
            self._fail(
                "P105",
                "reset expects exactly one quantum argument.",
                call,
            )
        qubit = self._bound_qubit(call.args[0])
        source = self._source_for(call, "reset")
        self._instructions.append(
            LogicalResetOperation(
                LogicalOperationId(f"{source.source_operation_id}:operation"),
                qubit.id,
                source,
            )
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
        value = self._binding_for_name(expression.id)
        if value is None:
            self._fail("P106", f"Unknown quantum value `{expression.id}` in return.", expression)
        if expected.kind is ReturnValueKind.QUANTUM_VALUE:
            if not isinstance(value, (LogicalQubitValue, _QuantumCallResultBinding)):
                self._fail(
                    "P110",
                    "A classical Bit result cannot be returned as Qubit.",
                    expression,
                )
            if value.id in self._classical_return_qubit_ids:
                self._fail(
                    "P110",
                    "A quantum value cannot be returned as both Bit and Qubit.",
                    expression,
                )
            self._quantum_return_qubit_ids.add(value.id)
            return ScalarReturn(ReturnValueRef(ReturnValueKind.QUANTUM_VALUE, value.id))
        if isinstance(value, ObservationResultValue):
            return ScalarReturn(ReturnValueRef(ReturnValueKind.CLASSICAL_BIT, value.id))
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
        if self._binding_for_name(name) is not None:
            self._fail("P107", f"Reassignment of `{name}` is not supported.", node)
        self._quantum_bindings[name] = value
        self._qubits.append(value)

    def _bound_qubit(self, node: ast.expr) -> _BoundQuantumValue:
        if not isinstance(node, ast.Name):
            self._fail(
                "P106",
                "Quantum intrinsic arguments must be bound quantum value names.",
                node,
            )
        value = self._quantum_bindings.get(node.id)
        if value is None:
            self._fail("P106", f"Unknown quantum value `{node.id}`.", node)
        if not isinstance(value, (LogicalQubitValue, _QuantumCallResultBinding)):
            self._fail(
                "P106",
                "Quantum intrinsic arguments must be bound quantum value names.",
                node,
            )
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
        if self._binding_for_name(function.id) is not None:
            self._fail(
                "P104",
                f"`{function.id}` is locally shadowed and is not an intrinsic.",
                function,
            )
        resolved = self._resolve_global_name(function.id)
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

    def _resolve_global_name(self, name: str) -> object:
        return self.globals.get(name, _MISSING)

    def _binding_for_name(self, name: str) -> _BoundValue | None:
        quantum_value = self._quantum_bindings.get(name)
        if quantum_value is not None:
            return quantum_value
        return self._observation_bindings.get(name)

    def _resolve_global_or_builtin_name(self, name: str) -> object:
        resolved = self._resolve_global_name(name)
        if resolved is not _MISSING:
            return resolved
        builtin_namespace = self.globals.get("__builtins__", builtins)
        if isinstance(builtin_namespace, dict):
            return builtin_namespace.get(name, _MISSING)
        return getattr(builtin_namespace, name, _MISSING)

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
        for marker in (
            tuple(_GATE_MARKERS)
            + tuple(_ROTATION_MARKERS)
            + tuple(_OBSERVATION_MARKERS)
            + tuple(_RESET_MARKERS)
            + tuple(_ANGLE_MARKERS)
        )
    )
