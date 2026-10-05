# PERF: `struct_field_names` is still asked once per FUNCTION, by the one-word chain walk

**Area:** `formal/build.py` — `_one_word_sole_field_chain` / `_sole_field_name`.
Found 2026-10-04 on `work/bugs5-1` while pinning the family of per-struct
redundancies the 2026-10-02 per-struct census measured (that doc is deleted
with its fix); the new check is `test_formal_per_struct_asks.py`, whose third case is
this residue.

**Status: FIXED 2026-10-05 (`work/bugs7-4`).** `model.sole_field_names` is the
third module-level table and `formal/build.py` threads it through the eight
helpers that ask, exactly as the four steps below specify. `test_formal_per_
struct_asks.py`'s third case is a STRICT EQUALITY now instead of a slope
assertion, and the measured count went from 64-at-20-functions / 84-at-40 (one
per added function) to **33 and 33**. Equivalence evidence: 208 artifacts —
`compile_formal`'s emitter text for every `formal/examples/*.mojo` on BOTH
backends — byte-identical before and after, and `test_formal_run.py` 1025/0.
`bugs/PERF_struct_field_split_asked_once_per_function.md` names the same
residue and is now down to its `struct_is_one_field` half.

The rest of this doc is the original report, kept as the record of how the
residue was found and measured.

## The measurement

`struct_field_names(S)` derives the struct's whole field set by walking **every
method body of `S`, twice** (`_split_declaration` → `struct_receiver_stores` +
`struct_method_receiver_reads`), so one ask is a whole-struct walk and a
per-function asker pays it once per function. `test_formal_per_struct_asks.py`
builds one module holding a struct with 12 methods and N functions that take it,
runs `_prepare_functions` with the four predicates wrapped, and counts:

| functions | `struct_is_framed` | `struct_fits_one_word` | `struct_is_one_field` | `struct_field_names` |
|---|---|---|---|---|
| 20 | 2 | 3 | 1 | 64 |
| 40 | 2 | 3 | 1 | 84 |

The three partition predicates are flat — the module-level tables answer them,
which is the state `formal/build_cost_2026-10-03.md` §6.1 left them in. The
field set grows by exactly ONE per added function, and that one is
`_one_word_sole_field_chain`'s `_sole_field_name(st)`:

```python
# formal/build.py, _one_word_sole_field_chain
    chain, seen = [], set()
    while st is not None and st.name not in seen \
            and M.one_field_answer(st, one_field):
        seen.add(st.name)
        field = _sole_field_name(st)      # <-- model.struct_sole_field_name(st)
        chain.append(field)
```

`_sole_field_name` asks `model.struct_sole_field_name`, which is
`struct_field_names(st)[0] if len(...) == 1 else None` — the walk. The chain is
walked once per FUNCTION that holds or owns a one-word struct (three call sites:
`formal/build.py:9343`, `:9685`, `:15288`), so the count is
`#functions-with-a-one-word-name`.

On a module whose struct has 40 methods instead of 12, the same comparison is
**83 `struct_is_framed` asks and 249 field-set asks before the two fixes that
landed on `work/bugs5-1`, against 2 and 168 after** — which is the size of this
residue: one walk per function over a 40-method struct.

