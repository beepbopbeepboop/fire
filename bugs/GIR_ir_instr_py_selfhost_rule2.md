# mojo/ir/instr.py breaks GIR rule 2 (self-hostable code) in a few places

`doc/GIR.md` section 2, rule 2: `types.py`, `instr.py`, `verify.py` and `build.py` must use plain
classes with every field annotated in `__init__`, and no closures, lambdas, `re`, tuple unpacking,
`getattr` or generators. `mojo/ir` is in the compiler's own import closure now (stage 3c), so this
matters for `make bootstrap`. Found 2026-11-23:

- `instr.py` ~line 94 uses `getattr(...)` for `tight`, and ~line 115 uses it for `capture`.
  `capture` is not declared in `Ex.__init__` at all. Add `self.capture: str = '&'` (check the
  default against the current getattr fallback) and use `self.capture` / `self.tight` directly.
- `instr.py` ~lines 93, 117 and 126: generator expressions inside `join(...)`. Replace each with an
  explicit loop that appends to a `list[str]`, as the `call` branch already does (~lines 103-105).
- `instr.py` ~lines 116, 123, 169 and the `render_lines` body (~289): list comprehensions with a
  condition. Make them explicit loops too.
- `instr.py` ~line 163: `ex_cat(*parts)` is varargs. Check whether the self-hosted compiler handles
  `*parts`. If you cannot tell, leave the signature alone and say so in your report.

`build.py` is clean (its only mention of the banned constructs is a comment).

## Checks

    python3 tools/c_oracle.py check --base <start sha> -j 4             # identical C and C++
    python3 tools/c_oracle.py check --base <start sha> --closure        # no new stubs (6 min)
    python3 test_gir_builder.py && python3 test_gimple_cpp_core_arms.py

Delete this doc in the same commit.
