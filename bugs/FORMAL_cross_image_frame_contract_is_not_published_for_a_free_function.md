# FORMAL_cross_image_frame_contract_is_not_published_for_a_free_function: the contract is published for a method receiver and not for a free function's struct parameter

**Status: found, measured, NOT fixed.** Filed 2026-10-01 by the
`task:formal2-sweep-3` regression floor, which is
`python3 test_formal_run.py` — 4 assertions fail on the `formal-batch3` tree and
all 4 are this one construct. It is not a stale expectation: the three
cross-module **method** cases of the same family pass with the right answers, and
the free-function half of the same fix does not.

```
$ python3 test_formal_run.py
formal run: PASS=484 FAIL=5

  PASS  byref_cross_module_wide_receiver_reads (36)
  PASS  byref_cross_module_wide_receiver_writes (68)
  PASS  byref_cross_module_one_field_receiver (70)
  FAIL  byref_cross_module_free_function_reads
  FAIL  byref_cross_module_free_function_writes
  FAIL  byref_refuse_cross_module_layout_disagreement
  FAIL  byref_cross_module_star_imported_free_function
```

(The fifth failure, `a_mutated_module_global_is_refused`, is a different thing
and is not this document's subject — see the last section.)

## The refusal, and what it says about the callee's manifest

`test_formal_run.py:3435`'s `run_module_case` writes the callee next to the
program and builds with `fire.py build --formal --no-prove` on both
architectures. Reproduced outside the harness in six lines:

```
$ cat .tmp/probe/byref/byref_xmod.mojo
struct P:
    var a: Int
    var b: Int

def take_it(p: P) -> Int:
    return p.a * 10 + p.b

$ cat .tmp/probe/byref/case.mojo
from byref_xmod import P, take_it

def main(n: Int) -> Int:
    var p = P()
    p.a = 3
    p.b = 4
    return take_it(p) + n

$ python3 tools/memslot.py --gb 8 --label probe -- \
      python3 fire.py build --formal --no-prove .tmp/probe/byref/case.mojo
build: a P receiver is passed to take_it() at argument position 0, and take_it
is compiled into another module, so whether ITS analysis made the parameter in
that position a frame holder is a fact about that module's compilation. Nothing
on this image's link line settles it: the manifest for the module it came from
does not list it as an export, so its compilation never published a contract
for it. … bugs/FORMAL_callee_no_def_ceiling_zero.md records the measurement
```

The manifest is the interesting part, and it contradicts the refusal's wording:

```
$ python3 -c "import json;print(json.load(open(
    '/Users/mrs/.gmojo/cas/formal-imports/arm64/byref_xmod.<key>.arm64.dylib.manifest.json'))['exports'])"

[{"arity": 1, "frame_params": [], "kind": 0, "module": "byref_xmod",
  "name": "take_it", "signature": "int64_t take_it (P *)",
  "symbol": "byref_xmod_take_it_01305a"}]
```

`take_it` **is** listed, with `arity: 1`. What is missing is `frame_params`,
and `resolve_frame_parameter_contract`
(`formal/model.py:6986`) turns that into the wrong sentence: an empty contract
means `position 0 >= len([])`, which is reported as
`CONTRACT_ABSENT_REASONS["not-exported"]` — "the manifest does not list it as an
export". So the refusal names a missing EXPORT where the truth is a missing
CONTRACT. That is worth fixing whatever else happens here: a diagnostic that
points at the wrong layer is the failure mode this backend's messages are
otherwise written against.

## Root cause, located

`formal/build.py:2646`, the loop that publishes the contract:

```python
    for fn in functions:
        hs = holders[_fn_key(fn)]
        if not hs:
            continue                     # ← skips everything below, including…
        …
        fn._frame_param_contract = _parameter_frame_contract(   # :2990
            fn, params_of.get(fn.name) or (), holders.get(fn.name) or (),
            (hstruct.get(fn.name) or {}), declared_holders.get(fn.name) or {})
```

A function the holder fixpoint did not classify publishes **no contract at all**
— not a contract of `Nones`. There is a separate early return for the
module-level case (`:2281`, a module with no framed struct at all publishes
`[None] * n`, and its comment says why: "a `def bump(x: Int, by: Int)` in a
module that declares no struct is exactly the case where a consumer must be told
'that slot is a plain word' rather than 'nothing is known about it'"). The gap
is the middle case: **this module HAS a framed struct, and this particular
function has no recognised holder.**

Why no recognised holder, for this shape: `holders` is a call-site fixpoint
(`formal/build.py:2250`'s `_frame_receivers`), and a free function in a dylib
module has **no call site in its own unit** — every call to it is in the
importer. A method receiver does not have that problem (it is position 0 by
construction), which is exactly the split the three passing cases and the three
failing ones show.

## The next step, and the soundness question it has to answer

Two separable pieces, in this order:

1. **Publish a contract for every function the `continue` skips** —
   `[None] * len(M.function_param_shape(fn).names)` — so the consumer is told
   "plain word" instead of "not exported". This is the `:2281` rule applied
   per function rather than per module, and on its own it turns these three
   FAILs into three different, truthful refusals (`cross_image_plain_parameter_
   refusal`). Cheap, and it fixes the misattributed sentence.

2. **Classify a free function's struct parameter from its DECLARATION**, which
   is the piece that makes the three positive cases build. The evidence is
   already computed and already used: `_parameter_frame_contract`'s docstring
   says "a framed DECLARATION seeds BOTH `holders` and `declared` (the fixpoint
   does not make the two exclusive — `declared` records the EVIDENCE, not a
   different classification)", and its `["one-word"]` branch is reachable only
   for a one-field struct. So the recognition exists; what is missing is that
   the seeding does not happen (or is not consulted) for a function with no
   in-unit call site.

   The soundness argument is the one the method half already makes, and it
   transfers unchanged: the consumer compares the callee's contract names
   against the structs ITS OWN argument is a frame of (`mine & set(holders)`),
   and the importer reads the callee's struct from the module's own source
   (`formal/imports.py`'s `imported_struct_defs`), so both sides computed
   `struct_field_names` from the same class body. A parameter declared `p: P`
   where `P` is a multi-field struct of the callee's module IS a holder of `P`
   by construction — there is no other lowering it could have had.

   **The negative case must keep refusing**: that is
   `byref_refuse_cross_module_layout_disagreement`, whose `Q` and `P` declare
   the same fields in a different order and which the comments say returns 213
   where CPython says 312. It is in the failing four, and a fix that makes the
   three positive cases pass by ignoring the name comparison would make this one
   build and return the wrong number. That test is the oracle for step 2 and
   must not be relaxed to accommodate it.

Verify by building, RUNNING and diffing against CPython — which is what
`run_module_case` already does (expected exits 44 and 96 are CPython's), so a
correct fix turns four FAILs into PASSes with no new test. Add one anyway for
the diagnostic: a callee whose contract is empty must not be reported as
`not-exported`.

## Scope note for the integrator

These four assertions are in `formal-run`, which the suite registry puts in the
`proofs` bucket — **in neither `check` nor `gate`** — so this is not gate-red.
It is red on the regression floor this task is required to run, and the
assertions in question are the first-layer `formal-callee-no-def-2` branch's OWN
positive cases: the test half of that fix is in the tree and the free-function
half of the behaviour is not. Worth knowing before anyone reads a green gate as
covering the cross-module frame hand-off.

## Not this document: the fifth failure

`a_mutated_module_global_is_refused` fails with

```
--backend=arm64 BUILT a construct that has no representation (expected a
refusal naming 'G is declared `global` in bump() and assigned there'); the
binary is the real answer here
```

which is the module-global STORAGE half landing
(`bugs/FORMAL_module_state_no_storage.md`, 2026-09-30) and the test not being
updated with it. `bugs/FORMAL_platform_reachable_row_measured.md:211` already
lists this case among tests that fail with no doc covering them. Stale
expectation, one line of work, not a compiler bug — recorded here so the count
of five is accounted for rather than being re-derived next time.