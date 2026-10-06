# A `try` handler arm is still never emitted, and the reason it is not worth
# fixing in one function is that EVERY arm in this repository calls something

**Area:** FORMAL, exceptions. Claim `project33:exceptions`, measured 2026-10-05
on `work/formal33-exceptions`. **OPEN, and step 1 of §5 — the design question §4
calls the only one in this document with no answer in the code — is ANSWERED and
LANDED (2026-10-05, `work/formal59-docs`).** Step 2's table is half of it, and
the half that decides the matching rule is now generated off the interpreter and
pinned against CPython itself; the KIND NUMBERING is still unmade. Steps 3-6 are
untouched. The uncaught half of the exception contract landed earlier (three
commits: `raise` of a class leaving with CPython's status, a float `/` by a zero
divisor leaving, and a failing `assert` running its message and its enclosing
`finally`) and this is the remainder.

## 2026-10-05 (`work/formal59-docs`): §4's TWO design questions are answered,
## and the answer to the first is a TABLE pinned against CPython

§4 ends by naming one question as unanswerable from the code and saying "decide
this before writing the emitters". Both are decided here, with the measurement
that decided each, and the first one landed as code rather than as prose.

### The superclass question: the word is a KIND and the dispatch walks a base
### CHAIN. It cannot be "this is exactly `ZeroDivisionError`".

`ZeroDivisionError` is a subclass of `ArithmeticError`, which is a subclass of
`Exception`; `KeyError` and `IndexError` are both `LookupError`. So
`except Exception:` — the commonest arm in real code, and the reason §4 refuses
to leave the cheap version — does not reduce to "the kinds are equal", and a
status word carrying only an equality test cannot answer it.

**The answer is the second option §4 offers, with the cheap half made cheap
rather than the semantics made wrong:** the word carries a small integer KIND
(no pointer, so no frame per raise site and no `_blob_cap` question), and the
DISPATCH walks the same base chain CPython walks. The chain is a table, not a
run-time chase, so the cost is one compare per arm in source order at a branch
that only exists on the exceptional path.

**And the chain is not a tree, which is the row that settles it.**
`GeneratorExit` derives from `BaseException` DIRECTLY, not from `Exception`, so
an implementation that flattened the hierarchy would run `except Exception:`'s
arm for it. `CPYTHON_EXCEPTION_SUBCLASSES` therefore keeps DIRECT bases and
`exception_catches` walks them, and that shape is asserted directly rather than
described — see the oracle below.

**The table is generated off the running interpreter, and it is pinned by
CPython itself rather than by a hand-written expectation.**
`test_formal_exceptions.py`'s `run_matching_oracle` asks CPython to actually
CATCH, for **every** `(arm, raised)` pair over the 66 classes CPython will
construct bare — 4356 pairs — and compares that with `exception_catches`. The
whole grid, because the failure mode of a hand-kept hierarchy is an edge nobody
remembered, and `test_formal_exceptions.py` already runs before every backend
assertion in the file.

**That oracle earned its cost immediately: it found a real bug in the table as
first written.** 36 of the 4356 pairs disagreed, all of one kind — Python 3
keeps `OSError`'s historical names as ALIASES of the same class object
(`EnvironmentError`, `IOError`), and a table keyed by `__name__` gave the alias
its own empty base list, so `except EnvironmentError:` stopped matching
`BlockingIOError`. Fixed in two places, because giving the alias the right base
list is only half: a walk COMPARES a base with the arm the reader wrote, so both
ends go through `CPYTHON_EXCEPTION_ALIAS` (`{spelling: canonical}`, grouped by
object identity). This is the strongest argument in this document for pinning
the rule against the interpreter rather than against a list.

### The `as e` question: bind `e` to the WORD, and REFUSE any read of it.

§4 lists three options and says none is free. The answer is the second, and it
is free because of a fact already in the tree: `model.BUILTIN_EXCEPTION_FIELDS`
is `("args",)`, and `args` is where CPython puts the message. So an exception
object on this path is a class with ONE slot, and giving `e` a real object means
a frame allocation at every raise site — `_blob_cap`, a frame-lifetime question
and a memory question, for a spelling whose only observable use is `str(e)`.

So: **`except E as e` binds `e` to the status word itself, and every READ of `e`
is refused by name.** `raise` and `continue` in an arm are already legal and
already change no answer; a read of `e` is refused rather than given the word,
because printing a word where CPython prints the message is the
wrong-but-exit-0 artifact this backend exists to make impossible, and refusing
costs one diagnostic on a construct whose correct lowering needs the frame that
is the NEXT step's cost. When the frame lands, the refusal is deleted with the
refusal that named it, and nothing else moves: the binding was already the word.

### What is NOT answered, and it is the smaller half of step 2

