# the arm64 frame-method finder scans the stack-floor GUARD prologue, so it finds no method and the by-reference receiver proof path is dead

**Area:** FORMAL, arm64 — `formal/arm64_proof_gen.py::_frame_methods` (and the
`_generate_frame_proof` path it gates). Found 2026-10-14 while checking whether
`_generate_frame_proof` still emits step lemmas over the image's string data
(the arm64 data-word bug, whose ordinary and DYLIB halves are fixed; the frame
half is unreachable because of THIS).

**Status: OPEN, and it is a regression from the stack-floor guard rework, not a
documented limit.**

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 - <<'EOF'
import formal.build as fb
import formal.arm64_proof_gen as G
r = fb.compile_formal("formal/examples/wide_recv.mojo",
                      output=".tmp/p/wide.aout", prove=False, check=False)
# `prog` is the simple-namespace build.py hands the generator:
#   functions=ordered, i.e. main, Point_set_x, Point_get_x, Point_get_y
print(G._frame_methods(prog, r["code"], r["info"]))
EOF
None
```

`wide_recv.mojo` is a two-field `Point` with `set_x`, `get_x`, `get_y` —
exactly the frame-receiver shape the path is for. `bugs/formal/FORMAL_a_one_field_
mutator_has_no_method_contract.md:150` records that this same call used to
return `['set_x', 'get_x', 'get_y']` on 2026-10-03.

## What I saw

`_frame_methods` walks the words in `[entry, nxt)` where `entry` is the
function's LABEL and `nxt` is the next label in address order, and it drops a
method when any word in that range is a branch (the "leaf shape" test,
`_step_branch_index(w) in (14,15,16,17,51,52,53)`).

Since the stack-floor guard moved into every prologue, the layout is

    Point_get_x       <- the function's label, the GUARD's first instruction
      STP/ADD/ADRP/LDR/CMP
      B.cond  _sf3_ok  <- the guard's conditional branch, inside [entry, nxt)
    Point_get_x_sf3_ok <- the BODY's label
      LDR X0, [X0]; RET

so `_frame_methods` sees the guard's `B.cond` (or, when it does not, finds no
`RET` before `nxt` because the body's `RET` is after the next label) and drops
every frame method. Measured on `wide_recv`: `Point_get_x` is at
`0x1000005f8`…`0x1000005ff` with `0x54000182` (`B.cond`, idx 51) at
`0x1000005fc`, and the body is at `Point_get_x_sf3_ok` = `0x10000062c`.

**Consequence:** `_frame_methods` returns `None` for every image, so
`generate_arm64_proof` never takes the `_generate_frame_proof` branch. The
by-reference receiver's per-method contracts, its `native_decide` run tests and
the whole `[3]`-era frame proof machinery are unreachable dead code — the
"dead code that reads as support" failure CLAUDE.md names. It also changes what
`formal/examples/wide_recv.mojo` refuses with: it falls through to the ordinary
path's "a struct field read has no value in the semantic model", which
`bugs/formal/FORMAL_wide_recv_model_has_no_domain_for_a_struct.md` documents as the
model-domain gap rather than as this wiring.

## What I expected

`_frame_methods` should classify the leaf methods of a frame-shaped struct, as
its own docstring says and as it did before the guard rework. A guard `B.cond`
above the body is not a branch in the METHOD.

## Exact next step

Scope the leaf-shape scan to the method's BODY, not its entry label: the
generator already publishes the body's label as `{fname}_sf{k}_ok`
(`formal/arm64_codegen.py`, `ok_label`), so `_frame_methods` should start the
`rets`/branch/`_frame_slot_accesses` walk at that label when it is present
(the guard's own code is the compiler's, not the method's, and
`_frame_slot_accesses` would return `None` on the guard's `ADRP`/`LDR` anyway).

**Do NOT land this alone.** Re-activating the path changes what the frame
proofs SAY for every frame-shaped image, and the emitted proofs must be
Lean-checked before it is trusted (`lib/ProofLib.olean` is absent on a light
worktree, so this is an integrator/`prooflib` job). Two things it must be
checked against first:

1. The step-lemma domain. `_generate_frame_proof` passes the WHOLE `code` to
   `_gen_step_result_lemmas`/`_gen_step_lemmas`; the data-word fix reads
   `formal/arm64_proof_gen.py::_executable_code`, and the frame emitter now
   uses it, but the re-activated proofs have not been generated from a real
   frame image end to end.
2. `_frame_slot_accesses` / `_frame_store_depths` must be correct over the
   body-only range (they were written when the label WAS the body).

A generation-only check that the finder is live (`_frame_methods(...)` returns
the wide_recv methods) is cheap and Lean-free; the proof check is not.
