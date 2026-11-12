# The interpreter keeps `field(...)`'s `Field` object as a dataclass field default

**Area:** `myinterpreter.py` — `MojoClass.__call__`'s field-default evaluation.
**Status:** open, pre-existing, found while fixing `interp-tokenizer-oracle`
(commit landing `@dataclass` as a compile-time transform; see below).

## What happens

`@dataclass` is now (correctly) not applied to an interpreted class: CPython's
`dataclasses.dataclass` cannot process a `MojoClass`, and its construction half
— fill the declared fields in declaration order with their defaults — is what
`MojoClass.__call__` already does. But that constructor evaluates a field's
default expression literally, so `field(default=...)` and
`field(default_factory=...)` (real calls returning a `dataclasses.Field`)
become the field's VALUE instead of the wrapped default:

    $ cat .tmp/dc_field.py
    from dataclasses import dataclass, field

    @dataclass
    class P:
        a: int
        xs: list = field(default_factory=list)
        n: int = field(default=7)

    p = P(1)
    print(type(p.xs).__name__, type(p.n).__name__)

    $ python3 fire.py run .tmp/dc_field.py
    Field Field

    $ python3 .tmp/dc_field.py          # CPython, the oracle
    list int

Every `field(...)` default is affected (`init=`, `repr=`, `kw_only=` are not
modelled either), and so is every `P(...)` construction that omits those
fields. `fire_compiler.py`'s own dataclasses use `field(default_factory=list)`
in ~20 places, so any interpreted program that *constructs* those AST nodes —
as opposed to the tokenizer oracle, which stops after `py_tokenize` — reads a
`Field` where it expects a list.

The compiled/gimple path already honours these (`c3d09b423`), so the interpreter
is the odd engine out; `test_interp_oracle.py` would show the divergence if a
corpus case constructed one.

## Exact next step

In `MojoClass.__call__`, where `value = self.interpreter.eval_expr(f.value)` is
computed for a `VarDecl`/`AssignStmt` field, unwrap a `dataclasses.Field`
before `_coerce_to_declared_type`:

- `default is not MISSING` → use `default`;
- else `default_factory is not MISSING` → call it (it can be any callable, so
  call it, do not special-case `list`/`dict`);
- else `None`.

Import `Field`/`MISSING` from `dataclasses` next to the existing `dataclass`
import. A `Field` can only come from `dataclasses.field()`, so an identity /
`isinstance` check needs no per-class "is this a dataclass" flag — but
`myinterpreter.py` self-hosts, so the exact construct has to compile through
`mojoc`; `isinstance(value, Field)` is the thing to try first and the
self-host/stage2 build is the check (the interpreter's own suite cannot see a
compiled-codegen-only break).

Add the two cases above to a `fire.py run` test, next to
`test_python315_disjoint_bases.py`'s `@dataclass` coverage, and compare against
`python3` on the same text.
