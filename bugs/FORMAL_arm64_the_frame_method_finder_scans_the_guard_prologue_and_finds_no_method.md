# the arm64 frame-method finder scans the stack-floor GUARD prologue, so it finds no method and the by-reference receiver proof path is dead

**Area:** FORMAL, arm64 — `formal/arm64_proof_gen.py::_frame_methods` (and the
`_generate_frame_proof` path it gates). Found 2026-10-14 while checking whether
`_generate_frame_proof` still emits step lemmas over the image's string data
(the arm64 data-word bug, whose ordinary and DYLIB halves are fixed; the frame
half is unreachable because of THIS).

**Status: PARTIAL FIX, verified 2026-11-02; re-verified 2026-11-03 (regression test passes). Root-cause fix (finder extent + body scan) confirmed. Master does NOT yet have the fix (branch carries commits `6fbc15ac6`, `c39e0c8c1`, `8bc66b37f`). Step 1 (bind scalar non-receiver params in `_generate_frame_proof` model so `set_x` gets a contract) and Step 2 (`prooflib` Lean check over emitted frame proofs) remain open. Doc stays until end-to-end verified over corpus.** The finder is live. Root cause, as
measured: `_frame_methods` took a method's extent as "up to the NEXT LABEL in
address order", and the codegen also labels points inside a body
(`{fname}_sf{k}_ok`, the stack-floor guard's `_ok`). So `Point_get_x`'s extent
ended at its own body label, and the body's `RET` lay outside it. A second,
independent defect sat behind it: the body-only scan lost the receiver's
register copy (`ADD x19, x0, #0`), which the PROLOGUE sets and the body reads.

**Round 2026-11-03 (planning, step 1 measured; nothing new landed in code).**
Step 1 is blocked on a Lean-side check the light-worker cap cannot run, so
this round records the measured fix and its exact edits.

Measured on this branch (`python3` probe of `_generate_frame_proof` on
`wide_recv`, image captured with the spy in `test_formal_frame_method_finder.py`):
the refusal is `model: \`v\` is read here ... (the model's environment is
['self'])`, raised from `_expr_go` inside `_gen_universal_e2e_cfg(fn=f)` for
`Point_set_x`, because the setter's entry env binds only `self`.

Planned edit (`formal/arm64_proof_gen.py::_frame_section`), tried and generated
cleanly (579 KB, no `sorry`/`admit`, `wide_recv` now emits `main_Point_set_x_frame_contract`):

```diff
-        init_extra = (f"sp := UInt64.ofNat {sp0}, mem := hmem"
-                      + (", x1 := v" if m["kind"] == "set" else ""))
+        init_extra = f"sp := UInt64.ofNat {sp0}, mem := hmem"
 ...
-            conj = [f"Frame.frameRead s.mem n {slot} = v"]
+            conj = [f"Frame.frameRead s.mem n {slot} = n1"]
 ...
-            params = "n v : UInt64) (hmem : Nat → UInt8"
+            params = "n n1 : UInt64) (hmem : Nat → UInt8"
 ...
             fn=f, tw_extra="", tc=..., cond_branches=set(), code_name=..., sr_name=stem,
+            entry_arity=max(1, len(f.params or [])),   # binds v to n1 via _entry_arg_names
             frame={"func_end": m["end"], ...
```

Why each line: `_entry_env` binds the source parameter `v` to the theorem binder
at its position, which `_entry_arg_names` names `n1`; `_entry_arg_with` already
emits `x1 := n1` in the CFG's entry state, so keeping `x1 := v` in `init_extra`
writes the field twice (`{ … with x1 := n1, …, x1 := n1 }`), which Lean rejects.

**Not verified, and why:** Lean has not accepted the generated set proof.
`formal.lean.check_proof` on the generated file under `memslot --gb 8` was
killed by the cap (no output, exit 1); `lib/ProofLib.olean` does not exist in
this worktree, so the check first builds it (`ensure_library`, ~80 s, 27 MB)
and then typechecks a 579 KB file. The integrator needs to run it with a larger
budget:

    python3 -c "import sys; sys.path.insert(0,'.'); from formal import lean; print(lean.check_proof('<generated.lean>', repo_root='.'))"

Pins that flip when the edit lands, and must be updated in the same commit
with the Lean verdict: `test_formal_call_proof_gen.py::TestStructFieldHasNoValueInTheModel::test_the_refusal_is_the_model_domain_one`
(asserts the refusal, now absent), and `test_formal.py`'s `wide_recv`
`EXPECTED_FAILURES` marker (if Lean accepts, the marker must be dropped; if it
rejects, the marker's reason must name the Lean error).

Landed in `formal/arm64_proof_gen.py` (earlier rounds):

* the extent is now `[entry, next FUNCTION entry)`, cut also at any label that
  is not named `{fname}_…` (code belonging to no function); the leaf method ends
  at its FIRST `RET`;
* the body starts at the guard's own `{fname}_sf{k}_ok` label (the
  `ok_label` `arm64_codegen.py` publishes); the earlier B.cond scan is gone;
* `_frame_slot_accesses(words, entry, end, body=)` walks the prologue only to
  carry the receiver's register copies forward; its loads are not accesses;
* `generate_arm64_proof` resolves `fn` before the frame branch. The branch reads
  `fn` for its `@refines` note; the lookup used to come after it, so any image
  the finder now reports hit `UnboundLocalError`. This was the exposed defect of
  the finder going live, not a separate one.

Verified: `test_formal_frame_method_finder.py` (new) returns
`Point_set_x: set`, `Point_get_x: get`, `Point_get_y: get` on `wide_recv`; it
FAILS on the pre-fix generator (finder returns `None`) and passes now.

Consequences, measured, and NOT Lean-checked:

* `wide_recv`'s get-only variant (the `test_formal_call_proof_gen.py`
  divergence row) now gets a by-reference frame proof on arm64 instead of an
  ordinary-model refusal. Its pin was rewritten to the new fact.
* `wide_recv` as written (with `set_x`) is still refused, now by
  `_generate_frame_proof`: `v` (Point_set_x's scalar parameter) is read and the
  frame model binds only `self`. The `test_formal.py` `wide_recv` marker and the
  `TestStructFieldHasNoValueInTheModel` pin were rewritten to that refusal.

Remaining, in order:

1. Bind a frame method's scalar (non-receiver) parameters in the frame model
   (`_generate_frame_proof`'s environment), so `set_x` gets a contract.
2. Lean-check the frame proofs that are now emitted (`prooflib` job). Until then
   they are generated, not accepted. `_frame_methods` is the only change that
   turns the frame path on for a new image, so this is what to check first.
3. Only then delete this doc: the frame proof path must be verified end to end
   over the example corpus, not just the finder.

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
exactly the frame-receiver shape the path is for. `bugs/FORMAL_a_one_field_
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
`bugs/FORMAL_wide_recv_model_has_no_domain_for_a_struct.md` documents as the
model-domain gap rather than as this wiring.

## What I expected

`_frame_methods` should classify the leaf methods of a frame-shaped struct, as
its own docstring says and as it did before the guard rework. A guard `B.cond`
above the body is not a branch in the METHOD.

## Exact next step (2026-11-02)

The finder step is done (see Status). The next step is Status item 1: bind a
frame method's scalar parameters in `_generate_frame_proof`'s model, then the
`prooflib` Lean check of the emitted frame proofs (Status item 2). The check
that the finder is live is `python3 test_formal_frame_method_finder.py`.
