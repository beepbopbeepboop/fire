# The parser DISCARDS a `comptime` FUNCTION-TYPE alias, and silently erases a `comptime` call whose bracket mixes a keyword with a later positional

**Area:** FIRE_COMPILER (the parser), with FORMAL consequences. Found
2026-10-01 on `work/formal2-re-and-slice` while measuring the `tile.mojo` row.
**See the Status section at the bottom first: parts 1 and 2 are FIXED on
`work/bugs3-codegen-2-r2` (2026-10-01) and part 3 is still open.** Two
defects, both in the parser, both reachable from any consumer; the first is
what makes `tile.mojo` unanswerable at all, and the second was a silent wrong
value.

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

## Status (2026-10-01, `work/bugs3-codegen-2-r2` — parts 1 and 2 FIXED; part 3 still open, and one NEW gap found)

Measured on this tree, both halves of **part 2** reproduced exactly as the
census below describes:

```
comptime A = f[T=Int]()                 -> CallExpr   keeps its value
comptime A = f[a=1, b=2]()              -> CallExpr   keeps its value
comptime A = f[1, 2]()                  -> CallExpr   keeps its value
comptime A = f[T=Int, 1]()              -> IdentExpr  ERASED   <-- keyword then positional
comptime A = f[T=Int, "x", "y"]()       -> IdentExpr  ERASED
comptime A = f[T=Int, "x", linux=1]()   -> IdentExpr  ERASED
```

### Part 2 — FIXED. `f[T=Int, "x", linux=…, macos=…]` parses and keeps every element

Two defects in `_parse_primary`'s keyword-bracket branch, both now fixed:

* a bare element that was not a NAME (a literal, a call) fell through BOTH
  arms, so the loop hit its `elif peek != RBRACKET: break`, left the token
  unconsumed, and `_expect("RBRACKET")` raised — which part 1's fix turns into
  a refusal rather than a placeholder, so both halves had to land together;
* a bare element that WAS a NAME parsed and was then **discarded** — the old
  comment "else positional arg: arg_expr already fully parsed" described no
  code at all. So even a positional that did parse was lost.

Positionals are now kept as `(None, value)` pairs, which is the spelling
`emit_calls.py`'s comptime-param threading **already read them by**
(`elems = [val for nm, val in _bracket_attrs if nm is None]`, `emit_calls.py`
~:1070) and which `SubscriptExpr.attrs`' own `name: object` field allows. A
bare NAME is kept under its own name, so both readings see it. `f[1, 2]` (no
keyword at all) still takes the comma-separated-items branch and lands in
`index` as a `TupleExpr` — a different path with its own consumers, untouched.

### Part 1 — FIXED. A misparse is a refusal, and is no longer indistinguishable from a skipped function type

`_skip_comptime_rhs`'s bare `except:` is gone. It now records the failure on
the `Parser` (`self._comptime_rhs_failures`) and re-raises a `SyntaxError`
naming the line, the offending text, and the underlying error, so the module is
refused at the source line instead of compiling a `comptime` alias to a
placeholder that reaches every use. Two details that are the point of it:

* the exception set is **enumerated** (`SyntaxError`, `ValueError`,
  `TypeError`, `AttributeError`, `IndexError`, `KeyError`) rather than bare.
  A bare `except:` here also swallowed the compiler's own bugs — a
  `TypeError` from a malformed AST node presented as "unparseable comptime
  rhs" and became a placeholder, which is how a crash in this function could
  look like a stdlib constant silently reading 0. `RecursionError` and
  `MemoryError` are deliberately not caught.
* the function-type skip stays the deliberate placeholder it is, and its
  DETECTION had to widen to survive the new refusal: a parenthesized
  MULTI-LINE function type

      comptime _ReduceGeneratorPluginHookFnType = (
          def[num_reductions: Int, ...](...) capturing[_] -> None,
      )

  starts with `(`, so neither the `def`-first test nor `_will_see_arrow`'s
  depth-0 `->` test matched it, it fell through to `_parse_expr`, raised, and
  **took a real stdlib module out of the build**. 6 of the 22 function-type
  aliases are spelled this way. `_comptime_rhs_is_function_type` is the new
  three-case test (`def` first / `(` then `def` / `->` at depth 0), and the
  `->` case is kept as narrow as it was rather than generalised through
  arbitrary parens.

### Measured, on the whole stdlib module list

`build_stdlib_dylib.stdlib_modules()` — 249 source files — each parsed with
this project's own `Parser(py_tokenize(src)).with_filename(path).parse_module()`:

```
module entries: 249  source files found: 249
parsed OK: 249   failed: 0
```

That is the assertion that matters for a change which turns a silent
placeholder into a refusal: one real module (`std/_plugin/_trait.mojo`) failed
it at the intermediate state, which is how the parenthesized-function-type case
was found, and it passes now. **The integrator should re-run this and
`compile_stdlib.py` (the `U` count must not rise), because a refusal is a new
way for a stdlib module to fail** — that is the risk this change carries and
the reason the measurement is stated rather than assumed.

### Part 3 — STILL OPEN. A function-type alias needs to survive as a signature

Unchanged and unaddressed: `comptime Static1DTileUnitFunc = def[width: Int](Int) -> None`
still becomes `IdentExpr('_comptime_expr')`, so
`formal/model.py`'s `specialization_call_refusal` still has no callee to bind
brackets to, and `tile.mojo` / `unswitch.mojo` stay refused — **correctly**,
with the signature erased there is genuinely nothing to bind. A `FunctionType`
AST node carrying `comptime_params` and the runtime parameter/return
annotations is what unblocks it; `specialization_call_refusal`'s text already
describes the right lowering and has nothing to read it from. 22 aliases in 11
files depend on it, not 10 — see the census table below.

