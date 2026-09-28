# INTERFACE REQUESTS — agent [5], FORMAL-PARALLEL round 1

Everything here is a change in a file [5] does not own, with the diff written
out so the integrator can apply it without re-deriving the reasoning. None of
it blocks [5]'s landed work; all of it is in files I was told not to touch.

Landed by [5], for reference: `formal/lean.py` (hole census made readable and
complete), `tools/formal_sweep.py` (reach split + a system-module-call class),
new `test_formal_sweep_truth.py`, and the [4]-integration fix in §6.

**RESOLVED since this was written — do not apply these:**
§1 and §2 were both implemented by [4] in `9caf8aa`/`464c857` (fire.py's
`_sorry_note`, and the `HOST_MODELLED`/`HOST_UNREACHABLE` split this document
asked for). §6 was fixed here. §7 is new. **§3, §4 and §5 are the only open
items**, and none of them blocks anything.

---

## 1. `to=[1]`  file=`fire.py`  — the census belongs next to `Proof:` — **RESOLVED by [4]**

**RESOLVED by [4] in `9caf8aa` (`fire.py:_sorry_note`).** Kept because it
records where the gap was closed and why stderr was enough to get there.

`formal/lean.py` writes the census to stderr from `check_proof_cached`, so it
appears in every `fire.py build --formal` log without any change to a file four
agents were working in. What it does not do is appear on **stdout**, beside the
`Proof: <path>` line — which is where a reader looks, and the only line `fire.py`
prints about a proof. `formal/lean.py:census_report(proof_path)` is the
read-side display and runs no Lean; it is the one-liner.

    INTERFACE REQUEST  from=[5]  to=[1]  file=fire.py
    WHAT: two sites, ~line 200 (`_formal_executable`) and ~line 913 (the
          `dylib --formal` path). After the existing
          `print(f"Proof: {result['proof_path']}{cached}")` add:

              from formal.lean import census_report
              for line in census_report(result["proof_path"]):
                  print(line)

    WHY: the sorry census was returned by `check_proof_cached`, stored by
         `formal/build.py` in `result["proof_sorries"]`, and read by NOTHING.
         A proof with a thousand `sorry`s and a proof with none printed the same
         `PASS`. It now goes to stderr; stdout is where it will be seen.
    BLOCKS: nothing of mine. [5]'s done-criterion is met by the stderr channel.

The two sites are the same two lines `fire.py` already duplicates for
`proof_cached`, so this is a copy of an existing duplication rather than a new
one. `FORMAL_CENSUS=off` silences the stderr copy if [1] prefers stdout-only.

---

## 2. `to=[4]`  file=`formal/imports.py`  — the reach split — **RESOLVED by [4]**

**RESOLVED by [4] in `464c857`, item 4**, as `HOST_MODELLED` / `HOST_UNREACHABLE`
plus a `host_module_tier()` accessor. The sweep reads it through that accessor
and reports `formal/imports.py` as the authority; the pinned mirror this request
was written against no longer exists (`IN_REACH_HOST_MODULES` is now a *derived*
view — `IN_REACH_HOST_MODULES = _in_reach_from_authority()` — and the fallback
set is empty, so the sweep reports "cannot size this" rather than a smaller
number that reads like a measurement). The original ask is kept for the record.

`tools/formal_sweep.py` now prints how many of the host-import files import a
module a Mojo-side implementation could in principle provide. It **reads** the
split from `formal/imports.py` and only falls back to a pinned local mirror
while no split is published, so this request is what turns a stated estimate
into a read fact.

    INTERFACE REQUEST  from=[5]  to=[4]  file=formal/imports.py
    WHAT: publish the two tiers. Any of these shapes is read already — the
          sweep tries them in order and none of them needs a change in
          `tools/formal_sweep.py`:

              HOST_MODULE_TIERS = {"modelled": frozenset(...),
                                   "unreachable": frozenset(...)}
              # or
              HOST_MODELS_IN_REACH = frozenset(...)
              HOST_MODELS_UNREACHABLE = frozenset(...)

          modelled:   os sys math struct time json re
          unreachable: everything else in HOST_MODULES (subprocess, ctypes,
                        asyncio, threading, socket, tempfile, signal, …)

    WHY: `CLASS_HOST`'s blurb said a host import is "outside this backend's
         reach, and not fixable". That is true of `subprocess` and FALSE of
         `os`, so the sweep's largest bucket was asserting something untrue
         about 115 of its 164 files. [4] owns the split; the sweep must not
         keep a second copy of it.
    BLOCKS: nothing. The sweep runs today on the mirror and says so in its own
            output ("from this tool's pinned mirror").

