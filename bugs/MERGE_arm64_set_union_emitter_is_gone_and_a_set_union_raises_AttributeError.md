# MERGE: arm64's `_emit_set_union` is gone, so `s | t` raises `AttributeError` out of the compiler

**Area:** FORMAL, the arm64 backend — `formal/arm64_codegen.py::_emit_binop`'s
`|` arm (`:8355`), and the `_emit_set_union` it calls. The neighbouring
`&`/`-`/`^` set algebra (`_emit_set_op`, `_emit_set_algebra`) is intact.
**Claimed by:** `formal407-docs`
(`bug:FORMAL_container_operators_that_need_a_per_element_stride`), so this doc
is filed rather than fixed from `work/bunny-reds`.

**Status: OPEN. One dropped definition, found by running a gate job, and the
symptom is a Python traceback out of the compiler rather than a refusal.**

## What I ran, what it printed

    python3 tools/memslot.py --gb 8 --label frun -- python3 test_formal_run.py

    FAIL  blob-growth-guard: arm64/uni: the probe did not compile
          (AttributeError: 'ARM64Codegen' object has no attribute
          '_emit_set_union'), so it cannot show whether the site has a guard.
          A probe that stops compiling is a hole in this check, not a pass

Reproducer, one line of Mojo, arm64 only:

    def main():
        s = {1, 2}
        t = s | {3}
        print(len(t))
        return 0

`formal/arm64_codegen.py:8355` is

    if op == "+":
        self._emit_list_concat(e.left, e.right)
    else:
        self._emit_set_union(e.left, e.right)

and `grep -n "_emit_set_union" formal/arm64_codegen.py` finds that call, three
docstrings that refer to it in the past tense, and no `def`.

## Why this is merge damage and not a missing feature

Three docstrings still describe `_emit_set_union`'s internals as if they were
still there, which is the signature of a merge that took a side:

* `formal/arm64_codegen.py:13622` — "This is the inner half of
  `_emit_set_union`'s second loop, factored out" (on the helper that survives as
  the copy/filter pass `_emit_set_op` calls);
* `:13637` — "…which is `_emit_set_union`'s dedup compare and the same…";
* `:13715` — "`_emit_set_union`'s dedup gives: a set lowers as a list here, so
  an element is a word…".

And the model says the construct IS answerable here, so the gate deliberately
lets it through:

* `formal/model.py::container_union_refusal` returns `None` for
  `left_is_set and right_is_set` — the first row of its own table, "union,
  repeats dropped / **the same thing**" — and both backends ask it at the same
  site, so `s | t` is meant to reach an emitter.
* `formal/model.py:14210` — "That sentence names arm64's `_emit_set_union` FOR
  SETS ONLY", i.e. x86-64 is the backend without the emitter.

So the refusal table promises an answer this tree cannot produce, and produces
an `AttributeError` instead. x86-64 has no `|` arm either and its refusal path
is `container_union_refusal` as well, so the two architectures are meant to
differ here and currently do not differ at all on arm64 — it crashes.

## The exact next step

1. Restore `_emit_set_union` on arm64, or route `|` to whatever survives of it.
   The surviving halves are already factored out and already carry its
   docstrings: the element-filter pass `_emit_set_op` calls, and the dedup
   compare the copy pass uses. A union is "copy the left, then append each
   element of the right that the left does not hold", so it is the copy pass plus
   a membership test — and `container_returned_blob_sites`'s
   `returned_container_blob_bytes` is the table that decides which callees hand
   back a word-only blob.
2. Whatever it is, it must call `_emit_blob_growth_guard` — that is the whole of
   the `blob-growth-guard: arm64/uni` row, which cannot report anything about the
   site while the site does not compile.
3. Re-measure `test_formal_run.py`'s three `set_union_*` rows
   (`set_union_is_a_set_on_arm64_and_refused_on_x86_64`,
   `set_union_count_read_as_a_value_through_locals`,
   `set_union_count_read_as_a_value_through_literals`), which fail today with
   "arm64 REFUSED a set union it lowers".

**Do NOT close the gap by making `container_union_refusal` refuse `set | set`.**
Its first table row says that shape is the one this path emits, and three test
rows assert arm64 answers it, so a refusal there is a smaller wrong answer than
the crash and a larger one than the emitter.

## What is NOT this

`blob-growth-guard`'s other three rows — `x86_64/sin`, `x86_64/sdf`,
`x86_64/ssd`, each "the site emitted NO capacity guard" — are a different defect
on a backend that does compile: `_emit_set_algebra` on x86-64 reserves without
emitting the guard, while `_emit_blob_growth_guard` exists and arm64's
`sin`/`sdf`/`ssd` pass. They are in the same claim and the same table, so they
are listed here only so the next reader does not assume this doc is the whole of
the `blob-growth-guard` red.