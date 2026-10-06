# FORMAL_the_sweep_family_table_has_no_row_for_the_export_rule_refusal: the corpus's biggest UNNAMED shape, and the loud finding now names it

**Claim** `sweep32:instrument` on `work/formal32-instrument`, alongside the two
instruments it was found by: `formal_sweep.py`'s
`unclassified_report` (a refusal shape over the honesty bar is a LOUD FINDING
and exit 4) and `tools/formal_sweep.py`'s committed-baseline regression alarm.
**This is the finding that instrument produced on the tree it landed on**, and
it is filed rather than fixed because filling a table is the queue's job and the
alarm is what makes the queue's job visible. One row, in one table, for a
construct the OTHER table already names.

## What was run, and what it said

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 - <<'PY'
import sys, collections
sys.path.insert(0, "tools")
import formal_sweep as S, formal_sweep_causes as C
import formal_sweep_parity as P
arch, rows, counts, swept, spass = P.read_log("bugs/sweeps/sweep-arm-12.txt")
printed = [(p, r.cls, r.reason, r.reason) for p, r in rows.items()]
un = S.unclassified_rows(printed)
shapes = collections.Counter(S.unclassified_shape(m) for p, m in un)
biggest, n = shapes.most_common(1)[0]
print(n, sorted({C.classify_message(m) for p, m in un
                 if S.unclassified_shape(m) == biggest}))
PY
```

Over the b12 arm64 log — 472 printed codegen rows, 158 of them matching no row
of `_REFUSAL_FAMILIES`:

    136 ['a call to a name the defining module does not export']

The same 136 on `bugs/sweeps/sweep-x86-12.txt`, so it is not an
architecture-dependent shape. The shape is `formal/model.py`'s
`imported_callee_refusal`: "`X` is called, and it is imported from `M`, so the
call has to bind a symbol `M` exports. That module does not export it, and the
reason is `doc/ABI.md`'s export rule…".

**136 of the 472 codegen rows — 28.8 % — are one shape that
`tools/formal_sweep.py`'s `_REFUSAL_FAMILIES` does not name**, and
`tools/formal_sweep_causes.py::CAUSES` names all 136 of them `a call to a name
the defining module does not export`.

Confirmed on a live run, not only on the log — two `std/_gpu/*.mojo` files,
which is a fifth of the corpus's codegen rows between them:

```sh
python3 tools/memslot.py --gb 8 --label loud-sweep -- \
  python3 tools/formal_sweep.py --no-stdlib -j 4 -t 120 -M 4 \
    .../Mojo/stdlib/std/_gpu/globals.mojo .../Mojo/stdlib/std/_gpu/intrinsics.mojo
```

    LOUD FINDING: 2 file(s) of the 2 swept (100.0%) — shape: `…` is called, and
    it is imported from `…`, so the call has to bind a …
      this table names no row for it, and tools/formal_sweep_causes.py — which
      ranks the same rows by what a fix would have to change — is the other half
      of the pair to check
    …child exit 4

## What is expected, and what is not

`formal_sweep_causes.py` got this row on 2026-10-03, measured and argued in
`bugs/FORMAL_sweep_work_map_2026-10-04_b10.md` §5.1 ("the change is in the
ranking instrument, not in the backend" — `other refusal` was 184 files at `-10`
and 170 of them this one sentence). `formal_sweep.py`'s own family table did not
get it, and the two tables are keyed on different things and are meant to
disagree: `_REFUSAL_FAMILIES` groups by the SHAPE of the message for a tool that
must classify one it has never seen, `CAUSES` by what a fix would have to
CHANGE. So both need the row — the same two-part argument
`…_b12.md` §5.2 made for the text-encoding refusal, and
`…_b12.md` §3.1 records this exact failure mode having cost a round.

## Next step

One row in `_REFUSAL_FAMILIES`, with its sample in `test_refusal_taxonomy.py`
(whose `SAMPLES` table requires one message per family and whose docstring says
why: a family with no sample is a family that can rot unnoticed).

* the marker is the clause the whole message exists to state — **"That module
  does not export it"** — quoted from `formal/model.py::imported_callee_refusal`,
  and `b10.md` §5.1 already argues that both of its load-bearing clauses survive
  a reword;
* place it with the other callee rows, ABOVE `("which is a name with no
  definition in hand", "callee has no definition on this path")` only if it does
  not shadow it: the two are different refusals — one callee is a name this
  image has no definition of at all, the other is a name a module exists but
  does not export — so the check is which clause each message carries, and
  `test_refusal_taxonomy.py`'s precedence cases are where to prove it;
* a family label in this table's vocabulary, which is what a fix is named by
  rather than what the message says. `CAUSES` calls it "a call to a name the
  defining module does not export"; the family names its neighbours "value call:
  declared type cannot hold a function" and "dependency binds what nothing
  provides", so something in that shape, decided once;
* then re-run the finding over the b12 log and expect the loud block to drop to
  the 22 remaining files, none of them over the bar on the file count.

**While it stands, the loud finding is correct and the corpus is red for it.**
That is the arrangement: an unclassified shape over the bar exits 4 on purpose
(`formal_sweep.py`'s EXIT STATUS), because a rank-1 row called
`other refusal` with an example file and no next step is what the b12 round was
diagnosed from, after the fact, by reading a work map.
