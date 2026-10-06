# A module-level store of a `TernaryExpr` is ZERO, on both architectures, where CPython stores the arm it took

**Found 2026-10-05 by `work/formal41-sweep-b14`** (claim `sweep41:sweep-b14`),
while landing `formal/build.py`'s `_lower_builtin_extremum` — the rewrite turns
`max(a, b)` into a `T.TernaryExpr`, and a `TernaryExpr` in a module-level STORE
is not lowered, so the rewrite had to be fenced off from the module body. **The
underlying defect needs no `max` at all** and is this document.

**Status: NOT FIXED.** It is fenced off rather than fixed, by
`_lower_builtin_extremum`'s `M.module_body_functions` guard, because the fence is
what stops a new wrong answer and the store path is a separate emitter question.
§4 is the next step.

## 1. The measurement

```
$ cat .tmp/mb6.py
TOP = 9 if 1 else 3
def main() -> Int:
    return TOP

$ python3 fire.py build --formal --no-prove --backend=arm64  -o .tmp/a .tmp/mb6.py
Built: .tmp/a  [arm64/macho]
$ .tmp/a; echo $?
0
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o .tmp/b .tmp/mb6.py
Built: .tmp/b  [x86_64/macho]
$ arch -x86_64 .tmp/b; echo $?
0
$ python3 -c 'print(9 if 1 else 3)'
9
```

**Both architectures answer 0, which is neither arm, and the condition is a
literal.** The two agreeing is the lucky part: they agree on the WRONG number,
which is what makes it hard to notice and what makes it worth a document rather
than a shrug.

**The same store of an ordinary arithmetic expression is right**, which is what
localises it:

| module-level source | this path | CPython |
|---|---|---|
| `TOP = 9` | 9 | 9 |
| `TOP = 3 + 9` | 12 | 12 |
| `TOP = 9 if 1 else 3` | **0** | 9 |

So it is the `TernaryExpr` in that position and nothing else about a module-level
store.

## 2. Why it is worse than a refusal here

`formal/arm64_codegen.py`'s own comment on the `TernaryExpr` arm says the reason
a CSEL is safe is that *"both arms are computed, one is chosen"* — which is a
statement about an expression that has somewhere to put its value. **A module-level
name has no storage on this path** (`bugs/FORMAL_module_state_no_storage.md`:
*"a module-level name has no storage here and every read of one is refused by
name"*), and the one exception — a name folded to a compile-time CONSTANT — is
decided by `formal/build.py`'s constant substitution, which runs on the AST
*before* any emitter. A `TernaryExpr` is not a constant, so it reaches the
emitter, and the emitter's module-body store path evidently evaluates it for
effect and drops the word.

**The generalisation to hold in mind: any construct whose value the module-body
store path does not read is a zero rather than a refusal.** That is the class
this document is filing, and one instance is not the whole of it.

## 3. How it was found, and the fence

`formal/model.py::NOT_LOWERED_BUILTINS`'s `max` row says the two-argument form is
"a compare and a select", and
`bugs/FORMAL_sweep_work_map_2026-10-05_b14.md` §5 is the change that cashes it.
The rewrite is a source-to-source rewrite into `F.TernaryExpr`, in the shared
pipeline, so it reaches every position a `def`'s body does — and the module body
is a synthetic function (`formal/model.py::MODULE_BODY_TAG`). Before the fence:

```
$ cat .tmp/mb3.py
TOP = max(3, 9)
def main() -> Int:
    return TOP
$ … --backend=arm64 -o .tmp/c .tmp/mb3.py && .tmp/c; echo $?
0
```

**So the rewrite turned today's honest `max(...)` refusal into a wrong number on
both architectures** — which is exactly the failure mode the fence exists to
prevent, and the reason `_lower_builtin_extremum` now asks
`M.module_body_functions(functions)` and skips those wrappers. After the fence the
same source is refused by the pre-pass, with the table row's own sentence.

`M.module_body_functions` is used rather than matching `MODULE_BODY_NAME` because
a LIBRARY is compiled from several sources and each may have a body:
`compile_formal_dylib` renames the second and later ones, so a name match would
find one of N and leave the others rewritten — which is the silent no-op
`MODULE_BODY_TAG`'s own comment exists to prevent, reintroduced one level down.

## 4. The next step, and what to check before writing it

**The store is the question, not the ternary.** Find where a module-level
assignment's value is read on the way to `__DATA`, and ask what it does with an
expression it has no lowering for. The two candidate answers, and they are not
the same change:

* **refuse** — the consistent choice, and the one `FORMAL_module_state_no_storage.md`
  argues for everywhere else (*"every read of one is refused by name"*). The
  message should name the construct and say that a module-level name here is a
  compile-time constant, so a computed value has nowhere to be stored.
* **fold** — only if the value can be decided at compile time, which
  `9 if 1 else 3` can and `max(a, b)` cannot. Folding is the right answer for the
  first and the wrong one for the second, and the difference is exactly the
  `formal/build.py` constant folder's existing predicate.

**Before either, measure the population**: a sweep of this corpus
(`bugs/sweeps/sweep-arm-14.txt`) for module-level stores whose right-hand side is
a `TernaryExpr`, and a grep of the repository's own `.mojo` for `^\w+ = .* if .* else`
at file level. If the population is zero outside this file, a refusal is a
three-line change and the doc is closed by it.

**And check the sibling positions**, because the same "no storage, no refusal"
shape is what §2 describes and this tree has three more of them, all measured on
2026-10-05 while fencing the rewrite:

| position | answer |
|---|---|
| module-level store `TOP = 9 if 1 else 3` | **0 — this document** |
| default argument value `def f(a, b = max(3, 9))` | refused by the link audit (`max` is not rewritten there) |
| struct field default `var y: Int = max(3, 9)` | refused by name — *"`s.y` reads a class-level constant of S, whose value is `max(3, 9)`"* |
| list literal element `[max(3, 9)]` | 1 element, correct |

**Three of the four are refusals and one is a wrong answer, which is the shape of
a gap rather than of a design.** The two refusals name the construct; the third
names it twice.

## 5. Why it is filed and not fixed here

`work/formal41-sweep-b14`'s claim is the sweep (`sweep41:sweep-b14`). The fix
belongs in the module-body store path of `formal/build.py`, which is a different
question from the one this branch was given, and the fence that stops the new
wrong answer is already in and measured — `test_formal_value_model.py`'s
`max_of_one_argument_is_refused_rather_than_folded_over_a_sequence` and its
siblings are the rows that keep the rewrite's boundaries honest, and
`max` at module level is refused by the pre-pass they share.