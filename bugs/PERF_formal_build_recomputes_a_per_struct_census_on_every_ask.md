# PERF: `formal/build.py` recomputes a PER-STRUCT census on every ask, and that is where a big file's time goes

**Class:** performance (the value model's tables, not one pass).
**Area:** `formal/model.py`'s per-struct helpers, read from `_prepare_functions`
and from both emitters.

Found while answering `bugs/FORMAL_sweep_default_timeout_hides_a_crash_on_the_repos_own_files.md`
§3, which asked for "a profile" of the two repo-root files no `-t` answers
(`gimple_codegen.py`, 5 645 lines; `myinterpreter.py`, 5 572). That section's
hypothesis — "the AST-walk-per-pass shape in `formal/build.py` is the first
thing to look at" — is **measured false below**, and the real shape is adjacent
to it: it is the per-STRUCT tables, recomputed once per ASK rather than once per
struct. This doc is the measurement and the next step; nothing here is fixed yet.

## What I ran

Timers wrapped around the candidate entry points with `functools.wraps` and
`time.perf_counter`, and the build driven through `runpy` so the whole pipeline
is inside the measured process. **No `cProfile`, and that is the point** — see
"What the profile gets wrong". The harness, so the numbers can be re-derived
rather than believed:

```python
# .tmp/phase_timer.py — run as
#   python3 .tmp/phase_timer.py build --formal --no-prove -o .tmp/o FILE
import collections, functools, os, runpy, sys, time
sys.path.insert(0, os.getcwd())
import formal.model as M
import formal.build as B

TIMES = collections.Counter()
COUNTS = collections.Counter()

def wrap(mod, name, label):
    fn = getattr(mod, name, None)
    if fn is None or not callable(fn):
        return
    @functools.wraps(fn)
    def timed(*a, **k):
        t = time.perf_counter()
        try:
            return fn(*a, **k)
        finally:
            TIMES[label] += time.perf_counter() - t
            COUNTS[label] += 1
    setattr(mod, name, timed)

for n in ("parse_module", "_prepare_functions", "_frame_receivers",
          "_rewrite_method_calls", "collect_module_symbols"):
    wrap(B, n, f"build:{n}")
for n in ("iter_nodes", "_self_field_names", "struct_is_framed",
          "struct_field_names", "struct_nested_frame_fields",
          "struct_fields_written_outside_init", "frame_field_type_candidates",
          "_init_field_assignments", "struct_frame_slots",
          "struct_frame_block_bytes"):
    wrap(M, n, f"model:{n}")

t0 = time.perf_counter()
try:
    runpy.run_path("fire.py", run_name="__main__")
except SystemExit:
    pass
print(f"\nTOTAL wall: {time.perf_counter() - t0:.1f}s", file=sys.stderr)
for k, v in TIMES.most_common(20):
    print(f"  {v:8.2f}s  n={COUNTS[k]:<9} {k}", file=sys.stderr)
```

## What I saw

Two files, arm64, `--formal --no-prove`, this tree, each wrapped in
`tools/memslot.py --gb 8`. Times are INCLUSIVE and overlap where one call
contains another; the counts are the point.

`monomorphize.py` (350 lines, this repo's root) — 8.9 s in-process:

| | time | calls | what it is |
|---|---|---|---|
| `_prepare_functions` | 4.37 s | 5 | the pass everything below happens in |
| `struct_nested_frame_fields` | 2.49 s | 91 | the PLACEMENT decision, once per (struct, constructor site) |
| `frame_field_type_candidates` | 2.33 s | 632 | **once per (struct, FIELD)** |
| `_init_field_assignments` | 1.42 s | 579 | a walk of `__init__`, reached from all four of the type questions |
| `iter_nodes` | 0.72 s | 7 384 362 | the generic walker |

`std/builtin/int.mojo` (172 lines) — 3.9 s in-process:

| | time | calls | what it is |
|---|---|---|---|
| `_self_field_names` | 2.51 s | 1 138 184 | one method body's field-set walk, per ask |
| `_prepare_functions` | 1.82 s | 7 | |
| `struct_is_framed` | 0.75 s | 743 | **the layout question, asked 743 times for 30-odd structs** |
| `struct_nested_frame_fields` | 0.63 s | 233 | |
| `iter_nodes` | 0.25 s | 3 383 849 | |

**Two different hot functions in two files, and neither is `iter_nodes`.** The
shape is the same in both: a per-struct table is derived from the struct's own
bodies, and it is derived again on every ask, so the cost is
`#asks x #methods x body size` rather than `#structs x #methods x body size`.

The two redundancies, named:

* **`struct_field_names(S)` walks every method body of `S`.** It reads
  `_split_declaration`, which calls `struct_method_receiver_reads(S, receivers)`
  — and that walks each method (`struct_demoted_method_names` →
  `struct_receiver_stores` → `iter_nodes` per method, plus `_receiver_names` per
  method). `struct_field_count` → `struct_is_framed` → `struct_fits_one_word`
  all sit on top of it, so a caller asking "is `S` a frame?" walks `S`'s whole
  body. **743 asks for a 172-line file** is the measurement, and 1.1 M
  `_self_field_names` calls is its consequence.
* **`_init_field_assignments(S)` walks `__init__`, and it is reached FOUR times
  per (struct, field) from `frame_field_type_candidates` alone** — from
  `struct_field_type` → `_init_store_shape_refusal`, → `struct_init_field_types`,
  → itself, and → `struct_init_field_type_why`. Three of those four are the same
  walk of the same unchanged body, inside one call.

The second is a **thread-the-dict** fix and needs no cache and no publish point:
`struct_field_type` computes it once and passes it down, with each helper's
current behaviour as the `None` default so every other caller is untouched.
Cheap, and worth doing first precisely because it is the one with no soundness
question attached.

## What the profile gets wrong, which is why the harness is in this doc

`cProfile` on the same build ranks `formal/model.py`'s `iter_nodes` FIRST, with
`_self_field_names` and `walk` next, and the tree already carries that
measurement in `iter_nodes`'s docstring ("the descent was 87% of the build's
samples before this and 71% after"). Under the wall-clock harness `iter_nodes`
is **8% of `monomorphize.py` and 6% of `int.mojo`** — 7.4 M calls at ~85 ns
each. cProfile's overhead is per CALL, so a function called 7 million times
inflates until it looks like the cost; the ranking it produces is a statement
about call counts, not about time.

That is not a reason to distrust cProfile — it is the right tool for "which
function is called how often", and its call counts are what identified
`_self_field_names` here. It is a reason not to read its TIME column as a
ranking of costs, and it is the correction this doc exists to leave behind: the
next person to profile this pipeline should time it, not sample it.

Measured for scale, since it decides whether the fix is worth anything: an
explicit-stack rewrite of `iter_nodes` (same order, same laziness, verified
node-for-node identical over 97 files / 193 122 nodes) is **1.21x** on the walk
itself — about 1.5% of a build. It is not where the time is, and it is not
landed.

## The exact next step

1. **Thread `_init_field_assignments` through `struct_field_type`'s three
   helpers.** No cache, no publish point, no staleness question: one call, one
   body, one walk. Expected: most of the 1.42 s above, and it scales with
   `#fields`, which is the axis that hurts on a big file.
2. **Publish the per-struct FIELD SET once, the way `_field_evidence` already
   is.** `attach_field_evidence` / `struct_field_evidence` is the established
   mechanism for exactly this — a per-struct table the pipeline computes and the
   emitters read off the struct, because both backends ask about a struct they
   were handed with no unit in hand. `struct_field_names` is the same kind of
   table and is not published, which is why it is re-derived per ask.
   **The soundness condition is the whole of this step and it is NOT
   mechanical:** the answer depends on the struct's method BODIES, and
   `_prepare_functions` rewrites them — `_rewrite_method_calls` turns
   `recv.m(a)` into `Struct_m(recv, a)` and `_rewrite_self_fields` collapses
   `self._inner` to `self` for a one-word struct, the second of which moves an
   ASSIGNMENT TARGET. So a table cached at an arbitrary time is a stale frame
   layout, which is a wrong answer rather than a failure — the outcome
   `struct_field_names`'s own docstring calls worse than a refusal. It has to be
   published at ONE named point, after the rewrites that touch field sets and
   before the first reader, and every reader has to prefer it over recomputing.
   Whether the tables happen to be stable across the rewrites is a MEASUREMENT
   worth making before choosing the point (compare every struct's
   `struct_field_names` at the top and the bottom of `_prepare_functions` over a
   corpus), and it is not a substitute for the argument: a memo is sound by
   construction or not at all.
3. **Then re-measure with the harness in this doc**, on the two files the sweep
   cannot answer. That is the measurement that says whether
   `gimple_codegen.py` has a ceiling at all.

Steps 1 and 2 are in `formal/model.py` and are read by both backends and by the
Lean proof's struct model, so a change here owes the full `make gate` — it is
the integrator's, not a light worker's.
