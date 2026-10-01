# FORMAL_frame_param_contract_is_published_empty: four `_fn_key` tables read by NAME, so every module dylib publishes `frame_params: []`

**Status: found and MEASURED, not fixed. One line, and it turns four RED cases
in `test_formal_run.py` green — verified, not predicted.** It is in another
worker's claim (`construct:callee-no-definition-2`,
`bugs/FORMAL_callee_no_def_ceiling_zero.md` §4), so it is handed over rather
than taken.

## The smallest reproducer

Two files, twelve lines each, no imports beyond each other:

```mojo
# byref_xmod.mojo
struct P:
    var a: Int
    var b: Int


def take_it(p: P) -> Int:
    return p.a * 10 + p.b
```

```mojo
# main.mojo
from byref_xmod import P, take_it


def main(n: Int) -> Int:
    var p = P()
    p.a = 3
    p.b = 4
    return take_it(p) + n
```

```console
$ python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/main.macho .tmp/main.mojo
build: a P receiver is passed to take_it() at argument position 0, and take_it is
compiled into another module, so whether ITS analysis made the parameter in that
position a frame holder is a fact about that module's compilation. Nothing on
this image's link line settles it: the manifest for the module it came from does
not list it as an export, so its compilation never published a contract for it.
…
```

CPython prints 44 for the same program.

**The refusal's middle sentence is false about the manifest.** It says the
manifest "does not list it as an export". It does:

```console
$ python3 fire.py dylib --formal --no-prove -o byref.dylib byref_xmod.mojo
$ python3 -c "import json;d=json.load(open('byref.dylib.manifest.json'));print([(e['name'], e['frame_params']) for e in d['exports']])"
[('take_it', [])]
```

The export is there. Its `frame_params` — the per-parameter frame-holder
contract this mechanism exists to publish — is the EMPTY LIST.

## Why it is empty: the tables are keyed by `_fn_key`, and this call site reads
them by `fn.name`

`formal/build.py:3147`:

```python
fn._frame_param_contract = _parameter_frame_contract(
    fn, params_of.get(fn.name) or (), holders.get(fn.name) or (),
    (hstruct.get(fn.name) or {}), declared_holders.get(fn.name) or {})
```

`params_of`, `holders`, `hstruct` and `declared_holders` are all keyed by
`_fn_key(fn)` — which is `id(fn)`, deliberately, for the reason `_fn_key`'s own
docstring gives ("these tables answer *what does THIS body do with its own
names* … Mojo overloads make that ordinary"). Four `.get(fn.name)` calls on an
identity-keyed table therefore return `None` for every function whose name
happens not to be a table key, which after `_fn_key` was introduced is **every
function**: `_parameter_frame_contract` iterates an empty `params` tuple and
returns `[]`, and `_export_frame_contract` publishes that as the export's
`frame_params`.

So the consumer is told "this compilation could not classify it"
(`_export_frame_contract`'s own words for `[]`) for **every** module dylib
export, and `resolve_frame_parameter_contract` — which is careful to treat "no
contract" as unanswerable rather than as "an ordinary word" — refuses every
cross-module frame hand-off.

Instrumented, one line of output:

```
_export_frame_contract(take_it) -> []   [attr=set]
```

`attr=set` because `_parameter_frame_contract` ran and returned `[]`, not
because the attribute was missing — which is what makes this a wrong answer
rather than an absent one.

It is the same defect `_fn_key` was introduced to fix, at the one call site that
was missed. Where a name IS overloaded it is worse than empty: the call site
takes whichever definition's tables the name happens to key, which is the
"first definition's answer stands for all of them" bug in its original form.

## What it costs, measured

`test_formal_run.py`, four cases, on this tree as committed (all four RED):

| case | expected | message it gets |
|---|---|---|
| `byref_cross_module_free_function_reads` | 44 | refused: manifest "does not list it as an export" |
| `byref_cross_module_free_function_writes` | 96 | refused: same |
| `byref_cross_module_star_imported_free_function` | 44 | refused: same |
| `byref_refuse_cross_module_layout_disagreement` | refused, naming `Q` | refused, but not with the sentence the case requires |

`bugs/FORMAL_callee_no_def_ceiling_zero.md` §4c tabulates exactly these four as
cases the landed contract fix "bought", with the wrong-address numbers each one
would hide (96 vs 46 for the write, 213 vs 312 for the layout disagreement). So
the fix that doc describes is in the tree and not doing anything: the contract it
publishes is empty, and the four cases that would have measured it are red.

**Verified pre-existing, not a regression from the reliability branch this was
found on**: the same four cases fail identically with `formal/` at the parent
commit, and the same two-file program produces the byte-identical refusal
message there.

## The next step

One expression, four `.get(fn.name)` → `.get(_fn_key(fn))`:

```python
fn._frame_param_contract = _parameter_frame_contract(
    fn, params_of.get(_fn_key(fn)) or (), holders.get(_fn_key(fn)) or (),
    (hstruct.get(_fn_key(fn)) or {}), (declared_holders.get(_fn_key(fn)) or {}))
```

**Measured, on this tree, with that change applied in place and then reverted:**

```console
$ python3 test_formal_run.py byref_cross_module_free_function_reads \
    byref_cross_module_free_function_writes \
    byref_cross_module_star_imported_free_function \
    byref_refuse_cross_module_layout_disagreement
  PASS  byref_cross_module_free_function_writes (96)
  PASS  byref_refuse_cross_module_layout_disagreement (own manifest says the parameter in that position is a frame holder of Q)
  PASS  byref_cross_module_star_imported_free_function (44)
  PASS  byref_cross_module_free_function_reads (44)
formal run: PASS=4 FAIL=0
```

(the read case reported `timed out` in the first four-case run — this machine had
six other workers' suites on it — and passes when run alone, so the 120 s
`BUILD_TIMEOUT` is the only thing it hit.)

Two things worth doing with it, both cheap:

* `_export_frame_contract`'s `[]` is documented as "this compilation could not
  classify it", and after the fix `[]` is nearly unreachable — a function with no
  parameters legitimately has `[]`, so keep the branch, but the docstring should
  say that a one-parameter function publishing `[]` is the bug this doc is about,
  because that is the shape a reader meeting it will recognise fastest.
* A test that asserts a module dylib's `frame_params` is non-empty for an
  exported function that takes a frame would have caught this at the point of
  publication rather than through a consumer's refusal four layers away.
  `test_formal_dylib.py` is where the manifest is already read.

## Why it is not fixed here

It is `construct:callee-no-definition-2` — the cross-module frame hand-off — and
that claim is held by another worker whose branch is already merged. This
session's share is the reliability of the build and its instruments; the
measurement is the handover.