# RUNTIME: an int64 dict key in [2^31, 2^47) is dereferenced as a `char *`

## Status (2026-10-03, `work/bugs-segfaults-r2` — the ARITHMETIC producers and
## the other dict consumers; the PREDICATE is still unchanged and
## `ptrreg-boxed-str` is still red)

`_int_word_vals` was seeded only by `_lower_IntLiteral` and carried across
assignments, so `d[base + 1]` was still a `SIGSEGV`: the key is a FRESH TEMP
holding an arithmetic result, which nothing had ever recorded, so the dict site
fell back to the `_kw` twin and `mojo_dict_set_int_kw(d, 3000000001, "x")` was a
`strcmp` of address 3000000001.  Measured as SIGSEGV on the parent commit for
`d[base + 1]`, `d[i * 3]`, `d[i - 2]`, `d[-1]`, `d[~n]`, `d[base << 1]`,
`d[m % 4]` and `d[6000000000 // 2]`; all eight match CPython now.

Three producers were needed, because there are three distinct losses between
the literal and the key, and only the first is the one this doc's earlier
"exact next step" named:

* **the arithmetic RESULT** — `_lower_binary_tail`'s generic numeric tail and
  `_lower_UnaryOp`'s `-`/`~`.
* **the operand-WIDENING cast the tail emits immediately before it.** This is
  the one that is easy to miss and the reason a two-operand rule alone fixes
  nothing: `base + 1` lowers its literal `1` to an `int64_t` temp through
  exactly that block, so a rule keyed on the operands of the arithmetic marks
  NOTHING and `d[base + 1]` keeps crashing while `d[-1]` is already fixed.
  Measured, not assumed — the first version of 773080f9 fixed the small-key
  cases and left this one segfaulting, which is why the carry exists.  It is
  the same carry `_track_pointer_actual_type` already does across an
  assignment, guarded on the SOURCE type being a plain integer, because a
  `char *` operand joined to a scalar is the boxed-pointer reinterpretation
  that must not be marked.
* **`//`**, which `_lower_binary` dispatches BEFORE the tail, so
  `d[6000000000 // 2]` needed its own producer at `_lower_floordiv`.

The rule is stated ONCE, in `_INT_ARITH_OPS` + `_mark_known_int`
(`mojo/backend_gimple/emit_exprs.py`), rather than as a list of hand-edited
sites, because the argument for adding a producer is monotone safety and that
only holds if the rule has one home: the result's C type must be a plain
integer, and every operand must already be recorded.  A miss falls back to the
runtime's own discriminator — exactly today's behaviour — so a
wrongly-narrowed producer costs a missed optimisation and never a crash.

`+=`, `.get` (with and without a default), `in`, `.pop`, `.setdefault`, a dict
LITERAL with a computed key, and `sorted(d.keys())` are separate consumers, not
all of them the subscript store, and all of them SIGSEGV'd before the fix.

**Not covered by the new cases, and named so it is not mistaken for covered:**
neither reaches `d[f()]` or the `char *`-declared-local shape, because both are
still `SIGSEGV` and a test that asserts a crash is not a regression test.

## Status (2026-10-02, later — the STORE side too: every hop a value takes
## toward a dict key now carries the record; the PREDICATE is still unchanged
## and `ptrreg-boxed-str` is still red)

Three commits, in the order the evidence forced them. **Read item 1's "the
third loss" before touching anything else — it is the one that is easy to
miss and it is why a two-operand rule alone fixes nothing.**

0. **2026-10-03: the ARITHMETIC producers and the other consumers.**
   `_lower_binary_tail`'s generic numeric tail, `_lower_UnaryOp`'s `-`/`~`, and
   `_lower_floordiv`'s integer arm all record their result, plus the
   operand-WIDENING cast the tail emits just before it — see the Status section
   above, which is where the third loss is argued, because it is the one that
   makes a two-operand rule alone mark nothing.  The rule lives once, in
   `_INT_ARITH_OPS` + `_mark_known_int`.  Then the eight other dict entry
   points, which are separate consumers rather than the subscript store.

   - `test_gimple_runner.py`'s `gimple_dict_key_computed_is_still_an_integer`
     and `gimple_dict_key_computed_reaches_every_dict_consumer` — all eight
     arithmetic spellings and all eight other entry points, both pinned to
     CPython, plus the string half that is the producer's soundness contract.
     SIGSEGV (exit -11, empty stdout) with the codegen hunk reverted.