**And then delete `IN_REACH_HOST_MODULES` from `tools/formal_sweep.py`.**
`test_formal_sweep_truth.py::test_the_mirror_and_the_authority_agree` fails the
moment the two disagree, and says to delete the mirror — so the fallback cannot
rot unnoticed, and this request is also the cleanup it is waiting for.

---

## 3. `to=[integrator]`  file=`tools/suite.py` — register the new test

    INTERFACE REQUEST  from=[5]  to=[integrator]  file=tools/suite.py
    WHAT: register `test_formal_sweep_truth.py` in the `check` bucket. No
          `deps`, no `memclass` beyond the default: it builds nothing and runs
          no Lean (the one case that needs Lean SKIPs without it), so it costs
          ~0.2s.

          A note for the `prooflib` step rather than a change: the library hole
          census is captured for free out of the run that builds
          `lib/ProofLib.olean`, so `test_formal_sweep_truth.py`'s
          `test_the_library_has_known_holes_and_they_are_named` gets its data
          from `prooflib` existing. It SKIPs, loudly, if no census is recorded.
    BLOCKS: nothing. The test is written and green standalone.

**Two files need registering, not one.** `grep -n formal tools/suite.py`
registers `test_formal_sweep.py` (`formal-sweep`, line 619) and nothing else —
so `test_formal_sweep_truth.py` (mine, 31 checks) **and**
`test_formal_link_accounting.py` ([4]'s, 83 checks) are both unregistered. The
second is worth raising explicitly because [4]'s audit is now the thing standing
between a real backend defect and a `codegen` misclassification on the
executable path, and the suite that pins it is not in the gate.

---

## 4. `to=[integrator]`  file=`test_formal_dylib.py` — a check that cannot fail

    INTERFACE REQUEST  from=[5]  to=[integrator]  file=test_formal_dylib.py:388
    WHAT: that case reads

              check("sorry" not in text and "admit" not in text,
                    "generated dylib proof contains sorry/admit")

          and `text` is the GENERATED proof. The three holes that decide this
          proof's verdict are in `lib/`:

              lib/ProofLib.lean  in_image_stub     := by sorry
              lib/ProofLib.lean  semantics_stub    := by sorry
              lib/Refine.lean    dylib_export_contract_stub := by sorry

          Lean emits no warning for a hole in a module consumed from a
          pre-built `.olean`, so the grep cannot see them, and it is green
          today. The census now reports all three, by name, from
          `formal/lean.py`:

              from formal.lean import library_census, find_lean
              lib = library_census(find_lean(HERE), os.path.join(HERE, "lib"))
              holes = {n for _c, names in lib.values() for n in names}
              check(not holes, f"the dylib proof rests on admitted holes: "
                               f"{sorted(holes)}")

    WHY: this is the single case where a library hole changes a verdict, and it
         is the case the grep was written for. The text check should stay — it
         still catches a hole in the generated file — but it is not sufficient
         and currently reads as though it were.
    BLOCKS: nothing of [5]'s. [5]'s own test pins the census that would make
            this check possible.

**Measured, and worth having in the same commit:** the same hole census
(`dylib_export_contract_stub`) is invoked by `formal/arm64_proof_gen.py:8338`
with `obs := fun n => n` — asserting that **every** dylib export's behaviour is
the identity map. That is not a vacuous proof, it is an admitted `sorry` over a
claim that is false; the census makes it visible, and FORMAL-PARALLEL §6 already
records it. Nothing to change here — nothing in `lib/` may be edited this
round — but the request is that whoever merges know the figure is now *read*
rather than merely *known*.

---

## 5. `to=[integrator]`  file=`test_formal.py` — the census it prints is half a census

    INTERFACE REQUEST  from=[5]  to=[integrator]  file=test_formal.py
    WHAT: `SORRY_CENSUS` / `_sorries_in` (`:200-210`) read `check_proof_cached(...)[3]`
          and print

              sorry census: 7 declaration(s) still admit a sorry, in 6 of 29
              proof(s) checked

          which is right and is the project's best existing reader of the
          figure. It is also only the generated file's half. `proof_census` now
          returns a `Census` with the library's holes and the vacuous
          declarations beside it, so the line can say, in one go:

              proof census: 7 admitted `sorry` in the generated file, 3 in
              lib/ (ProofLib: in_image_stub, semantics_stub; Refine:
              dylib_export_contract_stub), 2 vacuous (extern_mojo_print_step,
              …)

          The minimal change is to read `L.proof_census(path).lines` instead of
          indexing `[3]`.
    BLOCKS: nothing. [5]'s done-criterion ("a sorried proof and a vacuous one
            are distinguishable in the output") is met by the stderr channel;
            this makes it visible in the suite's own summary too.

---

## 6. `test_formal_sweep.py` was red from [4]'s bind audit — **FIXED HERE**

`python3 test_formal_sweep.py` was 48 tests, 1 failure + 1 error, both caused by
[4]'s bind audit landing on the executable path (`464c857`, item 3). Neither was
a regression from this round, and both are now fixed in
`test_formal_sweep.py`, which is adjacent to [5]'s work. Current: **56 tests,
OK.**

  * **`TestDyldProbe.setUpClass` — the `bogus.mojo` fixture no longer builds.**
    The audit now refuses the image at build time instead of producing an
    unresolvable one, which is the better behaviour and removes the artifact
    the probe's true-positive test needed. The fixture now (a) asserts the
    refusal really is the audit's, by checking `_EXTERN_BUILD_MARK` is in it —
    so if the audit ever stops covering the executable path, the failure says
    *that* rather than "Symbol not found not in …"; and (b) synthesizes the
    image the probe must still catch, via
    `macho_linker.build_macho_executable_extern`, the way the sibling tests in
    the same class already do. The dylib in that image has to be a *real* one
    with an empty symbol set: naming a path that does not exist makes dyld
    report `Library not loaded` before it ever looks at the symbol, so the
    assertion would be corroborating a different failure than the probe exists
    to corroborate. The probe is still live code — the dylib path still
    produces loadable images with unresolvable binds.

  * **`test_dyld_unresolvable_is_not_coverage` — a stale oracle.** It pinned
    the reason string exactly, and [4]'s classifier now distinguishes the two
    causes in the reason (`caught when the build refused the image` vs. not). It
    now asserts the count and the class. A new sibling,
    `test_a_build_time_bind_refusal_is_not_coverage_either`, pins the
    build-time cause as `CLASS_EXTERN` — the expensive half of that
    misclassification, since `codegen` would count against the backend, deflate
    the coverage rate, make the run exit 1, and point the next reader at a
    construct the backend was right to refuse.

---

## 7. `to=[4]` / `to=[integrator]`  file=`formal/build.py:629` — a message that denies itself

Not a regression, and small, but it is the same class of defect as everything
else in this round: a message that states something false about the reader's
own build.

`_unaccounted_report` says, of a set of symbols **nothing provides**:

    These are constructs this backend does not lower (a struct type, a method
    call on a value, a compiler intrinsic), not exports that are missing.

The second clause contradicts the finding it is attached to. Provenance: this
wording is pre-existing, on the dylib path at `464c857^:formal/build.py:4335`;
[4] generalized it to both paths unchanged, so it reads the same as it did
before. The reason it is worth a line now: the audit fires on the *executable*
path for the first time, where the overwhelmingly common cause of an undefined
call really is a call the backend failed to lower — which is what the message
asserts. The reader therefore cannot tell a backend defect (a call that should
have been emitted and wasn't) from a program asking for a symbol nobody has.
Both are `not-answerable` to the sweep and both are worth fixing, but they are
different work, and this sentence tells the reader they are the same thing.

    INTERFACE REQUEST  from=[5]  to=[4]  file=formal/build.py
    WHAT: drop the self-contradicting clause, or replace it with the one
          diagnostic that actually separates the two cases — whether the
          undefined name appears as a *call target in the model* (backend
          should have lowered it) or only in `external_syms` (nobody has it).
    BLOCKS: nothing. No behaviour depends on the wording; `test_formal_sweep.py`
            only checks that the marker `_EXTERN_BUILD_MARK` is present, which
            is the *first* sentence.