**The clock does not move, and that is stated rather than glossed.** A struct
with 12 short methods costs little per walk: `_prepare_functions` over a
2 285-line synthetic module measured 2.22 s / 2.27 s before and 2.87 s / 2.22 s
after — noise, not a win, and `bugs/FORMAL_build_cost_2026-10-03.md` §6.1 says
the same about the fix that preceded this one ("the win is on the outlier and is a
wash elsewhere"). The ask count is the assertion that does not depend on the
file's shape.

## The fix, as landed

Publish the field NAME per struct the way `one_field_struct_names` publishes the
STRUCT, and read it — all four steps, with what each turned out to need:

1. `formal/model.py`: `sole_field_names(structs) -> {name: field}` beside
   `one_field_struct_names`, deriving each entry with the existing
   `struct_sole_field_name` — so the two tables cannot disagree about which
   structs have one field, which is the failure mode a second derivation of the
   same predicate invites. `sole_field_answer(struct_def, sole_field=None)` is the
   threaded read beside `one_field_answer`, and it is a FUNCTION rather than a
   `.get()` for the reason `one_field_answer` is: `None` must mean "no table" and
   not "the table has no entry", or a caller would silently stop refusing a
   struct whose one field binds no name — which is what `_sole_field_name`'s own
   refusal exists to catch.
2. `formal/build.py`: threaded beside `one_field` through eight helpers, not
   six — `_sole_field_name`, `_one_word_sole_field_chain`,
   `_rewrite_self_fields`, `_lift_one_word_field_method`,
   `_rewrite_one_word_field_method_calls`, `_collect_one_field_receiver_rebinds`
   and its caller, `_collect_one_word_frame_receivers` /
   `_park_one_word_frame_receivers` and `_frame_receivers` — plus the four
   direct `M.struct_sole_field_name(...)` reads. The two extra hops are
   `_rewrite_one_word_field_method_calls` and `_lift_one_word_field_method`, which
   this doc did not list: they read the same chain the three listed sites do, one
   pass earlier, so leaving them on the predicate would have kept a per-function
   asker behind. Every helper keeps its current behaviour as the `None` default,
   so a caller with no module table keeps asking the model — the same contract
   `model.one_field_answer` states, and the reason none of the landed signatures
   changed an answer.
3. `test_formal_per_struct_asks.py`'s third case is a strict equality (40
   functions ask it as often as 20 do) and its docstring loses the residue
   paragraph.

**Why 33 and not 1**, since that is the number the strict equality pins and it
looks like a leftover: a struct's field set is still derived once per FUNCTION for
the handful of readers that were never in any of the three tables. That is the
same bargain `framed` and `one_field` made — the tables answer the predicates
that the `_prepare_functions` loop asks per function, and not every reader of
the field set is one of them. What the strict equality rules out is the thing
that regressed: a count that MOVES when the function count does.

**Soundness condition, settled by measurement rather than by argument** — the
same one `one_field_struct_names`' own docstring records, and worth repeating
because it is the thing that makes a per-struct table safe here at all: the
answer depends on the struct's method BODIES, and `_prepare_functions` rewrites
them (`_rewrite_method_calls`, `_rewrite_self_fields` collapsing `self._inner` to
`self` for a one-word struct, the second of which moves an assignment TARGET). A
table published at the wrong point is a stale field set, which is a wrong answer
rather than a failure. `formal/build_cost_2026-10-03.md` §3.1 measured **146 779
asks over 7 788 (question, struct) pairs across 14 files with not one pair
changing its answer between two asks inside one `_prepare_functions` call**, so a
table read at the top of the loop is the table every ask returned — and the fix
belongs at the same point `one_field` is derived, not somewhere new.

## What was run

`python3 test_formal_per_struct_asks.py` (7/7, and the third case's message went
from "grows by 1.00 per added function … 64 then 84" to "40 functions ask it as
often as 20 do — 33 then 33"), then the byte-identical-C comparison over
`formal/examples/*.mojo` on both architectures — the bar
`formal/build_cost_2026-10-03.md` §6.1 used and the one that caught the
`iter_statement_nodes` container tuple on its first run:

    # 52 examples x 2 backends, one process, `compile_formal(..., prove=False)`
    # and the result dict's own `code` — the emitter text, not a re-derivation.
    $ python3 .tmp/bytecmp.py new && git apply -R <the diff> \
        && python3 .tmp/bytecmp.py old
    new: built=104 refused=0 other=0
    old: built=104 refused=0 other=0
    $ for f in .tmp/bc/old/*; do cmp -s "$f" ".tmp/bc/new/$(basename $f)" \
        || echo DIFFERS; done
    identical=208 differing=0

plus `test_formal_run.py` 1025/0, `test_formal_x86_64_parity.py` 74/0,
`test_formal_bracketed_method_field_set.py` 26/0, `test_formal_value_model.py`
83/0, `test_formal_method_param_field.py` 32/0, `test_formal_field_walk.py` OK,
`test_formal_monomorph.py` 23/0 and `test_suite.py` 329/0.

`python3 tools/suite.py formal` is still the integrator's to run for the rest of
`formal/` — this is `formal/build.py`, which owes the full gate.
