INTERFACE REQUEST  from=[4]  to=integrator  file=formal/build.py

**RESOLVED — the gate at `formal/build.py:2423` is gone and the half that
depended on it has landed.**  Kept as a pointer, not as an open item, because
one thing in it is still somebody else's.

WHY IT WAS FIRST: `formal/build.py` was in NOBODY's write set and is not in
FORMAL.md §11.2's "Deliberately unowned" list either. It is also the file that
raised the refusal which was the entire target of [4]'s item: every "returned by
its creator" finding came from ONE line.

WHAT WAS ASKED, and where each half is now:

  1. "a `ReturnStmt` whose value is a holder in `created_here` should NOT
     raise."
     DONE, and the `received=True` half with it.  The reason it could be is
     that the convention names the destination: the caller reserves a block,
     passes its address as one hidden trailing argument, and the callee copies
     into it.  A frame that arrived as a PARAMETER is sound to copy out for the
     same reason — the copy happens while the caller's frame is live — so
     `def fwd(r): return r` and `def stash(x, y): return y` compute now.  That
     supersedes the "stays refused" in the request below, which was written when
     the destination was going to be computed by the callee (the candidate
     `returned_frame_convention_refusal` rules out, because the callee has not
     read the caller's body and cannot know which of its blocks to use).
     `formal/build.py`'s `_check_frame_escapes` and the new
     `check_frame_return_shapes`, which is parked and raised from the entry
     points beside the other three late frame checks.
  2. "the call-side counterpart … `struct_returned_frame_sites` has to be handed
     the `returns_frame` predicate this file's holder fixpoint already
     computes."
     DONE, and the predicate is a whole-image table rather than a per-call
     answer: `_frame_receivers` now computes `{function: struct}` for the
     functions that return a frame INSIDE the holder fixpoint (the two feed
     each other) and publishes it on every function as `_image_returns_frame`.
     `struct_returned_frame_sites` takes a one-argument predicate and now
     reserves a block for EVERY call of such a callee, not only the ones that
     bind the result to a name.
  3. "`returned_frame_convention_refusal` has to be RAISED from here, or from
     the codegen, or the hidden word is silently dropped."
     DONE TWICE, deliberately: `_check_returned_frame_budget` parks it from the
     build pass (one function, many call sites, counted from the DECLARED
     parameter list), and each backend raises it again at the call site that
     would otherwise drop the word.  The budget is SIX source arguments, not
     the eight the request assumed, because x86-64 passes integer arguments in
     six registers and a limit of eight would make the two machines answer
     differently about one program.

THE ONE THING STILL OPEN, and it is [3]'s: "the hidden argument is a
calling-convention change whose proof-side obligation is a `lib/Refine.lean`
predicate".  The codegen half is landed and measured, and no example in
`formal/examples/` exercises a wide receiver, so the proof layer has not been
asked the question yet.  What a proof would need to state, and cannot yet: that
the hidden word is a block in the CALLER's scratch, that the callee writes only
into it, and that every other channel out of a frame is refused — the third of
those is `formal/build.py`'s, the first two are the emitter's.

WHERE TO READ IT NOW: `bugs/FORMAL_wide_receiver_by_reference.md`, wave 8 —
the convention, the three properties that make it work, the refusals that
remain, the sweep numbers on both machines, and the arm64 spill bug the
eleventh local made reachable.  And `test_formal_returned_frame.py`, whose 14
cases all fail on the pre-change tree.
