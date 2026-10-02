# FORMAL_module_global_string_elements: a module global whose CONTAINER holds a string

**Status: OPEN, still REFUSED, and the filing's quoted message is stale — the
refusal is now a different one and for a more general reason.** Re-measured on
this tree, both architectures. Not fixed; what it would take and what the one
refusal it collides with are below.

## What it is now, measured

```
L = ["a", "b"]          # and  D = {"a": 1}
```

Both backends refuse, identically:

> build: main: 'L' is bound at module level, and this path has no module-global
> storage for it: a formal value lives in a function's own stack scratch, and
> that scratch is reclaimed when the function returns, so a name that outlives
> every frame has nowhere to live. A module-level name whose value the build can
> FOLD is substituted at every read and needs no storage — this one is not
> literal-only, so its value is not known before the program runs. Make the
> module-level binding a literal (or literal-only arithmetic on literals), or
> move the computation into a function and pass the result in

**The filing's quoted message is a different, narrower one** — "'L' has storage
here … but that storage has no initializer: a container element is a string, and
a string is a pointer to NUL-terminated bytes, so the blob would need those bytes
in `__DATA` with a relocation per element." So the decision has already moved:
the general rule is that a module-level name is FOLDED (substituted at every
read, needing no storage precisely because nothing ever stores it) or REFUSED,
and `["a", "b"]` is not literal-only so it never reaches the storage question
the filing was about.  The `__DATA` block and the per-element relocation the
filing reasons about do not exist on this tree at all.

That is not a small change in the answer, and it is worth being explicit that
**the filing's four-step next step is therefore aimed at machinery that is not
there**: "give `GlobalDataImage` a string arena", "record a fixup for the
container word and one per string element", "the existing lazy initializer
already fills address-valued slots from code".  There is no `GlobalDataImage`,
no lazy initializer, and no `__DATA` block; a formal value lives in a function's
frame.  Steps 1–2 of that plan would have to be re-derived against whatever the
value model is at the time, not applied.

## Why a container of strings is still not answerable, and the honest reason

A string on this path is a bare `char *` into the image's read-only
`__TEXT,__text` (`bugs/FORMAL_string_value_model.md`'s decision, measured: the
section is `initprot 0x5`, no write bit, and the bytes are NUL-terminated).  So
a `list` of strings is a blob of eight-byte WORDS, and each word has to be a
pointer to bytes that live somewhere with static storage duration.  The value
model has exactly one such place — the interned literals — and a container built
at run time would need a fresh arena that outlives the frame that built it,
which is the same lifetime argument that refuses a frame address in a field and
a blob returned by a callee (`model.construction_dead_blob_refusal`).

So this is a **storage-lifetime** gap, not a layout gap.  Laying the strings out
would mean a run-time string arena, and that is a change to the value model
which both backends AND the ~40 passing Lean proofs share.

## The cheaper half, and the refusal it collides with

The name does not have to be a *container* for the write to be impossible.
`L = ["a", "b"]` is refused for "no module-global storage", but so is any
mutable module-level binding, and that is now a NAMED refusal of its own:

```
G = 5
def bump():
    global G
    G = G + 1
```

refused by `model.mutated_module_global_refusal`, measured wrong on both
architectures before that check existed (CPython 6 and 6; this path 10601485 and
5 on arm64, 11 and 5 on x86-64).  So the family is:

| what the name is | answer |
|---|---|
| literal-only, never written | FOLDED — substituted at every read, and that is `read_string_global` / `write_string_global` running on both backends today |
| not literal-only, never written | REFUSED — the value is not known before the program runs |
| anything, written through a `global` declaration | REFUSED — there is no storage a write could outlive a frame in |

A container of strings is in the second row, and the honest reading is that it
belongs there: it is not a storage-of-strings problem that a string arena would
solve, it is that a module-level value must be knowable at build time.  That is
a different, and much more reachable, piece of work than the filing's plan — and
it is a design decision about what a global may be, not an implementation task.

## Next step, in the order it should be taken

1. **Decide whether a module-level binding may be non-literal at all.**  If the
   answer is no, `["a", "b"]` at module level is refused *correctly* today and
   the only work is the message saying so — and `mlir.py` (the file the filing
   found this through, whose module-level `MLIR_TYPES` is a dict of string keys
   to string values) needs its `MLIR_TYPES` written as literals, which is a
   source change to a file that already has a hand-maintained table.  If the
   answer is yes, that decision is the same one the returned-frame convention
   makes for values, and it wants the same treatment.
2. **Only then, the arena.**  A run-time string arena with static storage
   duration, which means a bump allocator over a region that is not a frame —
   and the first question is who owns it, because on this path nothing outlives
   a function.  This is the part that touches the Lean proofs.

**The measurement to take first is the denominator one**: `mlir.py` is already
`CODEGEN: module-global name has no storage` in the sweep, and the two
reproductions here are 30-line programs that no sweep file contains, so closing
this moves no number in either direction until step 1 is decided.  Do not read a
coverage change here as a gain.