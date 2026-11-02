# A context manager's `__exit__` cannot take CPython's own three exception
# words, so every context manager written the way CPython writes one is refused

**Status 2026-10-27 (this tree): the 2026-10-12 slice below was measured MISSING
and is re-landed — the bulk merge of `work/formal318-docs` (2026-10-16,
`c3ed827a`) had kept the doc change and dropped the source commit (`08e5c803`),
keeping the prose and losing the fix.
Measured before: `context_exit_variadic_ignores` absent from `formal/model.py`,
`struct_is_context_manager` accepting arity 1 or 4 only, and
`test_formal_with.py` still carrying the pre-2026-10-12 `a_variadic_exit_is_
refused_by_name` row (the ignoring `*args` shape refused on a "1 parameters
after the receiver" sentence the parser's star-in-the-NAME made look like
arity 2). Re-landed, ported to the current tree: `formal/model.py` (`_dunder_
receiver_params` now reads the star through `function_param_shape`, the one
reader of the parameter list — `fire_compiler.py::_parse_funcdef` keeps the star
in the NAME and no `FunctionDef` has the `vararg` attribute the old code asked;
`context_exit_variadic_ignores` accepts the catch-all the body never reads; the
gate's `-1` arm; the named READ refusal for the catch-all, with `**kw` alone and
`(self, exc_type, *rest)` staying refused for the structural reason their
docstring states), `formal/build.py` (the exit-call comment: the variadic shape
is arity 1, its catch-all binding the empty tuple), and `test_formal_with.py`
(the two new ANSWERED rows, the re-worded refusal row
`a_variadic_exit_that_reads_its_catch_all_is_refused_by_name`, and the four
in-process gate checks). Measured 2026-10-27 in this tree:
`python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_with.py` is
**PASS=506 FAIL=0** (489 before the re-land; the 17 are the two rows plus the
five in-process checks), the two ANSWERED rows agree with CPython on both
engines, and the catch-all READ is refused by name on both backends. The
READING half — either spelling — is still §3's unwinder, unchanged.**

**Status 2026-10-12 (`work/formal318-docs`): the SECOND spelling of the ignoring
shape is now accepted too — `__exit__(self, *exc)` whose body never reads `exc`
lowers, because the catch-all was being refused for a reason that was never
true: `_dunder_receiver_params` read the star from `getattr(method, "vararg",
None)`, and no `FunctionDef` on this front end has that attribute (the parser
keeps the star IN the parameter name, `("*args", …)`), so the shape came out as
arity 2 and the variadic branch of `with_context_manager_defect` was dead code.
`function_param_shape` is now the reader, `context_exit_variadic_ignores` is the
predicate (`**kw` alone and `(self, exc_type, *rest)` stay refused for a
STRUCTURAL reason — CPython never calls either with the receiver alone — and a
read of the catch-all is refused by name, the variadic spelling of the read
refusal below). `test_formal_with.py` is **395 checks, PASS=395** (was 378): two
new ANSWERED rows run the same `*args` text on both engines, plus four
in-process gate checks and a re-worded refusal row.**

**Status 2026-10-07 (`work/formal104-docs`): the COMMON CASE is FIXED — a
`__exit__(self, exc_type, exc_val, tb)` whose body IGNORES the three words is
now a context manager this path lowers, so the most common `with` in real code
compiles verbatim. What remains is the narrow half that genuinely needs the
unwinder: a `__exit__` that READS any of the three words (fixed or variadic) is
still refused, by name, because there is no exception value to pass and a
fabricated one would be a lie the method then acted on.**

**2026-10-08 (`work/formal258-docs`): §4 item 3 — the alias-dispatched method
whose NAME a second struct also declares — is FIXED, and fixed for BOTH
spellings of the source (this branch added the second).** When the manager
ANNOTATES its `__enter__` result (`def __enter__(self) -> Res`),
`model.with_alias_struct` is the one reader of "what does the alias hold", the
`with` lowering publishes it (`formal/build.py::_one_with_item` →
`_rewrite_with_statements`' `alias_structs`), and `_prepare_functions` merges it
into the framed-receiver table `_rewrite_one_word_field_method_calls` reads, so
`v.m()` lifts from the alias's DECLARED type instead of being declined by name.
The other spelling — `__enter__` returning its own RECEIVER with no annotation —
was already closed by the holder round trip (`work/formal118-docs`,
`_rewrite_holder_method_calls`); §4 item 3 below carries both. What STAYS
refused is the `__enter__` that returns a bare WORD (`Ctx` returns `self.tag`):
there the source types nothing, so the ambiguity is real. Pinned by
`test_formal_with.py`'s `an_annotated_enter_publishes_the_alias_struct` (both
backends, CPython oracle) plus its in-process predicate checks and the DECLARED
row `a_method_through_the_alias_with_a_rival_owner_is_answered` — over the
merged tree the whole file is 387 checks, PASS=387 FAIL=0.

