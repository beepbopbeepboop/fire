# A `try` handler arm is still never emitted, and the reason it is not worth
# fixing in one function is that EVERY arm in this repository calls something

**Area:** FORMAL, exceptions. Claim `project33:exceptions`, measured 2026-10-05
on `work/formal33-exceptions`. **OPEN, with §5 step 1 ANSWERED (2026-10-06,
`work/formal40-2`) and §5 step 2 LANDED (2026-10-05, `work/formal40-2`).** The
uncaught half of the exception contract landed on that branch (three commits:
`raise` of a class leaving with CPython's status, a float `/` by a zero divisor
leaving, and a failing `assert` running its message and its enclosing `finally`)
and this is the remainder.

**§5 step 1 is DONE — both of §4's design questions are answered, and one of the
answers came with code and a hole in the design it corrects.** §4 asks for the
superclass question and the `as e` question; the answers are in **§4a** (the
kind word grows a base relation, and here is the comparison list it compares
against, with the three cases that make that list undecidable) and **§4b** (`as e`
is refused until the exception has a representation). **Both answers were
measured against CPython over every ordered pair of its 71 exception names —
5041 comparisons — and the first version of the matcher disagreed on 36 of
them**, all under the two names that are aliases of `OSError`. Steps 3, 4, 5 and
6 are untouched and no emitter reads any of it yet.

**And the answer carries a correction to step 2, which is the more useful half.**
The two disjoint ranges make a **BUILTIN**'s integer image-independent; they do
**not** make a **declared** class's integer image-independent, because the
declared range is numbered by sorted name over the declared SET and a dylib and
its caller declare different things. That is not a defect in the landed table —
its docstring claims the builtin property and only the builtin property — but it
does mean an image that declares an exception class cannot give an
`except Exception:` arm a compare list that means the same thing in both images.
§4a says what the emitters must do about it, and it is a refusal rather than a
number.

**§5 step 2 is done and it is shared infrastructure that fixes nothing by
itself** — which is what §5 said it would be, and it is landed separately for
that reason rather than as a claim of progress. `formal/model.py` now has the
kind table: `exception_kind_table(structs)` builds it,
`publish_exception_kinds` / `exception_kinds` / `clear_exception_kinds` are the
per-image trio beside the other two, `formal/build.py::_prepare_functions`
publishes it at the point `structs_by_name` is first complete, and **both**
emitters put `M.exception_kinds()` into `info["exception_kinds"]` so the two
proof generators read one list rather than one each. **Nothing reads the table
yet**; steps 3, 4, 5 and 6 are untouched and §4's design questions are answered
in §4a and §4b rather than open.

