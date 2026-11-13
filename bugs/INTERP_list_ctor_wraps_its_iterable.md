# INTERP: `List(<iterable>)` wraps the argument as one element

**Status (2026-11-13):** open. Found while fixing the compiled-path bare-`List(...)`
constructor (the gate-stdlib-syntax class-2 item: a bare `List(...)` erased to
`int64_t` and the compiled program segfaulted; fixed in 66c1d6a9b, pinned by
test_gimple.py's gate_stdlib_syntax_bare_list_constructor); the two engines
disagree on the same program.

## Repro

    python3 fire.py run - <<'EOF'
    def main():
        var a = List([1, 2])
        print(a)
        print(a * 3)
        var b = List(length=3, fill=7)
        print(b)
    EOF

- **Observed (interpreter):** `[[1, 2]]`, `[[1, 2], [1, 2], [1, 2]]`, `[]`.
- **Expected / compiled path:** `[1, 2]`, `[1, 2, 1, 2, 1, 2]`, `[7, 7, 7]`.
  `[1, 2] * 3` already answers that in BOTH engines; `List([1, 2])` is the same
  list, and `python3 fire.py build` prints the expected values after the codegen
  fix in the commit that deleted the class-2 item of the gate doc.

## Cause

`myinterpreter.py`'s `_MojoListType.__call__` (around line 2990) returns
`list(args)` — a POSITIONAL-VARIADIC construction. So:

- `List([1, 2])` becomes `list(([1, 2],))` = `[[1, 2]]` (one element);
- `List((1, 2))` becomes `[(1, 2)]`;
- `List(other_list)` becomes a one-element list holding `other_list`, not a copy;
- `length=`/`fill=`/`fill_with=` are ignored (`_MojoListType` does not strip them),
  so `List(length=3, fill=7)` returns `[]`.

`List(1, 2, 3)` — the variadic form — is correct and must keep working.

## Exact next step

In `_MojoListType.__call__`, before the variadic fallback:

1. `length=` present: return `[fill] * length` (evaluate `fill` once), and for
   `fill_with=<callable>` return `[fill_with(i) for i in range(length)]`.
2. Exactly one positional argument that is an iterable (list/tuple/set/dict/
   range/str/bytes/`_MojoListType` result): return `list(arg)` — a copy in the
   container's iteration order, matching `list(...)`.
3. Everything else keeps the current `list(args)` behaviour.

There is no dedicated interpreter unit for the constructor; the natural pin is a
case in `test_interp_oracle.py` (it runs the same text through `python3 fire.py run`
and CPython's `list` equivalent and requires identical stdout) or a small case in
`test_runtime_diff.py` comparing the two engines. A direct Python-level check of
`_MojoListType()([1, 2])`, `_MojoListType()(length=3, fill=7)` and
`_MojoListType()(1, 2, 3)` is the cheapest regression; it needs no compiled path.