**What landed, and why it is not the signature change §3 warns against.** The
three words still have nowhere to come from; the fix does not invent them. It
distinguishes the shape that USES them from the shape that does not, and lowers
the second — the cleanup-only manager every temporary-directory and redirect
class writes. `formal/model.py`:

* `context_exit_ignores_its_exception_words(method)` — true for a four-parameter
  `__exit__` none of whose last three parameter names occurs anywhere in its
  body (walked with `iter_nodes`, so a read inside a nested `def` counts, and an
  assignment target counts too — the conservative direction).
* `struct_is_context_manager` accepts `__exit__` arity 4 exactly when that
  predicate holds, and is still the one gate.
* `context_exit_arity(struct_def)` — the ONE reader of "how many arguments the
  exit call passes" (1 or 4), so the gate and the call cannot disagree.
* `with_context_manager_defect`'s four-parameter arm now says the words are
  READ (the old wording, "this path calls it with the receiver alone", stopped
  being true once the ignoring shape lowered).

`formal/build.py::_one_with_item` passes the receiver plus three zeros for the
four-parameter shape, which is CPython's `None, None, None` on a normal exit
spelled as the only value this word-based model has for "nothing" — and nothing
in the callee looks at them.

**Measured, both architectures.** `python3 test_formal_with.py` — **352 checks,
PASS=352 FAIL=0** (was 336). Three new ANSWERED rows run CPython's own spelling
verbatim (the base protocol, a `return` out of the block, and a `raise` leaving
it, the last comparing exit status too), and the REFUSED row is now the READING
shape (`an_exit_that_reads_cpythons_three_words_is_refused_by_name`). The
in-process `check_the_exit_word_gate_is_about_reading_not_arity` pins the gate
and `context_exit_arity` directly, so a future edit cannot move the boundary
while the builds keep passing for an unrelated reason. `test_formal_run.py`'s
six `with` rows still pass, as do `test_formal_core_hostmods.py ctx`
(`nullcontext`) and `test_formal_tempfile.py`'s arm64 half.

**What is still not fixed, and it is §3's unwinder.** A `__exit__` that reads
`exc_type`/`exc_val`/`tb`, and a computed return value CPython reads as a
suppression (`FORMAL_a_with_exit_whose_value_is_computed_can_suppress.md`), still
need steps 1-3 below. This change is the "drop the exception arguments"
workaround §3 points the reader at, applied by the COMPILER instead of by the
reader, and it is safe precisely because the arguments are provably unused.

**Area:** FORMAL, context managers. Claim `project:with-statements`, measured
2026-10-05 on `work/formal56-with-statements`. **PARTIAL: the §4 alias-dispatch
limit is CLOSED (2026-10-07, `work/formal118-docs`); the three-exception-word
signature below is still OPEN**, because it needs the unwinder. One of three
limits this project measured and did not close; the other two are
`FORMAL_a_with_exit_whose_value_is_computed_can_suppress.md` (the narrow half of
the same missing unwinder, which IS now refused when the value is foldable) and
the alias-dispatch note in §4, which is no longer one of them.

**Read this before planning the rest of the work.** What is left is the
unwinder, and §3 is why the same missing unwinder is
the stated reason `try`/`except` arms are refused too
(`FORMAL_a_try_handler_arm_is_still_never_emitted.md`, which measures that half
as worth **zero files in this repository**).

## 1. What the backends do today, measured

`--no-prove`, both architectures, on this branch, CPython as the oracle. The
reproduce line is one file and one program:

    python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build \
        --formal --no-prove -o .tmp/e3 -n 3 .tmp/doc/exit3.mojo

with `tmp/doc/exit3.mojo` the `class ThreeArgs` of §2.

