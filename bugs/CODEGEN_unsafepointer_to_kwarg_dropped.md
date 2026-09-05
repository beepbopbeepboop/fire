# CODEGEN: `UnsafePointer(to=x)` (no `[T]` subscript) silently yields a null/zero pointer in compiled code

## Status

New, found 2026-09-04 while writing user-facing docs on the `UnsafePointer`/
tagged-struct pattern for mmap-style external-memory interop. Not
triaged/fixed, reported per this session's "file bugs you find" instruction.

## Repro

```mojo
fn main():
    var x: Int = 42
    var p = UnsafePointer(to=x)
    print("val:", p[0])
```

```
$ python3 mojo.py build -o /tmp/t4 /tmp/t4.mojo && /tmp/t4
val: 0        # expected: val: 42
```

Confirmed the address itself is bogus, not just the dereference:

```mojo
fn main():
    var x: Int = 999
    var addr = Int(UnsafePointer(to=x))
    print("addr computed:", addr)   # prints 0 — expected a nonzero address
```

`p.bitcast[UInt8]()[0]` on such a pointer similarly reads `0` instead of the
real first byte (`/tmp/t5.mojo` in the session's scratch dir).

## Root cause (traced, not fixed)

`gimple_gen_calls.py`'s `_lower_pointer_ctor` (~line 137) only handles the
**subscript-call** constructor shape, `UnsafePointer[T](x)` — see its own
docstring citing BUG-2026-027. The **plain-call keyword** shape used
throughout real Mojo and this project's own `myinterpreter.py` stand-in
(`_MojoUnsafePointerType.__call__(self, to=None, **kwargs)`,
`myinterpreter.py:1446`) — `UnsafePointer(to=x)` with no `[T]` — goes through
a different call-lowering path in `gimple_codegen.py` that has no special
case for the `to=` keyword at all. The keyword argument is silently dropped,
`node.args` ends up empty for this shape too, and it falls through to
whatever this codegen's generic "unresolved/no-arg call" default is — which
resolves to a zero/null pointer value instead of the address of `x`.

The **interpreter** path (`myinterpreter.py`) already documents (in
`_MojoPointer`'s own docstring, `myinterpreter.py:1338`) that
`UnsafePointer(to=x)` doesn't alias back to `x` there either — but that's a
disclosed simulation limitation of the Python stand-in, not something that
should also be true of the **compiled** path, which has real addresses
available and no reason not to wire this through correctly (e.g. by lowering
`UnsafePointer(to=x)` to the same `&x`-shaped C expression a
`ref[...]`-annotated struct field or a `Pointer(to=x)` presumably already
needs elsewhere).

## Impact

Any Mojo source using the common `UnsafePointer(to=local_var)` idiom (address
of a local, no explicit `[T]`) to build a pointer for passing to a helper /
another function compiles cleanly but silently produces a null-like pointer
at runtime, with no compile error or runtime diagnostic — a real, currently
undetected miscompile class, not merely an unsupported-shape refusal.
Workaround: use the subscript form, `UnsafePointer[TypeOfX](addr)`, together
with an address obtained some other way (e.g. one passed in externally,
which does correctly alias real memory — see the sibling doc on struct-
pointer field access for the next gap found along the same path).