**The one design decision this step had to make, and it is not §4's two:** the
numbering has to survive an image DECLARING a class, because a dylib and the
executable that links it are two `_prepare_functions` runs with different
declared sets and the same CPython half — so a word written by the library would
mean nothing in the caller's image. Measured on the first version of the
function, which numbered one sorted set: declaring `MyErr` moved `ValueError`
from 38 to 69. The two ranges are therefore disjoint (`CPYTHON_EXCEPTION_BASES`
at 1..N by sorted name, the image's own classes at N+1.. by sorted name), 0 is
reserved for "no exception in flight", and a declared name that shadows a
builtin keeps the builtin's integer. Pinned in
`test_formal_exceptions.py::kind_table_checks` (14 pure-function rows, no build
and no Lean) and `::kind_table_in_info_checks` (which reads it out of the
`(code, info)` pair each backend's `compile` RETURNS, so the claim is about what
a proof generator is handed). That file is 228/0, up from 198.

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

## 4a. §4's SUPERCLASS question, answered (2026-10-06) — the word grows a base
## relation, and here is what the dispatch compares against

**The decision: the kind table grows the base relation. The word does NOT become
a pointer.** §4 offers the two as alternatives and this is the first.

* **The word has to stay one word.** It is written by a callee into its own
  frame and read by a call site that must also leave the value in the return
  register, so a second return value is not available — §4's own reason for a
  word rather than a pair, and it does not change under this decision.
* **A pointer takes on §4's THIRD question at the same time**, which is how a
  design ends up with two unsolved halves instead of one solved one. `except A
  as e:` needs an object to bind, an object is a FRAME on this path
  (`model.BUILTIN_EXCEPTION_FIELDS` is `("args",)`), and one per raise site is a
  `_blob_cap` question.
* **The base relation is a BUILD-TIME fact on both halves**, which is what makes
  the word enough: CPython's hierarchy is a constant of the interpreter
  (`model.CPYTHON_EXCEPTION_BASE`, generated from it the way
  `CPYTHON_EXCEPTION_BASES` was), and a class this image DECLARES has a base the
  source writes down.

**The two functions, and why there are two.** Both are in `formal/model.py`, both
are pure, and both are pinned by `test_formal_exceptions.py::
handler_arm_matching_checks` (13 checks, no build and no Lean).

| | the question | answers |
|---|---|---|
| `handler_arm_matches(arm, flying)` | **what CPython would do** | `True` / `False` / `None` |
| `handler_arm_kinds(arm)` | **what the image can compare** | a `frozenset` of kinds, or `None` |

**They are separate because they have different answers for the same input**,
which is the whole reason §4's question had two halves and not one:

* `except ArithmeticError:` catches `ZeroDivisionError` — so the arm has to know
  about **DESCENDANTS** of itself. An ancestor walk answers the opposite
  question. Measured: all 71 arms disagree with CPython's descendant sets if
  the walk goes the other way.
* **`True`/`False` need only the RAISED class's chain**, never the arm's own
  ancestry — the test is membership of the arm's NAME in it. So an arm whose own
  base is unmodelled is still decidable as a source question.
* **`False` is not always available.** `except Exception:` does not catch a
  `class Mine(External)` whose own bases nothing here knows, and answering
  `False` there would drop an exception CPython catches. That case is `None`,
  and `None` means REFUSE, never "no match".

**Three cases make `handler_arm_kinds` answer `None`, and each is a refusal the
emitters must implement rather than a gap to note:**

1. **an unmodelled base** in the chain — §4's third bullet, now a refusal rather
   than an unmatchable kind;
2. **a class the image cannot name at all**;
3. **a DECLARED class with a DECLARED subclass** — the correction to step 2, and
   the only one that is a surprise. The declared range is numbered by sorted name
   over the declared SET, so a dylib (which declares `Mine`) and an executable
   (which declares `Mine` and `Other`) number `MineSub` differently, and a
   compare list built from one image's declared subclasses means something else
   in the other. A CPython arm is safe from this by construction: its whole
   descendant set lives in `CPYTHON_EXCEPTION_BASE`.

**The alias, which is the thing a reader would not have predicted.** CPython's 71
exception NAMES are **69 class objects**, and `EnvironmentError` and `IOError`
ARE `OSError`. `issubclass(BlockingIOError, IOError)` is therefore True, and a
NAME hierarchy that does not canonicalise answers `False` for all 18 of `OSError`'s
subclasses under either alias. Measured over every ordered pair of the 71 names —
5041 comparisons — **36 disagreements before `model.CPYTHON_EXCEPTION_ALIAS`, 0
after.** A DECLARED `class IOError(...)` is deliberately NOT canonicalised: it is
a different class from the builtin of that name, and `raise_class_name` already
gives a declaration precedence for the same reason.

**What `except BaseException:` now costs, measured:** one compare per kind, 71
of them. §4 says this arm is the commonest in real code and cannot be left to
the cheap version, and this is the measurement that says the cheap version gets
it right anyway — the whole list is a build-time constant of the interpreter.

## 4b. §4's `as e` question, answered (2026-10-06): REFUSE, until the exception
## has a representation

**The decision: `except A as e:` is refused while `e` would have a value.** The
three options §4 lists are bind `e` to the word, refuse the arm, or give the
exception a representation, and it is the second — with the third named as the
work that lifts it.

* **Binding `e` to the kind word is the wrong answer and this project has a rule
  about it.** `str(e)` is the first thing anybody writes in an arm, and a
  convention where `e` is an integer prints a number where CPython prints
  `IOError: [Errno 2]`. That is `bugs/FORMAL_string_value_model.md`'s class: the
  question is what the path does when the source says something the word cannot
  hold, and the answer must not be a plausible number.
* **The representation is close and is not a code question.**
  `model.BUILTIN_EXCEPTION_FIELDS = ("args",)` already gives every builtin
  exception class a one-word slot for its message, so an object is not far away —
  but a class with an `args` slot is a FRAME on this path, and copying one per
  raise site is a `_blob_cap` question. That is §5 step 6's neighbour and it is
  worth doing **with** the unwinder rather than before it.
* **So the refusal names the construct, not a symbol**, which is the rule the
  two landed commits above already follow, and it goes in beside
  `model.refuse_dropped_handler_arm` rather than replacing it: the arm with no
  binding is emittable and the arm with one is not.

**What this does NOT decide:** whether the exception object is a one-word cell
with an `args` word in it, or something with a message buffer. §4's third option
is still open and it is the frame-budget project.

## 5. The exact next steps, in order

1. ~~**Decide §4's superclass question and the `as e` question.**~~ **DONE**
   (2026-10-06, `work/formal40-2`): **§4a** and **§4b** above. The superclass
   answer is `model.exception_base_chain` / `handler_arm_kinds` /
   `handler_arm_matches`, pinned against CPython's own `issubclass` over all
   5041 ordered pairs of the 71 names, and the `as e` answer is a refusal to
   write when step 3 lands. **The emitters' step 3 must implement the three
   `None` cases in §4a as refusals**, because a dispatch that treats one as a
   non-match is the failure §4a was written to prevent.
2. ~~**The kind table** in `formal/model.py`: `{class name -> integer}`, from
   `CPYTHON_EXCEPTION_BASES` plus this unit's declarations, published in
   `info` so both emitters and both proof generators read ONE list. This is
   shared infrastructure and fixes nothing by itself — it is worth landing on
   its own and saying so.~~ **DONE** (2026-10-05, `work/formal40-2`): see the
   Status. `model.exception_kind_table` + the publish/clear trio, published in
   `_prepare_functions` where the image's own class names are first complete,
   and `info["exception_kinds"]` in BOTH emitters. The numbering is two
   disjoint ranges rather than one sorted set, which the Status measures and
   explains: a dylib and its caller are two images with different declared
   sets, so a single sorted set made `ValueError` mean 38 in one and 69 in the
   other. **§4a adds the limit of that fix: it makes a BUILTIN's integer
   image-independent and does not make a DECLARED class's.**
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