**The KIND NUMBERING is still unmade** — which class gets which integer — and it
is genuinely unmade until the word has a home, because the numbering has to be
stable across a dylib boundary and nothing states what a library publishes. The
table that IS landed (`CPYTHON_EXCEPTION_SUBCLASSES`, `CPYTHON_EXCEPTION_ALIAS`,
`exception_catches`) is the part that does not depend on it: it is a fact about
CPython, so it is right before any word exists and unchanged after. Steps 3-6
are untouched, and §3's measurement still says the same thing: in-function
routing moves 0 files.

**Read this before planning the work.** The obvious plan — emit the arms, route
a `raise` inside the same function to the arm that matches — is measurably
worth **zero files in this repository**, and §3 is the measurement that says so.
What every real `try` in this corpus needs is an exception to cross a **call**,
which is a different and larger piece. The predecessor of this document,
`FORMAL_except_arm_is_never_emitted.md`, was deleted with its claim
(`formal8-5`, no longer active); this is its successor and carries the same
subject plus the table.

## 1. What the backends do today, measured against CPython

Every row below is `--no-prove` on both architectures on
`work/formal33-exceptions` (`8a7666f5`, `2a1b901a`, `fd5a3934`), with CPython
as the oracle — the same program, `main(3)` appended. Reproduce with
`python3 test_formal_exceptions.py` (198 checks, all passing) and with the
25-row probe the three commits cite.

**CORRECT, both backends, and the same answer as CPython** — 21 of 25 rows:

| construct | CPython | backend |
|---|---|---|
| `raise ValueError('boom')`, `raise ValueError` (bare) | exit 1 | exit 1 |
| `raise OSError('e', 2)` | exit 1 | exit 1 |
| `raise ValueError(g())` — the argument expressions RUN | exit 1, `arg` printed | same |
| `raise MyErr()`, `raise MyErr` (bare, class declared here) | exit 1 | exit 1 |
| `raise MyErr('m')` for `class MyErr(ValueError)` | exit 1 | exit 1 |
| `raise e` for a local holding an instance | exit 1 | exit 1 |
| `raise 'a plain string'`, `raise <a call's result>` | exit 1 | exit 1 |
| bare `raise` | exit 1 | exit 1 |
| `raise SystemExit` / `(0)` / `(3)` / `(-1)` / `('msg')` | 0 / 0 / 3 / 255 / 1 | same |
| `1 // 0`, `1 // (n-1)` at 1, `n % 0` | exit 1 | exit 1 |
| `1.0 / 0.0`, `1.0 / z` for `z == -0.0` | exit 1 | exit 1 (was **exit 0 + `inf`**) |
| `xs[5]`, `d['b']`, `int('zz')` | exit 1 | exit 1 |
| `assert` true / false / with a message | 0 / 1 / 1 | same |
| `finally` on `return`, on `break`/`continue`, nested, on a `raise` | — | same |

**REFUSED, by name, and correctly** — 3 rows, all one shape:

| construct | the refusal |
|---|---|
| `except ValueError: print(...)` | "`ValueError` is a handler arm with a body this path cannot put in the image, so it is refused rather than dropped" |
| `except ValueError as e: print(...)` | the same, with "`ValueError` as e" |
| `except: print(...)` | the same, with "a bare `except:`" |

**WRONG in one remaining row**, and it is not an exception row:
`print(xs.zzz)` is refused because **`print()` cannot tell whether a
`MemberExpr` is a string or a number**, not because of the `AttributeError`
CPython raises. That is a `print` typing gap (`formal/model.py`'s
`print`-operand refusal), reachable without any exception in the program, and it
belongs to whoever owns `print`'s operand model.

## 2. Why the arms are not emitted, in one sentence each

* There is no unwinder: `_emit_try` in both emitters skips the arms outright,
  and `RaiseStmt` leaves the process, so no edge runs from a raise site into an
  arm. That is stated at `formal/model.py::refuse_dropped_handler_arm`, and it
  is TRUE.
* The alternative was measured and is the failure CLAUDE.md names: an arm that
  stores, calls or prints with nothing to say so gives a program that builds,
  runs, prints nothing and exits 0.
