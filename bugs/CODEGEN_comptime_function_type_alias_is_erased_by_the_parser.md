# The parser DISCARDS a `comptime` FUNCTION-TYPE alias, and silently erases a `comptime` call whose bracket mixes a keyword with a later positional

**Area:** FIRE_COMPILER (the parser), with FORMAL consequences. Found
2026-10-01 on `work/formal2-re-and-slice` while measuring the `tile.mojo` row.
**NOT FIXED — and NOT this branch's to fix.** Two defects, both in the parser,
both reachable from any consumer; the first is what makes `tile.mojo`
unanswerable at all, and the second is a silent wrong value.

## Part 1 — a function-type alias is ERASED, so its callee has no signature

This is the finding that closes the open question in
`bugs/FORMAL_stdlib_tile_row_is_a_specialization_through_a_function_value.md`.
That doc names two options and says "which one is a decision rather than an
implementation". The first option is **not implementable**, and not for want of
effort: **the signature is not in the tree.**

`tile.mojo:20` declares

    comptime Static1DTileUnitFunc = def[width: Int](Int) -> None

and the parser gives the alias the value `IdentExpr('_comptime_expr')`:

```
$ python3 - <<'PY'
import fire_compiler as F
p = '../new-modular/Mojo/stdlib/std/algorithm/backend/tile.mojo'
for st in F.Parser(F.py_tokenize(open(p).read(), p)).with_filename(p).parse_module():
    if isinstance(st, F.ComptimeVarStmt) and st.target == 'Static1DTileUnitFunc':
        print(type(st.value).__name__, repr(st.value))
PY
IdentExpr IdentExpr(name='_comptime_expr', line=0, col=0)
```

`fire_compiler.py`'s `_parse_comptime_expr` (`:3765`) skips the whole line when
it sees a function type:

```python
# Check for function type definitions — skip to newline
if (t.kind == "KW" and t.value == "def") or self._will_see_arrow():
    ...
    return IdentExpr("_comptime_expr")
```

Its own docstring says this is deliberate — "for complex types
(`def[...] -> ...`), **skip them**". But the consequence was never drawn: the
alias is not merely unparsed, it is **erased**, so nothing downstream can recover
it. `formal/model.py`'s `specialization_call_refusal` refuses
`workgroup_function[tile_size](offset)` precisely because "a decision about a
signature … needs a declaration and there is none in hand" — and there is none,
because the parser threw it away two stages earlier.

**So that doc's "Whose" section is right that `tile.mojo` belongs to another
worker, and the reason is one level deeper than it states:** not GPU ownership
(`construct:mlir-and-gpu-globals`, which is merged and does not have it) but a
missing parser capability no formal-side work can supply.

### The row is bigger than 4 files

Every `comptime NAME = …` in the 252-file new-modular stdlib whose parsed value
is `_comptime_expr`, by parsing each file:

    32 aliases in 11 files — 22 of them FUNCTION TYPES

| family | aliases | what depends on the signature |
|---|---|---|
| the tile/unswitch signatures | `Static1DTileUnitFunc`, `Dynamic1DTileUnitFunc`, `BinaryTile1DTileUnitFunc`, `Static2DTileUnitFunc`, `SwitchedFunction`, `SwitchedFunction2`, `Static1DTileUnswitchUnitFunc`, `Static1DTileUnitFuncWithFlag`, `Static1DTileUnitFuncWithFlags`, `Dynamic1DTileUnswitchUnitFunc` | the 4-file `tile.mojo` row and `algorithm/backend/unswitch.mojo` beside it |
| plugin-hook function types | `_UnsafeDanglingPluginHookFnType`, `_StackAllocationPluginHookFnType`, `_PrintEmitPluginHookFnType`, `_ExpPluginHookFnType`, `_TanhPluginHookFnType`, `_ReduceGeneratorPluginHookFnType` | a hook CALLED through a parameter typed by the alias — `tile.mojo`'s shape exactly |
| CPython C-API function pointers | `PyCFunction`, `PyCFunctionWithKeywords`, `PyCFunctionFast`, `destructor`, `reprfunc`, `Typed_initproc`, `Typed_newfunc`, `MOJO_PYTHON_TYPE_OBJECTS`, `PyFunctionRaising`, `PyFunctionWithKeywordsRaising` | a C callback ADDRESSED, and its arity is the alias's |

So the 4-file row was an undercount of the *mechanism*, not only of the files:
`unswitch.mojo` was already in the sweep's terminal-cause table as a dependent of
`tile.mojo`, so it is counted inside the 4 rather than beside it.

## Part 2 — a bracket mixing a keyword with a LATER POSITIONAL is silently erased

The other 10 aliases are not function types and fail for a different reason.
Minimised, by parsing one `comptime` line at a time:

