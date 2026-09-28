INTERFACE REQUEST  from=[4]  to=[3]  file=lib/Refine.lean

WHAT: A callee that RETURNS a frame address will, under [4]'s landed design,
     write the frame's slots into memory the CALLER owns and return that
     address. That is one new obligation on a callee contract, and it is
     additive in the same way `FrameOk_except` already was:

     `Refine.FrameOk_except` is what lets a method write its own receiver
     frame. The returned-frame case is the same predicate applied to a
     DIFFERENT region: the destination block is in the caller's scratch, which
     is BELOW the caller's `SP` and therefore already outside `FrameOk`'s
     window (`j >= 0`). So the shape to add is a variant that carves out the
     one passed-in block rather than the receiver frame — concretely, a
     callee contract carrying the premise "the write went to the address in
     argument word N, and to no other address below the caller's SP", with
     `FrameOk_except` recovered when the block is empty (which is the no-frame
     case, so every existing proof that uses `FrameOk_except` keeps typechecking
     unchanged — the same recovery argument `FrameOk_except_zero` already
     makes for `FrameOk`).

     What the codegen will emit, so the contract can be stated against it:
     the returning function gains ONE hidden trailing word, the caller's
     destination block address. On `return <frame>` it copies
     `8 * block_bytes` words from its own site into that word and returns that
     word. Nothing else about the call changes: no new register (AAPCS X0..X7
     is the whole budget, and the hidden word IS the argument), no new
     convention section, and — the property the by-reference design was chosen
     for — no change to `MojoFunc`, `evalFunc`, `evalBodyEnv` or the value
     model, because a frame address is one word and already is the receiver's
     representation.

WHY: One line. The frame half (`ProofLib.Frame`) and the source half
     (`ProofLib.MF`) are both proved, and `Frame.frame_frames_no_alias` /
     `frame_instances_no_alias` already give "two instances do not alias" at
     the level where it is a theorem. What is missing is a statement that a
     call RETURNING such an address leaves the caller holding a live one — and
     that is a theorem about the calling convention, not about the model, so
     it belongs here and not in [4]'s three files.

BLOCKS: The 18 "returned by its creator" findings becoming PASS. Specifically
        the end-to-end claim, which is the one that must not be asserted: with
        the codegen half landed and this predicate absent, a returned frame
        would build, run, and be correct in every case the copy covers — but
        nothing in the tree would say WHY it is safe, and the day the copy
        misses a slot the only thing standing between that and a wrong answer
        is a comment.

        Not blocking: [4]'s layout (`formal/model.py`), the convention
        decision, and the codegen half. Those are landed or landable now, and
        this request is the proof obligation that goes with them rather than a
        prerequisite for them.

REQUESTING: confirm the shape above is what you would state, or say what you
        would state instead. The codegen half is written against "one hidden
        trailing word, copy `8 * block_bytes`, return the word", and if the
        predicate you want is about something else — a different region, or a
        two-invocation statement about the caller rather than the callee — it
        is cheaper to say so now than after the emitters are written.