### Part 3, measured again 2026-10-03 (`work/formal18-tile-specialization`): the ERASURE is what the INTERPRETER trips over too, and it is a diagnostic with no position

Re-measured while landing the specialization-through-a-function-value lowering
(`FORMAL_stdlib_tile_row_is_a_specialization_through_a_function_value.md`
§"What landed"), because the differential test for that construct wanted the
stdlib's own spelling and could not have it.

`fire.py run` on the smallest possible file that uses it:

```sh
cat > .tmp/alias.mojo <<'EOF'
comptime Sig = def[width: Int](Int) -> None

def use_it(x: Some[Sig]):
    return 1

def main():
    return use_it(0)
EOF
python3 fire.py run .tmp/alias.mojo
```

```
  File ".../myinterpreter.py", line 4859, in eval_IdentExpr
    return self.scope.get(expr.name)
NameError: name '_comptime_expr' is not defined
During handling of the above exception, another exception occurred:
  ...
  File ".../myinterpreter.py", line 4286, in execute_ComptimeVarStmt
    value = self.eval_expr(node.value)
NameError: .tmp/alias.mojo:0:0: name '_comptime_expr' is not defined
```

Three things in that, and they are all this file's subject rather than a new
one:

* the interpreter's answer is the PLACEHOLDER's own name — `_comptime_expr` is
  the sentinel `fire_compiler.py` emits for a function type it does not model,
  so the interpreter is reporting the erasure rather than the file's line. The
  position is `0:0`, which is what makes it useless: a reader is sent to the top
  of the file for an error on line 1;
* `comptime Two = 2` in the same position runs fine, so it is the function-type
  literal and not `comptime`;
* the compiled path BUILDS the same file (measured: `fire.py build` exit 0), so
  the three consumers of a `comptime` alias disagree about what one is.

**The census is unchanged and is worth repeating because it is what sizes the
row:** 11 files, 34 alias lines —
`grep -rln 'comptime [A-Za-z_][A-Za-z_0-9]* = def' ../new-modular/Mojo/stdlib/std | wc -l`
→ 11, and the `grep -rn` of the same pattern → 34 (the difference is aliases
written across several lines, `std/python/bindings.mojo:244` among them). The
largest single user is `std/python/_cpython.mojo` (`PyCFunction`,
`PyCFunctionWithKeywords`, `PyCFunctionFast`).

**So the interpreter cannot be the oracle for any of the 11**, which is what
forced the differential test for the value-call lowering to write its function
type inline (`workgroup_function: Some[def[width: Int](Int) -> Int]`) instead of
behind an alias. Both spellings say the same thing to the formal readers — the
`Some[…]` base is what settles the bracket — and the inline one the interpreter
can execute; the test's docstring records the substitution rather than leaving it
as a mystery.

### NEW, found while fixing the above, and NOT fixed

`myinterpreter.py` has **no evaluation for a keyword-bracket call at all** —
`f[T=Int, y=5]()` is treated as a SUBSCRIPT on `f`, so the bracket's contents
are evaluated in the enclosing scope and `T` raises `NameError`:

```
$ python3 fire.py run ct4.mojo
comptime A = f[T=Int, y=5]()
comptime B = f[T=Int]()
comptime C = f[T, 9]()
NameError: 6:15: name 'T' is not defined
```

This is downstream of the parser and independent of it: it fails for the
all-keyword spelling that has always parsed, so part 2's fix does not change
it. It is what `std/io/file.mojo`'s `O_CREAT` / `O_APPEND` / `O_CLOEXEC`
aliases would hit on the interpreter path next, now that their parser half is
right. Filed as `bugs/CODEGEN_interpreter_evaluates_a_keyword_bracket_call_as_a_subscript.md`.

## The next step (part 3, and the two filed follow-ons)

Three separable pieces, separable on purpose:

1. ~~**`_parse_comptime_expr`'s bare `except:` is the bug amplifier.**~~ **DONE
   2026-10-01** — see the Status section; the `except:` is gone, a misparse is
   a `SyntaxError` naming the line, and the function-type detection widened to
   keep the 6 parenthesized multi-line aliases parsing (249/249 stdlib
   modules). It converts a
   `ParseError` into a placeholder that is indistinguishable from a deliberately
   skipped function type. Two callers cannot then tell "not implemented" from
   "misparsed". Making the two distinguishable — a distinct node, or a recorded
   error — is what makes (2) and (3) visible at all, and it is the smallest
   change with the largest diagnostic payoff.
2. ~~**A bracket mixing keyword and positional must parse.**~~ **DONE
   2026-10-01** — it parses, and every element is kept; see the Status
   section for the two defects that were in the way. Whichever subscript
   parser runs under `comptime` (`_parse_expr`'s, not the MLIR bracket path) has
   to accept Mojo's `f[T=Int, "x", linux=…, macos=…]` — the language's own
   `def platform_map[…]` signature requires it, so this is a parser bug against
   the language, not a stdlib quirk. Two cases: `f[T=Int, 1]()` and `f[a=1, 2]()`.
3. **A function-type alias needs to survive as a signature.** *(still open)* A `FunctionType` AST
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