```
f[T=Int]()                -> CallExpr          keeps its value
f[T=Int, a=1]()           -> CallExpr          keeps its value
f[a=1, b=2]()             -> CallExpr          keeps its value
f[1, 2]()                 -> CallExpr          keeps its value
f["a"]()                  -> CallExpr          keeps its value
f[T=Int, 1]()             -> IdentExpr         ERASED   <-- keyword then positional
f[a=1, 2]()               -> IdentExpr         ERASED
f[T=Int, "x"]()           -> IdentExpr         ERASED
f[T=Int, "x", "y"]()      -> IdentExpr         ERASED
```

**A bracket that mixes a keyword argument with a positional one after it does not
parse**, `_parse_comptime_expr` swallows the `ParseError` in its bare `except:`
(`:3790`) and returns the placeholder. It is not the string literal that breaks
it — `f["a"]()` is fine — it is a positional element FOLLOWING a keyword.

### Why this one is worse, and why nothing reports it

The four erased names in `std/io/file.mojo` are **integer constants**, not
function types:

    comptime O_RDONLY = 0x0000                       # KEPT — plain literal
    comptime O_CREAT = platform_map[T=Int, "O_CREAT", linux=0x0040, macos=0x0200]()
    comptime O_APPEND = platform_map[                 # ERASED — keyword `T=Int`,
        T=Int, "O_APPEND", linux=0x0400, macos=0x0008  # then positional "O_APPEND"
    ]()

(`platform_map` is `std/sys/info.mojo:566`, and its own signature puts
`operation` first and `linux`/`macos` after `*`, so a keyword-then-positional
bracket is the normal way to call it.)

And these are USED:

    flags = O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC     # io/file.mojo:103
    flags = O_RDWR | O_CREAT | O_CLOEXEC                 # :106
    flags = O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC    # :109

So `O_CREAT`, `O_TRUNC`, `O_APPEND` and `O_CLOEXEC` read as
`IdentExpr('_comptime_expr')` at each of those uses, and the file-open flags the
program passes to `open(2)` are built from a placeholder rather than from
`0x200 | 0x400 | 0x1000`.

**That is a wrong answer, not a refusal** — the shape this backend exists to make
impossible — and it is invisible to the sweep: `std/io/file.mojo` is refused
earlier for other reasons, so it has no `codegen` line and no
`formal_sweep_causes.py` row. It is here because the census that produced the 32
is what found it. **`bugs/CODEGEN_stdlib_stat_mode_constants_missing.md` is the
same family (stdlib constants not reaching their user) and should be read with
this.**

## The next step

Three separable pieces, separable on purpose:

1. **`_parse_comptime_expr`'s bare `except:` is the bug amplifier.** It converts a
   `ParseError` into a placeholder that is indistinguishable from a deliberately
   skipped function type. Two callers cannot then tell "not implemented" from
   "misparsed". Making the two distinguishable — a distinct node, or a recorded
   error — is what makes (2) and (3) visible at all, and it is the smallest
   change with the largest diagnostic payoff.
2. **A bracket mixing keyword and positional must parse.** Whichever subscript
   parser runs under `comptime` (`_parse_expr`'s, not the MLIR bracket path) has
   to accept Mojo's `f[T=Int, "x", linux=…, macos=…]` — the language's own
   `def platform_map[…]` signature requires it, so this is a parser bug against
   the language, not a stdlib quirk. Two cases: `f[T=Int, 1]()` and `f[a=1, 2]()`.
3. **A function-type alias needs to survive as a signature.** A `FunctionType` AST
   node carrying `comptime_params` and the runtime parameter/return annotations
   is what `specialization_call_refusal` needs to become answerable — its text
   already describes the right lowering, it has nothing to read it from.

Until (3) lands, `tile.mojo` and `unswitch.mojo` stay refused, and that refusal
is **correct**: with the signature erased there is genuinely no callee to bind the
brackets to, and emitting the call with them dropped would build, run, and return
a number the source never wrote.

## What was measured, and what was not

* Both minimisations above, one `comptime` line parsed at a time, so the trigger
  is identified rather than guessed.
* The 32-alias census over the whole 252-file stdlib.
* The `tile.mojo` refusal itself, on arm64 and x86-64, identical text, and
  reproduced in 8 lines with no stdlib at all (`comptime TileFunc = def[width:
  Int](Int) -> None` + `workgroup_function[3](n)` → the same message), which is
  what establishes that nothing about `tile` the FUNCTION is involved.
* That a parameter of that declared type builds fine when it is not called
  through brackets — so the refusal is the brackets, not the alias.
* **NOT measured:** a sweep delta, the x86-64 answer for `unswitch.mojo`, and
  what the 22 function-type aliases would do to a file that is not already
  refused earlier for an unrelated reason.