# Debugger provenance and expanded calls

The debugger presents immutable compiler and runtime evidence. It does not
reconstruct calls from source text or infer ownership from allocated slots.

## Expansion path

```text
Python functions -> LogicalModule -> call expansion / logical instantiation
-> ExpandedLogicalProgram -> lifetime analysis -> logical-slot allocation
-> CircuitIR -> ExecutionTrace -> TraceInspection -> TraceDebuggerSession
```

A qubit declaration inside a reusable quantum function is a definition. Each
function invocation instantiates that declaration as a distinct logical quantum
value unless the value is a bound parameter alias. The debugger can therefore show
the definition origin, the deterministic call instance, and the allocated slot as
separate facts.

Returning a `Qubit` transfers the same logical quantum value across the function
boundary. It never copies quantum state. A caller assignment such as
`value = prepare()` is a source alias for the returned expanded value and does not
receive a second slot.

## Definition and invocation locations

For an operation defined in a reusable callee, `Operation.source` stays linked to
the callee definition. `OperationProvenance.call_stack` independently records the
ordered caller-to-callee frames. A frontend can render both locations without
pretending the operation was textually substituted into its caller.

## Serialized compatibility

Execution traces use schema version $4$, trace inspections use schema version $2$,
and debugger session documents use schema version $2$. These versions include the
structured call-stack provenance shape. Current constructors reject older or
mismatched serialized schema versions rather than silently reinterpreting them.

The current allocation policy remains dense and non-reusing. Lifetime analysis is
available for debugger evidence and future allocation policies, but a lifetime end
does not yet cause a slot to be reused.
