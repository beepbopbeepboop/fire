# FORMAL_module_global_bound_to_a_non_literal_has_no_lazy_initializer: 5 files in slice repo-c, and the mechanism that would hold it already exists

**Status: OPEN, measured on `master` (2026-10-02) while sweeping slice `repo-c`.
NOT fixed here: the claim that owns the mechanism is
`bug:FORMAL_module_state_no_storage`, and this filing also asks for a correction
to that claim's doc, which is not this branch's to make.** The remaining causes
are ranked in `bugs/FORMAL_sweep_work_map_2026-10-02_repo-c.md` §4.2 — this is
the second-largest row (5 of the slice's 15 answerable files) and it is ONE gap
wearing two messages.

## What I ran

```
$ python3 tools/memslot.py --gb 8 --label sweep -- python3 tools/formal_sweep.py \
    -j 4 --no-stdlib -t 60 --allow-concurrent <the repo-c 211 paths>
```

and the ranked causes, which name the five files and both messages:

| file | name | initializer | message |
|---|---|---|---|
| `formal/elf.py:28` | `ELF_MAGIC` | `b"\x7fELF"` | *bound at module level, and this path has no module-global storage for it* |
| `tools/bootstrap_verify.py` | `REPO` | an `os.path…` call | same |
| `tools/audit_selfhost_struct_fields.py` | `HERE` | `os.path.dirname(os.path.abspath(__file__))` | same |
| `tools/wave1_move_shared.py` | `MOVES` | a container literal whose ELEMENTS are not static | *has storage here — it is one of the module-global slots — but …* |
| `tools/wave2_extract_shared.py` | `EXTRACT` | likewise | same |

## The mechanism, and the one place that decides who gets a slot

`formal/model.py::module_slots` grows a table for a module-level name in exactly
two cases, and its docstring says why:

* **a function WRITES it** — `global G; G = G + 1` changes the value while the
  program runs, so there is no one value to substitute at the reads;
* **its value is a CONTAINER literal** — `[1,2,3]` is not a value the folding
  path can express, but it IS static data: a flat blob whose first word is the
  count, so the linker can place it in `__DATA` and the slot can hold its address.

Everything else is FOLDED and needs no storage. A name in neither set that the
build also cannot fold is refused by name, which is the first message above.

So the two messages are one question asked at two depths:

* a **scalar bound to a call** has no slot at all, because there is no value to
  substitute at the read and nowhere to keep the computed one;
* a **container literal whose words cannot be computed statically** gets a slot
  with `("unknown", …)` from `_static_initializer`, and is refused by name at the
  read.

## Why this is not a value-model project, and the reason nobody has done it

**The lazy initializer exists, and it is a real one.** `GlobalDataImage` is in
the tree; `GlobalDataImage.string_cells` exists precisely for initialisers that
only CODE can carry out ("only the codegen interns"), and the block comment at
`formal/model.py:17745` ("WHY THE INITIALIZER IS LAZY") documents the mechanism
in full: a function that reads a global is emitted with a flag-word check and
runs the initialiser when the flag is clear, because a dylib has no startup stub
to put it in and one mechanism for both container kinds is the only answer this
codebase accepts. `function_touches_globals` is the predicate that decides which
functions pay for it. A module-level *expression* — `os.path.dirname(
os.path.abspath(__file__))` — is exactly what that mechanism is for.

**What is missing is that `_static_initializer` is deliberately exhaustive over
what a `__DATA` word can hold statically, and an expression is none of those.**
The slot table is built at build time from the module's statement list; the
initializer is a *tuple of bytes to link*, not code to run. Closing this is
therefore one question the machinery already frames: **accept an expression as an
initializer, run it before the first read, and write the slot** — for a
restricted, decidable subset.

## The next step, in the order it should be done

1. **Extend the lazy initializer to run the module-level EXPRESSION at the first
   read and write the slot**, for a deliberately narrow and decidable subset — a
   call to an imported Mojo-side function, and arithmetic over literals — and
   refuse everything else exactly as it does now. This is the whole of rows 1–3
   (`REPO`, `HERE`, and every `sys`-side computed path).
2. **Then `b"…"` as a literal**, which is a different and cheaper question: a
   bytes literal is a blob whose words are the bytes' own, so
   `_static_container_words` may be able to compute it once it is told a bytes
   literal is a STATIC RUN rather than an unclassifiable value. `ELF_MAGIC` is
   one line of one file; do not bundle it with step 1.
3. **The container case is its own question** and should not be bundled with
   either. `MOVES` and `EXTRACT` are container literals that DO get slots, so the
   failure is narrower: `_static_container_words` gave up, and **its own message
   is the thing to read first** — it says why.

## A doc correction this filing is asking for, and is not making

`bugs/FORMAL_module_global_string_elements_is_a_storage_decision.md` states, as
current fact:

> There is no `GlobalDataImage`, no lazy initializer, and no `__DATA` block; a
> formal value lives in a function's frame. Steps 1–2 of that plan would have to
> be re-derived against whatever the value model is at the time, not applied.

All three now exist (`GlobalDataImage` at `formal/model.py:17688`, the lazy-init
flag word described at `formal/model.py:17745`, `__DATA` written by
`build_data_image`). That
document also correctly says its own quoted refusal is stale. **A reader who
follows its four-step next step would rebuild machinery that is already there**,
which is the failure mode this repository's docs are most often written to avoid,
so the correction is worth making by whoever owns the claim.

## What this filing does not claim

* It does not claim a module-level expression is ANSWERABLE in general. Step 1's
  subset is narrow on purpose: an arbitrary call has arbitrary effects, and the
  lazy initializer runs at the first READ rather than at module scope, so a
  program whose module-level expression has a side effect would see it happen
  later than CPython runs it. That is a second question and it needs its own
  answer.
* It does not claim the value model cannot hold a computed container. The
  lifetime argument (a container built in one frame, read from another) is
  `bugs/FORMAL_module_global_string_elements_is_a_storage_decision.md`'s subject
  and is unchanged by any of this.
* It does not measure the sweep count. `FILES BLOCKED` is an upper bound: 5 files
  is how many the sweep's walk reaches, and closing steps 1–3 would move them to
  their next cause with the count unchanged.