1. **2026-10-02: two more producers for `gen._int_word_vals`,** so the
   "monotone-safe, pure gain" argument below has two more instances of it.
   `_lower_UnaryOp` records `-n` / `~n` on an operand already recorded, and
   `_lower_binary`'s arithmetic tail records an integer result from two
   operands already recorded. Neither involves inference, which is the whole
   reason they are safe: a miss falls back to the runtime's own discriminator,
   never to a crash. (Both were later re-expressed through
   `_mark_known_int`, which is the same rule with one home.)

   - `test_gimple_runner.py`'s `gimple_computed_dict_key_above_2gb_is_
     integer` — four shapes, one per way a large key can be *computed* rather
     than written: `i + 1` from a large literal, `-1`, literal + literal, and
     a small local times a large literal. `-1` is in the list because a
     negative word is OUTSIDE the predicate's window (a huge `uint64`), so the
     crash there is in the assignment rather than the lookup, and it is the
     shape that would pass a test written only for the positive range.

2. **2026-10-02: the STORE side.** What item 1 leaves out is the other
   direction — a large key that is ASSIGNED to a name. The record died on three
   hops, each an existing shared helper that simply did not carry this one
   table: `_gen_stmt_AugAssignStmt` (`k += 1`), `_gen_stmt_VarDecl`
   (`var k = 3000000000`), and `_note_global_store_types` plus
   `_lower_IdentExpr`'s global-read arm for a module-level `K`. The read arm is
   the least obvious of the three: reading a global mints a FRESH temp, the
   dict-key decision is keyed on the value it was handed, and a record that
   stops at the temp is no record at all.

   Three more producers, none of which involves inference: `_lower_floordiv`'s
   integer arm (`//` never reaches the binary tail, where `%` and the
   arithmetic operators are covered), `_lower_pow`'s integer arm (the `(int)`
   cast the lowering already performs makes the result an integer for EVERY
   input, which is the strongest form of the argument available, and `**` is how
   a large key is usually COMPUTED — `3 ** 20` is 3486784401), and
   `_lower_TernaryExpr` over two known integers, gated on BOTH branch types
   being integer-shaped and not on the joined `res_type`: `_quick_type`
   estimates without evaluating, so a branch that really lowers to a pointer
   can join to `int` and be truncated to an address. Measured, not assumed:
   `d[x if flag else "s"]` still takes the runtime's own path, as it must.

   `k = "s"` clears the record (the chokepoint's `discard` branch), which is
   what keeps the carries sound; the new test pins that direction by putting a
   string in the same slot and requiring it to stay a string key.

   - `gimple_assigned_large_dict_key_survives_every_store_shape` (`+=`, `//`,
     `**`, a ternary, a `var`, and the string direction) and
     `gimple_module_scope_large_dict_key_survives_the_global_store` (both
     declaration spellings at module scope). Both are SIGSEGV (exit -11) on the
     parent commit; the second printed NOTHING at all.

3. **The 2026-10-01 work (e701f33a, a9c78439), still in place.** `_actual_types`
   records "this int64_t slot really holds a pointer"; `gen._int_word_vals` is
   its exact complement, "this value holds a plain Python integer". It is
   seeded in `_lower_IntLiteral` (an integer literal cannot be a pointer at
   ANY magnitude — no inference, no guess) and carried across assignments in
   `_track_pointer_actual_type`, the single chokepoint both the `VarDecl` and
   the plain-`AssignStmt` paths already use for exactly this kind of
   side-table carry, and which DISCARDS on an RHS the codegen cannot vouch
   for. That is what keeps it sound rather than optimistic: `k = 3000000000`
   marks `k`, `k = "s"` unmarks it.

   Two consumers:
   - `_char_to_cstr`'s `word_ok` branch — a dict-key site whose key is a known
     integer now renders its decimal with the new `mojo_int_str_transient` and
     uses the ORDINARY dict entry point, instead of handing the raw word to the
     `_kw` twin for the runtime to classify. Not a demotion: the dict
     re-normalises the text through `_canon_int`, so `d[5]` and `d["5"]` stay
     the one integer slot they have always been.
   - `_emit_call`'s `char *`-parameter coercion — there a known integer goes
     through `mojo_str_from_int`, which is the KEPT variant, because the
     callee may store the pointer. That half landed as a9c78439, which fixed
     the annotated-`str`-parameter SIGSEGV and deleted its doc; naming the
     commit rather than the doc, since a deleted doc is a citation with no
     referent.

   `mojo_int_str_transient` is `_int_str_transient` published under a name
   that states the answer the caller already has: same block, same pool, same
   release protocol as `mojo_cstr_or_int_str`'s own integer half. It is not a
   second implementation.

4. **`ptrreg-boxed-str` is still red, correctly**, and re-measured on
   2026-10-03 in the same state: 3 of 3 configurations fail on the first
   assertion, `mojo_boxed_is_str(big[i]) == 0`, at -O0, -O2 and under ASan.
   The group asserts the PREDICATE ITSELF becomes right. It does not, and by
   this doc's own argument below it cannot: the shape test is
   information-theoretically unable to separate an integer from a pointer.
   Nothing in items 1-3 touches the predicate, deliberately. So the `expect=`
   marker stays, and this doc stays.

### What is NOT fixed

Re-measured 2026-10-03, with the two that the earlier revision of this
section lumped together now separated, because one is a next step and one is
a wall:

1. **A value from a call the codegen cannot type: `d[f()]`.** `def pick(n):
   return 3000000000 + n` then `d[pick(0)] = "x"` is a `SIGSEGV`. The return
   value of an unannotated function is an `int64_t` with nothing recorded
   about it, and nothing downstream can know it. This is the same wall an
   unannotated/erased parameter and a value read out of a heterogeneous
   container hit, and it needs real inference — `mojo/middle/`'s to own.

2. **A local whose C declaration is `char *` because of a LATER assignment,
   which earlier held a large integer.** Measured `SIGSEGV`:

       d = {}
       k = 3000000000
       d[k] = "big"       # mojo_dict_set_str (d, k, _t4) with k = (char *)3000000000
       k = "3000000000"

   `_declare_var` is first-decl-wins, so `k` is declared `char *` by the
   string on the last line, and the store on the first casts the integer's
   bits into it. The crash is NOT the `_kw` twin and NOT `mojo_boxed_is_str`:
   the generated C has no discriminator call at all, because `_char_to_cstr`
   short-circuits on `typ == 'char *'` before any of that. The codegen DOES
   have the answer — `k` is in `_int_word_vals` at that point — and the
   obvious fix is to consult it there.

   **It is not fixed here, and the reason is the specific failure mode, not
   the effort.** `_mark_known_int`'s fail-safe argument covers PRODUCERS: a
   miss falls back to today's behaviour. It does NOT cover a new CONSUMER
   reading a `char *`-typed name, because there a stale mark is a SILENT
   wrong answer instead of a crash — the outcome this codebase consistently
   rates as worse. And the discard discipline is not yet universal:
   `_track_pointer_actual_type` is reached from the plain-`AssignStmt` path
   (`emit_stmts.py:1311`) and the tuple-`VarDecl` path (`:405`), and NOT
   from a `for k in [...]` target rebinding, so

       k = 3000000000
       for k in ["a", "b"]: s[k] = 1

   would leave `k` marked while it holds a string. That program is correct
   today (nothing consults the set for a `char *`), which is exactly why the
   hazard is invisible until someone widens the consumer.

   So the next step is to make the discard complete for every rebinding path
   FIRST, and only then widen `_char_to_cstr` — in that order, because the
   other order produces a silently wrong dict key on a program that works
   today.

### Exact next step

Two directions, and they are genuinely different jobs:

* **Widen `_int_word_vals`.** Every additional producer is monotone-safe — a
  miss falls back to today's behaviour, never to a crash — so this is pure
  gain.  DONE, in this order: `_lower_IntLiteral` (the seed),
  `_lower_binary`'s arithmetic tail and `_lower_UnaryOp` (`-n`, `~n`) plus the
  widening cast between them, the store side (`x += e`, `var x = e`, a
  module-global store and a global read-back), then `_lower_floordiv`,
  `_lower_pow`'s integer arm and `_lower_TernaryExpr`.  See the Status
  sections at the top for each one's shape and the tests that cover them.

  `_lower_percent`'s generic numeric arm needed nothing: it returns a `None`
  sentinel and the caller falls through to `_lower_binary_tail`, which the
  arithmetic producer already covers.  (`%` was therefore never actually
  missing — worth recording, because the doc listed it as work and the honest
  answer is that it was covered by a different site.)

  Deliberately NOT one of them, still: `_lower_CompareChain` (a comparison
  yields a `_Bool`, not an int64 word).

  **The remaining producer, and the exact shape of it:** a call whose return
  this codegen can vouch for.  `func_return_types` cannot answer that question
  on its own, and the reason is structural rather than a missing entry — it
  mixes DECLARED types with INFERRED ones and with the erasure default, and all
  three are spelled `int64_t`.  The table is written from
  `module_gen.py`'s own two places:

  * `func_return_types[s.name] = self._resolve_type(s.return_type)` — an
    ANNOTATED return (`def f() -> Int:`).  Real evidence, and it is the one
    case worth doing first.
  * `func_return_types[s.name] = inferred` where `inferred =
    self._infer_return_type(s.body)` — an inference over the body.  Evidence
    only when the body's own literals are integers, which is a second
    question, not this one.
  * every `.get(mangled, 'int64_t')` at a call site — the ERASURE, which is
    precisely the case that must NOT be evidence, and which is also what makes
    "is it in the table" the wrong question.

  So the work is a second table written only by the first of those three, and
  a producer at the call site gated on it.  Note `_resolve_type` is not enough
  on its own even there: an annotation of `Any`/`object` also resolves to
  `int64_t`, so the gate has to read the ANNOTATION's own name, not its
  resolved C type.

  **The `char *`-declared local, and it is a separate piece of work from all
  of the above:** (a) route every rebinding through the discard — `for` targets,
  augmented assignment, `with ... as`, parameters, struct fields — and pin each
  with a test that a name marked as an integer and then rebound to a string
  still compares equal to that string; (b) then consult `_int_word_vals` in
  `_char_to_cstr` for a `char *`-typed value.  (a) is a real correctness
  prerequisite for (b), not tidying.

  Still unhandled after all of that, and still `mojo/middle/`'s to own: an
  unannotated/erased parameter, a value read out of a heterogeneous container,
  and `d[f()]` for a call whose return cannot be vouched for.
* **Make the predicate sound**, which means giving the runtime provenance
  rather than a range: a registry of every string the program can hold, fed by
  the runtime's own string constructors AND by codegen for its string-literal
  pool. That is a real design change with a real failure mode of its own — a
  string built somewhere un-registered becomes a SILENT wrong answer rather
  than a crash, which this codebase consistently rates as the worse outcome —
  so it wants its own investigation, not a drive-by.

## Original report (2026-09-30)

A program that uses a large integer as a dict key segfaults. Reproduced in the
runtime unit test, at -O0, -O2 and under AddressSanitizer:

    d = {}; d[3000000000] = 1        # SIGSEGV

Found while adding the float-key pool regression to `test_ptr_registry.py`, and
reported by name as that harness's `boxedstr` group — the registered
`ptrreg-boxed-str` test, `expect=`'d. It is a **pre-existing** bug, unrelated to
the float/pool work that surfaced it.

## Cause

`mojo_cstr_or_int_str(int64_t v)` (runtime/fire_runtime.c) has to answer "is
this word already a boxed `char *`, or an integer that needs a decimal?". It
delegates to `mojo_boxed_is_str`, which is

    _mojo_ptr_shaped(v) && !mojo_is_registered_list(v) && !mojo_is_boxed(v)

and `_mojo_ptr_shaped` (runtime/fire_runtime.c:904) is **range-only**:

    static int _mojo_ptr_shaped(int64_t addr) {
        uint64_t u = (uint64_t)addr;
        if (u < 0x80000000ULL) return 0;          /* below 2^31 */
        if (u >= 0x0000800000000000ULL) return 0; /* at/above 2^47 */
        return 1;
    }

So every **positive** `int64_t` in `[2^31, 2^47)` is classified as a pointer. A
plain integer in that window is then cast to `char *` and handed to `strcmp` /
`strlen`, and the process dies. Confirmed misclassified:

| value | hex | `mojo_boxed_is_str` |
|---|---|---|
| 2147483648 | `0x80000000` | 1 → crash |
| 3000000000 | `0xb2d05e00` | 1 → crash |
| 4294967296 | `0x100000000` | 1 → crash |
| 1099511627776 | `0x10000000000` | 1 → crash |
| 70368744177664 | `0x400000000000` | 1 → crash |
| 2147483647 | `0x7fffffff` | 0 → fine |
| 140737488355328 | `0x800000000000` | 0 → fine (at the ceiling) |
| any negative int64 | | 0 → fine (`u` is huge) |

Every `_kw` entry point routes through the same predicate —
`mojo_dict_get_int_kw`, `mojo_dict_contains_kw`, `mojo_dict_pop_int_kw`,
`mojo_dict_setdefault_int_kw` — so all four crash on such a key, as does
`mojo_cstr_or_int_str` itself (any string-context use: `%s` formatting,
concatenation, `f"{n}"`).

## Why the range is there, and why narrowing it is NOT the fix

The window is deliberate and documented at the predicate. Two things constrain
it from below and above, and the comment above `_mojo_ptr_shaped` is explicit
that both were derived from real failures:

- **2 GiB floor.** Values below it are `None`, small ints, bools, and the
  31-bit `zlib.crc32(name) & 0x7fffffff` struct type-tags that a compiled
  `type(node)` yields where a class object belongs. A previous predicate let
  those through and handed them to `strlen` — CRASH.md's segfault.
- **2^47 ceiling.** The struct predicate's canonical-userspace ceiling; a
  garbage 64-bit word above it must not reach `strlen` either.

The two registry exclusions (`!is_registered_list`, `!is_boxed`) exist because a
boxed float out of a heterogeneous list is pointer-shaped and is not a list —
`struct.unpack('<if', buf)` printed a wrong number as a segfault.

So the shape test is the only discriminator available, and **it is
information-theoretically unable to be right**: in this compiler's scalar body
model a `char *` and an `int64_t` are the same 64 bits with no tag. This is not
a bug with a one-line fix; it is the ambiguity the codegen already knows about,
which is exactly what the `_actual_types` map exists for.

Note what is *not* the fix, explicitly, because each looks reasonable:

- Tightening the range does not help — every choice of bounds trades one
  misclassification for another, and there is no bound that separates "integer"
  from "pointer".
- Requiring the address to be registered would reject every real string: dict
  slot keys are size-exact `malloc`s and codegen string literals live in
  `__TEXT`/`__rodata`, neither of which is in `_reg_*`.

## Next step (2026-09-30; step 1 is DONE — see the Status above)

The production fix is to stop asking the runtime to guess: have the codegen
supply the answer, which is what it is already positioned to do. `emit_infra.py`
records what it *saw* type-erased in `_actual_types`; a call site that knows its
argument is a `double` (the float-key path) or a genuine `int64_t` should emit
the int-keyed entry point directly and never call the `_kw` one. That removes
the guess from every statically-typed site and leaves the predicate to answer
only the genuinely ambiguous ones, where "wrong answer" is at least the current,
documented behaviour.

Concretely:

1. DONE — `mojo/backend_gimple/emit_infra.py`, `_char_to_cstr`'s `word_ok`
   branch: a key the codegen can prove is an integer now emits
   `mojo_int_str_transient` + the ordinary dict entry point and never reaches a
   `_kw` helper. `emit_infra.py` records what it saw type-erased in
   `_actual_types`, and the new `_int_word_vals` is the complement it lacked.
2. NOT DONE — re-measure how many sites remain genuinely ambiguous (the
   `lambda k: d[k]` case in the predicate's own comment is the model example,
   and it is still routed to the `_kw` twin, correctly). The 2026-10-02 store-
   side work moved a known set of shapes off it (`x += e`, `var x = e`, a
   module-global store and a global read-back, `//`, `**`, a ternary) but did
   not attempt a census, and a census is a `--dump-full` measurement: the
   integrator's, not a worker's.
3. NOT DONE, and now doubtful: narrow the range only for the residue, and only
   as a *crash* guard. Nothing landed narrows it — see the Status — and the
   predicate is still asked, so a narrowing here would trade one
   misclassification for another exactly as this doc's own "Why the range is
   there" section argues.

## Coverage

- `test_ptr_registry.py --group boxedstr` (`test_boxed_str_discrimination`):
  asserts `mojo_boxed_is_str(big) == 0` for all five misclassified values, then
  that `mojo_cstr_or_int_str` renders each as its decimal, then the same key
  through a real `mojo_dict_set_int` / `mojo_dict_get_int` round trip. It fails
  today, on the first assertion, as a clean assert rather than a segfault —
  deliberately, so the report is legible.
- Registered as `ptrreg-boxed-str` with an `expect=` reason, so the suite shows
  it as EXPECTED and it flips to FAILURE the moment the predicate is fixed.
- 4294967296 was in `test_dict_and_itoa`'s `vals[]` before this, which is how the
  value entered the file — but that group never ran, because
  `python3-config --cflags` supplies `-DNDEBUG` and the whole harness is written
  in `assert`. See the note in `test_ptr_registry.py`'s `_flags`; the case is
  now in the `boxedstr` group so the two concerns are separate.
- `test_gimple_runner.py`'s `gimple_dict_key_above_2gb_is_an_integer` (added
  2026-10-01 with the codegen fix above): the end-to-end shape, pinned to
  CPython's own answers for a literal key, a local bound from one, `in` for a
  present and an absent large key, and the `lambda` string-key case that must
  keep going through the `_kw` twin. SIGSEGVs on the parent commit. It is the
  test that covers what landed; the `boxedstr` group covers what did not.
