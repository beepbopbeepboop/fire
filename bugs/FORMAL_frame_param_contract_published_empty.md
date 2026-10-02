# FORMAL_frame_param_contract_published_empty: every cross-module frame hand-off is refused because the contract publishes `[]`

**Status: found, MEASURED, NOT fixed.** Four calls to `.get(fn.name)` on tables
that are filed under `id(fn)`, in `formal/build.py`'s per-function loop. The
consequence is that the per-parameter frame contract every module publishes for
its exports is **always `[]`**, so every cross-module frame hand-off on this path
is refused as "not-exported" — and `test_formal_run.py` carries four cases that
say so. Found 2026-10-01 as a side effect of running the regression floor for
`construct:declared-param-vs-call-sites`; it is not that construct's fix and is
not mine to land.

## 1. What is red, on this tree, before any change of mine

```
$ python3 test_formal_run.py
formal run: PASS=484 FAIL=5

$ python3 test_formal_run.py byref_cross_module_free_function_reads
  FAIL  byref_cross_module_free_function_reads: … the manifest for the module
        it came from does not list it as an export, so its compilation never
        published a contract for it …
```

The five are `byref_cross_module_free_function_reads`,
`byref_cross_module_free_function_writes`,
`byref_refuse_cross_module_layout_disagreement` and
`byref_cross_module_star_imported_free_function` — this doc — plus
`a_mutated_module_global_is_refused`, which
`bugs/FORMAL_platform_reachable_row_measured.md:211` already records as an
undocumented gap on master (that doc's own list is the five empty-container /
module-global cases, four of which have since been fixed; these four are new).

`formal-run` carries **no `expect=` marker** in `tools/suite.py`, so this is a
gate FAILURE on the tree as it stands, not a known-red.

## 2. The defect, in four reads

Every per-function table in the frame analysis is filed under `_fn_key(fn)`,
which is `id(fn)`:

```python
formal/build.py:2456    holders = {_fn_key(fn): set() for fn in functions}
formal/build.py:2457    hstruct = {_fn_key(fn): {} for fn in functions}
formal/build.py:2425    params_of[_fn_key(fn)] = names
formal/build.py:2484    declared_holders = {_fn_key(fn): {} for fn in functions}
```

`_fn_key`'s own docstring (`formal/build.py:2274`) explains why identity and not
the name: 53 of 1595 files in the sweep roots declare some name more than once,
and keying by name made the first definition's answer stand for all of them.

The publication of the cross-image contract reads all four by NAME:

```python
formal/build.py:3084
        fn._frame_param_contract = _parameter_frame_contract(
            fn, params_of.get(fn.name) or (), holders.get(fn.name) or (),
            (hstruct.get(fn.name) or {}), declared_holders.get(fn.name) or {})
```

Those are the only four `.get(fn.name)` reads of those tables in the file; every
other reader uses `_fn_key`. So `params_of.get(fn.name)` is `None`, the
parameter list arrives as `()`, and `_parameter_frame_contract` — which iterates
`params` — returns `[]` for every function in every module.

Measured, by printing the published table while building a two-file program:

```
DBG export take_it: _frame_param_contract=[] -> []
```

and the manifest it writes
(`~/.gmojo/cas/formal-imports/<arch>/<module>.<hash>.dylib.manifest.json`):

```json
{"name": "take_it", "symbol": "byref_xmod_take_it_01305a",
 "signature": "int64_t take_it (P *)", "arity": 1, "frame_params": [], "kind": 0}
```

**The signature says `P *` and the contract says nothing**, which is the whole
inconsistency in one line: the dylib was compiled with a frame-address parameter
and told its consumers it has no contract at all.

## 3. Why the consumer then says "not-exported"

`model.resolve_frame_parameter_contract` (`formal/model.py:6986`) reads the
contract positionally and has three "no contract" answers. With `[]`:

* `contract is None` — no, a list;
* `position >= len(contract)` — `0 >= 0`, **true**, so it answers
  `CONTRACT_ABSENT_REASONS["not-exported"]`, whose text is "the manifest for the
  module it came from does not list it as an export, so its compilation never
  published a contract for it".

That is a false statement about the manifest: the manifest lists `take_it` (the
JSON above), it publishes a contract, and the contract is empty because of four
reads. **The message sends the reader to look for an export filter that is not
the problem**, which is why this cost a session to place.

## 4. Reproducer (two files, both in `.tmp/`)

```console
$ mkdir -p .tmp/probe/xmod && cd .tmp/probe/xmod
$ cat > byref_xmod.mojo <<'EOF'
struct P:
    var a: Int
    var b: Int

def take_it(p: P) -> Int:
    return p.a * 10 + p.b
EOF
$ cat > main.mojo <<'EOF'
from byref_xmod import P, take_it

def main(n: Int) -> Int:
    var p = P()
    p.a = 3
    p.b = 4
    return take_it(p) + n
EOF
$ python3 fire.py build --formal --no-prove main.mojo
build: a P receiver is passed to take_it() at argument position 0, and take_it
is compiled into another module, so whether ITS analysis made the parameter in
that position a frame holder is a fact about that module's compilation. Nothing
on this image's link line settles it: the manifest for the module it came from
does not list it as an export …
```

CPython's answer for the same two files is **44** (`3 * 10 + 4 + 40`), which is
what `byref_cross_module_free_function_reads` asserts.

## 5. The exact next step

1. Key those four reads by `_fn_key(fn)`, the way every other reader of those
   tables already does. Nothing else in the function is wrong.
2. Then **measure the marginal effect before believing it**: a contract that was
   empty for every export in every module means every cross-module hand-off in
   the stdlib is currently refused at this gate, so the four reads can move a
   large number of files at once. `python3 tools/formal_sweep.py` over
   `std/collections`, `std/string`-adjacent modules and the cross-module tests is
   the measurement; expect the `codegen/dependency` and
   `not-answerable/unresolved-*` classes to move, and expect some of what moves
   to be a new refusal rather than a pass.
3. The four `byref_*` cases above are the regression, and they assert EXECUTION
   on both architectures, so step 1 is verified by running
   `python3 test_formal_run.py byref_` rather than by "it builds".
4. `byref_refuse_cross_module_layout_disagreement` is the negative control and
   wants `cross_image_frame_disagreement_refusal`'s wording
   ("own manifest says the parameter in that position is a frame holder of Q"),
   which is only reachable once the contract is non-empty — so it is also the
   case that says the fix did not turn the disagreement check off.

**Deliberately not landed here.** This is the cross-image contract publication
(`construct:frame-address-escapes` /
`construct:receiver-position-and-no-representation` territory), it is four reads
in `formal/build.py` next to code this session did change, and a fix that
unblocks every cross-module hand-off in the tree is not a light worker's to land
unmeasured. The measurement above is the contribution.