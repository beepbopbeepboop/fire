# FORMAL_returned_frame_two_incompatible_designs: `formal-frame-escape` and `formal-string-return` each built the whole returned-frame convention, differently

**Status: a merge of `work/formal-frame-escape` into a tree that already has
`work/formal-string-return` was attempted and ABORTED. Nothing of either is
half-applied. This document is the map the attempt produced, so the next worker
does not have to rebuild it before deciding.**

Both branches are finished, individually green worker branches. They diverge
from the same commit (`5535925a`, the batch base) and each implemented the
caller-owned-block convention **in full**, down to the prologue, the call site
and its own refusal family. The two implementations are not variants of one
design: they disagree about the shape of the table the backends read, about
which predicate arity `struct_returned_frame_sites` is called with, and about
the mechanism by which the object outlives its creator.

## The evidence, and what each step was

**1. They are siblings, not one a descendant of the other.**

    $ git merge-base --is-ancestor work/formal-string-return work/formal-frame-escape
    (non-zero: NO)
    $ git log --oneline -1 $(git merge-base work/formal-string-return work/formal-frame-escape)
    5535925a integrate runner-stale-mojo

`model.struct_returned_frame_sites` is on **master** (2 occurrences), so its
presence in the frame-escape tree is inherited, not contributed by
string-return. There is no common ancestor that has either design.

**2. Neither tree satisfies the other's tests.** Dropping
`test_returned_frame_layout.py` (string-return's, 18 cases) onto a
`git archive` of `work/formal-frame-escape` and running it:

    TypeError: _returns.<locals>._p() takes 1 positional argument but 2 were given
      File ".../formal/model.py", line 9926, in struct_returned_frame_sites
        st = returns_frame(value.func.name, name)

string-return's test supplies a ONE-argument predicate on purpose — its own
docstring says so: *"ONE argument, because the landed version took the bound
name as well and used it to decide whether the call site's result was kept"* —
so the two branches changed a **public** function's contract in opposite
directions. That is not a merge conflict in the textual sense; it is two
answers to one question.

**3. The frame-ownership mechanism differs, in the codegen, on both machines.**

| | `formal-string-return` (landed here) | `formal-frame-escape` |
|---|---|---|
| who owns the block | the CALLER, per call site | the CALLER, per call site (same) |
| how the object gets there | **copied** at `return` (`_emit_frame_return`) | **written in place** at every construction (`_ret_block_sites`) |
| the callee's state | `_returns_frame`, `_image_returns_frame`, `_SRET_LOCAL` | `_returned_frame`, `_ret_block_reg`, `_ret_fwd_sites` |
| the caller's state | `_ret_frame_sites`, `_ret_frame_base`, `_ret_frame_bytes` | `_ret_recv_sites`, `_ret_recv_bytes` |
| the prologue | `self._load_home_from_reg(_SRET_LOCAL, sret_arg)` | `mov X17, self._ret_block_arg; self._store_var(M.RETURNED_BLOCK_WORD, 17)` |
| the analysis | fixpoint INSIDE the holder loop (`_frame_return_status`, `_check_returned_frame_budget`), table `{fn: struct}` | fixpoint BEFORE the holder loop (`M.returned_frame_holder`, `returned_frame_forward_bindings`), table `{fn: (holder, struct)}` |
| model surface | 4 functions | 19 functions, including a second `returned_frame_convention_refusal` with a THIRD parameter (`arg_regs`) |
| its own tests | `test_formal_returned_frame.py` (14), `test_returned_frame_layout.py` (18) | `test_formal_returned_frame.py` (own version) |

**4. The conflict surface, measured.** 22 conflict regions over 8 files:
`formal/arm64_codegen.py` 6, `formal/model.py` 5, `formal/x86_64_codegen.py` 4,
`formal/build.py` 3, `test_formal_returned_frame.py` 1, `test_formal_run.py` 1,
`bugs/FORMAL_wide_receiver_by_reference.md` 1,
`bugs/INTERFACE_REQUEST_4_to_formal_build.md` 1. The model regions are
individually small and mostly reconcilable; the **backend** regions are not,
because each side's per-function state variables are read in six places and none
of those names survives the other design.

## What reconciling it would actually take

Not a textual merge — a decision, and then the other design's tests rewritten
rather than deleted:

1. Pick the table shape (`{fn: struct}` or `{fn: (holder, struct)}`). The
   branch's carries the HOLDER, which the landed one does not, and the holder
   is what `_ret_block_sites` / `returned_frame_constructor_sites` need, so
   **the branch's shape is the one with more information in it** — that is the
   argument for taking frame-escape forward, not a reason to leave it.
2. Pick the mechanism. Write-through at the construction site (the branch) has
   no copy and therefore no window in which the callee's own block and the
   caller's disagree; copy-at-return (landed) is smaller in the codegen and
   needs no rewrite of every construction. This is a judgement call, and it is
   the one thing here that is not mechanical.
3. Unify `returned_frame_convention_refusal` on the 3-parameter form
   (`callee, n_source_args, arg_regs`) — the 2-parameter form hard-codes
   x86-64's six registers into a shared message, which is what the extra
   parameter exists to stop.
4. Rewrite `test_returned_frame_layout.py`'s predicate to the chosen arity and
   `test_formal_returned_frame.py`'s 14 cases against the chosen mechanism.
   Both files' cases must survive: they are the only coverage the construct has.
5. Re-verify on BOTH architectures, and then with `tools/formal_sweep.py` over
   the files the construct unblocks. That last one is the point: the failure
   mode of getting this wrong is a use-after-free that no narrow test can see,
   and the sweep is a heavy run (see rule 2 of the worker task — a light
   worker does not run it, the integrator does).

## The exact next step

Take `work/formal-frame-escape` forward on a branch that starts from
`master + work/formal-string-return`, resolve it as steps 1-4 above with the
branch's table shape and the write-through mechanism, and hand the result to
the integrator for the sweep. Do not resolve it by keeping both tables: they
answer the same question for the same image, and which one a backend reads
would then depend on which was assigned last.

## Where the code is

| what | where |
|---|---|
| the landed design's analysis | `formal/build.py` `_frame_return_status`, `_check_returned_frame_budget`; `formal/model.py` `struct_returned_frame_sites` |
| the branch design's analysis | `formal/model.py` `returned_frame_holder`, `returned_frame_forward_bindings`, `returned_frame_constructor_sites`, `returned_frame_forward_sites`, `returned_frame_hidden_arg` |
| the shared entry point whose contract they disagree about | `formal/model.py` `struct_returned_frame_sites(fn, structs_by_name, returns_frame)` — the third argument's arity |
| the two designs' own bug docs | `bugs/FORMAL_returned_frame_caller_owned_block.md` (the branch's; not merged), `formal-string-return`'s sections in `bugs/FORMAL_wide_receiver_by_reference.md` |
