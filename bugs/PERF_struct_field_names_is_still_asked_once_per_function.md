# PERF: `struct_field_names` is still asked once per FUNCTION, by the one-word chain walk

**Area:** `formal/build.py` — `_one_word_sole_field_chain` / `_sole_field_name`.
Found 2026-10-04 on `work/bugs5-1` while pinning the family of per-struct
redundancies that `bugs/PERF_formal_build_recomputes_a_per_struct_census_on_every_ask.md`
measured; the new check is `test_formal_per_struct_asks.py`, whose third case is
this residue.

**Status: measured, named, and PINNED as a number. Not fixed** — it is six call
sites in a file that owes the full gate, and the fix is the same shape as the one
that landed twice already.

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

## The fix, and why it is not in this commit

Publish the field NAME per struct the way `one_field_struct_names` publishes the
STRUCT, and read it:

1. `formal/model.py`: a `sole_field_names(structs) -> {name: field}` beside
   `one_field_struct_names`, deriving each entry with the existing
   `struct_sole_field_name` — so the two tables cannot disagree about which
   structs have one field, which is the failure mode a second derivation of the
   same predicate invites;
2. `formal/build.py`: thread it beside `one_field` through `_sole_field_name`,
   `_one_word_sole_field_chain`, and the three call sites above, plus the four
   direct `M.struct_sole_field_name(...)` reads at `:4215`, `:4348`, `:4923` and
   `:8241`;
3. keep every helper's current behaviour as the `None` default, so a caller with
   no module table keeps asking the model — the same contract
   `model.one_field_answer` states, and the reason the three landed signatures
   did not change an answer;
4. `test_formal_per_struct_asks.py`'s third case becomes a strict equality (40
   functions ask it as often as 20 do) and its docstring loses the residue
   paragraph.

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

## What to run

`python3 tools/suite.py formal` is the honest gate for this (it is `formal/`,
read by both backends and by the Lean struct model). Narrowly:
`python3 test_formal_per_struct_asks.py`, then the byte-identical-C comparison
over `formal/examples/*.mojo` on both architectures, which is the bar
`formal/build_cost_2026-10-03.md` §6.1 used and the one that caught the
`iter_statement_nodes` container tuple on its first run.