**ANSWERED, both backends, and the same answer as CPython** — every spelling
whose `__exit__` takes the receiver alone. `test_formal_with.py`'s 28 ANSWERED +
6 DECLARED + 3 resource rows are all of them, and it is the table to read for
what this path already honours: the enter/body/exit order, the alias binding
`__enter__`'s RESULT rather than the context, one/two/three items (left in,
right out), an item with no alias between two that have one, nesting,
`return`/`break`/`continue` out of the block, an exception leaving the block, an
exception leaving two items, `__enter__` raising (the exit must NOT run),
placement in an `if`, two `with`s in a row, and the RESOURCE arm
(`with open(...)`, whose bytes on disk are compared as well as its stdout).

**ANSWERED since 2026-10-05, and this is where the project's slices went** — the
`with` context may now be named four ways, each answered from a type the source
DECLARES, through the one reader a field access already uses
(`model.receiver_struct`):

| context spelling | evidence | before |
|---|---|---|
| `with Ctx() as v:` | a construction the source wrote | answered |
| `with mgr as v:` for `mgr = Ctx()` | the binding, agree-or-refuse | **refused** |
| `with make() as v:` for `def make() -> Ctx` | the callee's declared `-> T` | **refused** |
| `with self.mgr as v:` for `var mgr: Ctx` | the field's declared type | **refused** |
| `def use(c: Ctx): with c as v:` | the parameter's annotation | **refused** |

**ANSWERED since 2026-10-07, and this is what the fix added** — the shape the
document is named for, when the body does not read the words:

| construct | evidence |
|---|---|
| `__exit__(self, exc_type, exc_val, tb)` that ignores them | no read of any of the three parameter names in the body |
| `__exit__(self, *exc)` that ignores `exc` | no read of the catch-all name in the body (2026-10-12) |

**REFUSED, and this is what is left** — the same signature when the body READS
a word:

| construct | the refusal |
|---|---|
| `__exit__(self, exc_type, exc_val, tb)` whose body reads `exc_type`/`exc_val`/`tb` | "its `__exit__` takes CPython's three exception words and READS them … there is no exception value, no traceback and no type word to pass, so any value this path supplied would be a lie the method then acted on" |
| `__exit__(self, *exc)` whose body reads `exc` | the same sentence through the variadic spelling: "takes CPython's three exception words through a variadic `*exc` and READS it … there is no exception value, no traceback and no type word to pass" (2026-10-12) |

The wording is itself part of what this branch fixed: until 2026-10-05 the same
program was told "**it declares no `__enter__`**", which is FALSE about a class
that has one, and it sent the reader to add a dunder they already had. That
sentence was the FIRST refusal a reader of real code met, because that signature
is what every context manager in the wild writes.

## 2. The reproduction

    class ThreeArgs:
        def __init__(self):
            self.tag = 7
            self.log = 0

        def __enter__(self):
            print('enter')
            return self.tag

        def __exit__(self, exc_type, exc_val, tb):
            print('exit')

    def main(n):
        with ThreeArgs() as v:
            print('body', v)
        print('after')
        return 0

CPython: `enter / body 7 / exit / after`, exit 0. This path **now answers the
same thing, exit 0**, on arm64 and on x86-64 — this is the exact reproduction
the ANSWERED row `an_exit_that_ignores_cpythons_three_words_runs_the_protocol`
in `test_formal_with.py` runs, CPython's own spelling verbatim. Before
2026-10-07 it was **exit 1** with the refusal above, on both architectures
identically; adding a single read of `exc_val` to the body still restores that
refusal, by name.

## 3. What closing it needs, and why it is not a signature

CPython's `__exit__` receives three words describing the exception in flight.
Answering them needs a representation for an EXCEPTION — and this backend has
none, which is the same fact `arm64_codegen.py::_emit_raise`'s docstring states:
`raise` "leaves the process" after running the enclosing `finally` clauses, and
there is "no handler in the image to bind one to". So:

  * **the three words have nowhere to come from.** There is no exception value,
    no traceback, and no type word to pass. Emitting three NULs would make a
    `__exit__` that READS them act on a lie, which is worse than refusing.
  * **the RETURN VALUE is the same missing runtime from the other side.** CPython
    reads a true `__exit__` return as SUPPRESS the exception and continue after
    the block; a `raise` here leaves the process, so there is no continuation to
    branch back into. A signature change without this would turn a refusal into
    the wrong answer the sibling document measured: cleanup runs, every printed
    line matches CPython, and the statements after the block never happen.