* The CFG agrees with the emitter on purpose. `_build_cfg`'s `TryStmt` arm
  (`formal/model.py`, the long comment beginning "THE HANDLER ARMS ARE NOT
  RUN, and not as a simplification") runs the body, the `else` and the
  `finally`, and does not run the arms — because nothing in the image can run
  them. Two places depend on that agreement and would have to move together with
  the emitters: the arm's dominance in `_definitely_stored`, and
  `test_formal_read_before_store.py`'s `every_handler_stores_is_dominating` row
  (157 checks, of which 2 are try/else graph shapes).

## 3. The measurement that decides the order: ONE arm in this repository has a
## call-free `try` body

`formal/model.py::unemitted_handler_arm` over every `.mojo` file in the tree
(walked with `fire_compiler`'s own parser, `except` arms with a body only):

```
files/functions with an unemitted handler arm: 5
  ... whose try body contains NO call at all: 1
    ./mojo.mojo run_repl   ReturnStmt
  ... with calls:
    ./mojo.mojo dump_file                        ['open', '.read']
    ./scripts/stage2_mojo_interpreter.mojo load_interpreter_with_full_pipeline
                                                    ['open', '.read', '.close', 'mojo_to_python', '.ModuleType', 'exec']
    ./scripts/stage2_mojo_interpreter.mojo stage2_compile
                                                    ['open', '.read', '.close', '.get', '.get', 'print']
```

Two things follow, and the second is the one that matters.

1. **The sweep census overstates the class.** The sweep maps
   (`FORMAL_sweep_work_map_2026-10-04_b11/b12`) rank "a handler arm with a body"
   as a 25–30 file row. That count is of files the sweep REFUSED; this is a
   count of `try` statements in the repository, and it is **5 functions in 3
   files**. The two numbers are not the same measurement and the sweep's is
   about corpus coverage, not about how much work the construct is. Do not
   size this work from the sweep row.
2. **In-function routing would unblock nothing.** The one call-free arm is
   refused for a `ReturnStmt`, which is not a raise site a dispatch could
   reach. Every arm whose body could actually be dispatched — `open`, `read`,
   `close`, `print`, `exec`, `mojo_to_python` — has a `try` body that CALLS,
   and a call into a function of this image is a raise site the callee decides,
   not the caller. So the restricted, decidable slice ("emit the arms, route
   the statically-known raise sites, refuse the rest") lands a large change to
   `formal/model.py`'s CFG and to both emitters and moves **0 files**, while
   the corpus rows need the part below.

## 4. The design, and what is left of it

The task this doc answers asks for "a status-word/unwinding convention both
backends can emit, with the Lean model carrying the exceptional exits". The
unwinding half is a status word, and the shape below is the one the code is
already arranged for — it is not a proposal from nothing.

**The convention.** One callee-visible word per function, meaning "an exception
is in flight", holding the KIND of the current exception:

* kind 0 = no exception;
* one small integer per exception class this image can name, from a table
  `formal/model.py` owns and both emitters read — the same table
  `CPYTHON_EXCEPTION_BASES` is, plus the classes a module declares;
* a class an image cannot name — an unmodelled base. `357e3b5c` fixed the
  case that was filed for this, a subclass of a builtin base that built and
  then died, by refusing a `try` that has an `except` arm at all on both
  backends — gets kind 1 and is not matchable by name, which is honest
  rather than convenient.

Every function that can raise: reserves the word in its own frame, and returns
through it. Every call site of such a function: after the `BL`, tests the word
and branches to the innermost enclosing `try`'s dispatch when it is non-zero,
and does nothing when it is zero. That last half is what makes the change
cheap at every ordinary call site and is why it is a WORD rather than a second
return value — the value is already in X0/RDI and must stay there.

**The dispatch.** For each arm in source order: compare the word against the
arm's kind (a tuple arm is two compares, a bare `except:` is an unconditional
take), and on a match bind `as name` and run the arm's body, then jump to the
join. No match: run the enclosing `finally`, then either re-dispatch at the
NEXT enclosing `try` or leave with the status `model.raise_exit_status` already
decides.

**Why the word and not the class's own identity.** A pointer to the exception
object would let `except A` match a SUBCLASS by walking bases, which is what
CPython does and what `isinstance` needs; a small integer says "this is exactly
`ZeroDivisionError`" and an arm for a subclass of it would not match. The
integer is the honest cheap version, and the difference is visible in exactly
one shape — `except Exception:` / `except BaseException:` — which is the most
common arm in real code and therefore cannot be left as the cheap version. So
either the kind table grows a `SUPERCLASS_OF` bit, or the word is a pointer and
the base walk moves into the dispatch. **Decide this before writing the
emitters**: it is the one design question in this document with no answer in the
code, and both answers are defensible.

**`except A as e` needs the object.** With a kind word there is no object to
bind, so `e` has no value. Three options, none free: bind `e` to the word
(wrong for `str(e)`), refuse `as e` while emitting the arm that does not bind
it (sound, and it loses a common spelling), or give the exception a real
representation. The one this tree already has is `model.BUILTIN_EXCEPTION_FIELDS
= ("args",)`, so an object is not far away — but a class with an `args` slot is
a FRAME on this path and copying one per raise site is a frame-budget question
(`_blob_cap`), not a code question.

## 5. The exact next steps, in order

1. ~~**Decide §4's superclass question and the `as e` question.**~~ **DONE
   2026-10-05 (`work/formal59-docs`) — both answered at the top of this
   document, and the first one landed as `CPYTHON_EXCEPTION_SUBCLASSES` /
   `CPYTHON_EXCEPTION_ALIAS` / `exception_catches` with CPython itself as the
   oracle over all 4356 `(arm, raised)` pairs.** The part of step 2 below that
   does not depend on the numbering is therefore already in place.
2. **The kind table** in `formal/model.py`: `{class name -> integer}`, from
   `CPYTHON_EXCEPTION_BASES` plus this unit's declarations, published in
   `info` so both emitters and both proof generators read ONE list. This is
   shared infrastructure and fixes nothing by itself — it is worth landing on
   its own and saying so.
3. **The raise sites** already know their class on this branch: `RaiseStmt`
   (`model.raise_class_name` / `raise_declared_class_name`),
   `_emit_div_shift_pow`'s integer `div0_label` and
   `_emit_float_divide_by_zero_guard` (`ZeroDivisionError`), and `AssertStmt`
   (`AssertionError`). Each currently calls the one shared leave
   (`_emit_diverge` / `_flush_pending_finally` + exit); each needs one extra
   branch BEFORE that leave, to the innermost enclosing dispatch. The
   subscript, dict-key and `int()` sites need the same treatment and are the
   three that are easiest to miss — a partial set silently produces a program
   that catches `ZeroDivisionError` and not `IndexError`, which is worse than
   catching neither.
4. **The CFG**, in `formal/model.py::_build_cfg`'s `TryStmt` arm: run the
   handler bodies, add their exits to `arm_exits`, and delete the long comment
   that says they are not run. Re-measure `test_formal_read_before_store.py`
   (157 checks) and `test_formal_run.py` (1044) — the dominance answers are the
   thing that will move, and `every_handler_stores_is_dominating` is the row
   that will notice.
5. **`_HANDLER_ARM_NO_EFFECT` and `refuse_dropped_handler_arm`** stop applying
   to an arm the image now contains, and `build.py:15501`'s loop asks the new
   question instead. Keep the refusal for the arms that still cannot be
   emitted, and keep it naming the construct.
6. **The Lean model carries the exceptional exits.** This is the part with no
   scaffolding at all and it is the reason steps 1–5 are worth landing
   separately from it: `formal/arm64_proof_gen.py`'s semantic model has **no
   translation for a `TryStmt`** ("a TryStmt has no translation in the semantic
   model"), so `fire.py build --formal` REFUSES every program containing a
   `try` — measured, both backends. So today the unwinder would be a path with
   no proof behind it, and the project's own thesis ("one runtime, two code
   generators, one proof") would be further from true, not closer. The model
   needs the kind word as a function of the state, a `step` case for the store
   into it, and the dispatch's compares as `cbz` blocks the generator already
   knows how to close. **Until that lands, any unwinder here is unprovable and
   should say so in its own docstring.**

## 6. Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_exceptions.py
exceptions: PASS=198 FAIL=0 (198 checks)

# §3's census, over every .mojo file in the tree
$ python3 - <<'PY'
import sys; sys.path.insert(0, '.')
import fire_compiler as F, formal.model as M
n = free = 0
for root, dirs, files in __import__('os').walk('.'):
    dirs[:] = [d for d in dirs if d not in {'.git','build','.tmp','output','lib'}]
    for fn in files:
        if not fn.endswith('.mojo'): continue
        try: mod = F.Parser(F.py_tokenize(open(root+'/'+fn, encoding='utf-8', errors='replace').read())).parse_module()
        except Exception: continue
        for d in mod:
            if not isinstance(d, F.FunctionDef): continue
            found = M.unemitted_handler_arm(d)
            if not found: continue
            n += 1
            calls = [c.func.name for b in (found[2].body or [])
                     for c in M.iter_nodes(b) if isinstance(c, F.CallExpr)
                     and isinstance(c.func, F.IdentExpr)]
            free += not calls
print(n, 'arms,', free, 'with a call-free try body')
PY
5 1
```

## 7. What the three landed commits on this branch already changed, so a reader
## does not re-measure it

* `8a7666f5` — `raise` of an exception CLASS: the called and bare spellings of a
  builtin base, the bare spelling of a declared class, and `SystemExit`'s five
  status forms. Removed two refusals that named a symbol instead of the
  construct.
* `2a1b901a` — a float `/` by a zero divisor leaves with status 1. Was exit 0
  with `+inf`, i.e. a program that ran and was not the program written. Deleted
  the bug doc that recorded that divergence with the fix (commit 2a1b901a).
* `fd5a3934` — a failing `assert` runs its message and flushes the enclosing
  `finally`. Both were measured divergences from CPython on both backends.
* Plus `formal/model.py::integer_literal_value`, the one signed-literal reader
  the two backends' `_static_int` copies and `raise_exit_status` now share.