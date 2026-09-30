INTERFACE REQUEST  from=[4]  to=integrator  file=formal/build.py

WHY FIRST: `formal/build.py` is in NOBODY's write set this round and is not in
FORMAL.md §11.2's "Deliberately unowned" list either, so it has no owner. It is
also the file that raises the refusal which is the entire target of [4]'s item:
all 18 of the "returned by its creator" findings come from ONE line.

WHAT:  `formal/build.py:2423`, inside `_check_frame_escapes`:

        raise CodegenError(M.frame_return_refusal(
            owner.name if owner is not None else None,
            node.value.name not in created_here,
            _names(node.value)))

     This is the gate on `return <frame>`. The fix — a returned frame copied
     into a block in the CALLER's own scratch, so it outlives its creator — is
     now designed and its layout is landed in `formal/model.py`
     (`struct_returned_frame_sites`, `returned_frame_convention_refusal`).
     What is left here is to stop refusing, once the codegen half and the
     proof-side obligation have landed:

     1. a `ReturnStmt` whose value is a holder in `created_here` should NOT
        raise. The copy is emitted by the callee; there is nothing for the
        build pass to do but not object. (The `received=True` case is a
        DIFFERENT shape — the frame came in as a parameter, so the creator is
        up the call chain — and it stays refused: the callee cannot copy a
        frame it did not build into a place the caller can reach, because
        "the caller" is not a function this analysis can name. Those are the
        9 `aliased out of a method` findings, and they are not this fix.)
     2. the call-side counterpart: a call whose result binds a frame holder
        needs no new refusal, but it DOES need the caller's block, and
        `struct_returned_frame_sites` has to be handed the `returns_frame`
        predicate this file's holder fixpoint already computes. That is a new
        argument on a new call, not a change to an existing one.
     3. `returned_frame_convention_refusal` fires for a returning callee that
        already takes 8 arguments. That refusal has to be RAISED from here, or
        from the codegen, or the hidden word is silently dropped — see the
        `BLOCKS` note.

WHY:  Measured, not inferred. `tools/formal_sweep.py` arm64, this tree:
     `returned by its creator` is **18 of the 128 in-file codegen findings**
     (14.1%), and every one of the 18 is this one line. The refusal is
     CORRECT today — the address really does name reclaimed stack, and the
     measured failure with the check removed is 10 on arm64 and 0 on x86-64
     where the source says 7. What is wrong is that the check is the answer
     rather than a placeholder for one, and the fix now exists on the other
     side of it.

BLOCKS: Nothing of [4]'s that has already landed. It blocks the END-TO-END
        part — the 18 findings becoming PASS — which is the item's "Done when".
        The part that is [4]'s to own (the layout, the convention decision,
        the codegen half) does not depend on this and is not waiting on it.