So the two halves must land together, and the honest order is:

1. **an exception representation** — at minimum a status word saying "an
   exception is in flight", because that is all the *suppression* half needs;
2. **a resume edge** — the raise site must be able to branch to the statement
   after the `with`'s `finally` when the clause's value says "suppress", which is
   a change in `_flush_pending_finally`'s contract in BOTH emitters (it currently
   truncates the stack and runs the clause, with no value and no successor);
3. **then** the three words, which need a real exception VALUE to be worth
   anything — and at that point `FORMAL_a_try_handler_arm_is_still_never_emitted.md`
   becomes cheaper, because a raise site finally has somewhere to route to.

Steps 1 and 2 are the work; step 3 follows. The Lean side is not the hard part
here — `_leaves_early` in `formal/model.py` already models the finally clause as
reached from every early exit, and a suppression edge is one more successor to
prove — but both emitters and the CFG have to grow it together, and the two
architectures must not be able to disagree about whether the resume happened.

## 4. What is measured, refused and NOT wrong — the boundary to keep

Three shapes stay refused, each with a row in `test_formal_with.py`, and the
second is the same missing unwinder seen through a narrower door:

  * a `with` over a value no DECLARED type names — a callee in another module or
    a dylib, an unannotated field, an unannotated parameter, a name bound to two
    layouts, a binding made in a nested `def`;
  * an `__exit__` that returns a FOLDABLY truthy value (`return True`, `return 1`)
    — refused, because that is a suppression this path cannot perform, and
    before 2026-10-05 it was a wrong answer (`__exit__`'s return value was
    dropped on the floor). See
    `FORMAL_a_with_exit_whose_value_is_computed_can_suppress.md` for the
    remaining half of that;
* ~~a method call through the alias whose NAME a second struct also declares.~~
    **CLOSED 2026-10-07/2026-10-08 — two publications, one per spelling of the
    source.** The alias binds whatever `__enter__` returns, and there are two
    ways the source states what that is; BOTH are published into
    `formal/build.py`'s framed-receiver table now. (1) **The receiver round trip**
    (2026-10-07, `work/formal118-docs`): the alias is bound to `S.__enter__(tmp)`,
    and when `__enter__` returns its receiver that call is a frame-returning
    call, so the holder fixpoint already knows the alias is an `S` — this is
    `Box.__enter__` returning `self` with no annotation.
    `_rewrite_holder_method_calls` runs beside `_rewrite_nested_method_calls`
    against the same `by_name` table and lifts the bare-name receiver the
    name-only dispatch declined, with `_derived_overrides`'s guard copied so a
    child that overrides the member is still refused. (2) **The declared result
    type** (2026-10-08, `work/formal258-docs`): the manager that ANNOTATES
    `def __enter__(self) -> Res` writes the type down, `model.with_alias_struct`
    reads it out of the source, `_rewrite_with_statements` carries it out of the
    `with` lowering (`alias_structs`), and `_prepare_functions` merges it into
    the same table — but only where the name has no OTHER binding
    (`_bound_receiver_structs`/`one_word` win), because two layouts under one
    name is the ambiguity that table already drops rather than picks.
    `test_formal_with.py`'s
    `a_method_through_the_alias_with_a_rival_owner_is_answered` is the row (it
    moved from the REFUSED table to the DECLARED one, against CPython on both
    architectures), and `an_annotated_enter_publishes_the_alias_struct` is the
    in-process check that keeps the annotation predicate honest even while the
    build passes for another reason. `test_formal_run.py`'s
    `ambiguous_name_a_derived_struct_also_declares_is_still_refused` still pins
    the one clause that must not be waived. What stays refused is the
    `__enter__` that returns a bare WORD (`Ctx` returns `self.tag`): there the
    alias genuinely has no type, and a wrong layout stays unreachable.

## 5. The reproduce line for the whole table

    python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_with.py

387 checks, both architectures (measured 2026-10-10, after the merge that
brought the second publication in). §1's "ANSWERED" rows are its ANSWERED +
DECLARED + resource rows; §4's remaining shapes are among its REFUSED rows. The
former two-owner alias row is DECLARED, not refused, and it is now answered
through both publications: the `Box` receiver round trip (holder analysis) and
the `Holder` manager's own `-> Holder` annotation.