- `test_gimple_runner.py`'s `gimple_dict_key_computed_is_still_an_integer` and
  `gimple_dict_key_computed_reaches_every_dict_consumer` (added 2026-10-03 with
  773080f9 / 71a77e8c): the computed key through all eight arithmetic
  spellings and through the eight other dict entry points, both pinned to
  CPython's own answers, plus the string half (`s[a + b]`, `s["foo" + "bar"]`)
  that is the soundness contract for the producer. Both SIGSEGV — empty stdout,
  exit -11 — with the codegen hunk reverted, verified by reverting it and
  re-running rather than by reading the generated C.
- `test_gimple_runner.py`'s `gimple_computed_dict_key_above_2gb_is_an_integer`
  (added 2026-10-02 with the two producers above): the same end-to-end shape
  for a key that is COMPUTED, in four spellings, pinned to CPython's answers.
  SIGSEGVs on `bc17a62b` for the whole program.
- `test_gimple_runner.py`'s `gimple_assigned_large_dict_key_survives_every_
  store_shape` and `gimple_module_scope_large_dict_key_survives_the_global_
  store` (added 2026-10-02 with the store-side carries and the three new
  producers): the ASSIGNED half of the same fact. The first is SIGSEGV on the
  parent commit at its third line (`1`, `2`, `3` printed, then the ternary's
  subscript); the second prints NOTHING before, because it died on line 3.
  The first also pins the soundness direction — a string in the slot that
  `k = 3000000000` used to hold must still be a STRING key — because a carry
  that cannot clear itself would turn a crash into a silent wrong answer,
  which this codebase rates as the worse of the two.
- NOT covered, and named here so it is not mistaken for covered: none of the
  cases above reaches `d[f()]` or the `char *`-declared-local shape, because
  both are still `SIGSEGV` and a test that asserts a crash is not a regression
  test. When either is fixed, its case goes here.
