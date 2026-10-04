# FORMAL_a_dotted_import_resolves_to_a_nearer_leaf: `std.format._utils` from `std/_gpu/_utils.mojo` resolves to `std/_gpu/_utils.mojo`

**Area:** `formal/imports.py::resolve_module_path` / `_candidates` / `_search_roots`
· **Status:** OPEN, measured 2026-10-04 on `work/formal20-std-os-io-2`
(`sweep20:std-os-io-2`) · **Layer:** 1/5 of the formal work

Found while fixing `tools/formal_chain_probe.py` to name the module an
export-gate refusal is about: the probe resolves the module a message names with
`formal.imports.resolve_module_path(name, relative_to=importer)` — the build's
own resolver — and on the `std/{os,io,pathlib,hashlib,base64,ffi,python,_gpu}`
scope that put three files of one round under the group key
`std/_gpu/_utils.mojo`, which is the IMPORTER, not the module that refused. This
doc is why that key was wrong, and it is a defect in the resolver every formal
build uses.

**It is not the probe's bug and not a cosmetic one: the same call inside a real
`fire.py build --formal` returns the wrong file.**

## 1. The measurement

`formal/imports.py::_candidates(name, base, ext)` returns, per search root, in
this order:

    <base>/<name with / >.mojo          <- the dotted path
    <base>/<name with / >/__init__.mojo
    <base>/<LEAF>.mojo                  <- the leaf fallback
    <base>/<LEAF>/__init__.mojo

and `resolve_module_path` loops the roots NEAREST FIRST, taking the first
candidate that exists. So the leaf fallback of a NEAR root is tried before the
dotted path of a FAR root — and when the importer's own directory happens to hold
a file whose basename is the last component of the dotted name, that file wins.

The stdlib has such a collision. `std/_gpu/_utils.mojo` and
`std/format/_utils.mojo` are both `_utils.mojo`:

```console
$ python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from formal.imports import resolve_module_path
p = '.tmp/leafstd/std/_gpu/_utils.mojo'
print(resolve_module_path('std.format._utils', relative_to=p, project_root=p))
PY
.../work-366/.tmp/leafstd/std/_gpu/_utils.mojo      # <- ITSELF
```

**And it is what a real build does**, not only a direct call. Spying on the
resolver inside `fire.py build --formal --no-prove` of a throwaway copy of the
stdlib (`MOJO_STDLIB=<copy>`, with `from std.format._utils import FormatStruct`
added to `<copy>/std/_gpu/_utils.mojo`):

```
SPY resolve('std.format._utils', project_root=set) -> .../std/_gpu/_utils.mojo
     relative_to: .../std/_gpu/_utils.mojo
SPY resolve('std.format._utils', project_root=set) -> .../std/_gpu/_utils.mojo
     relative_to: .../std/_gpu/_utils.mojo
SPY resolve('std.format._utils', project_root=set) -> .../std/format/_utils.mojo
     relative_to: .../std/builtin/builtin_slice.mojo
SPY resolve('std.format._utils', project_root=set) -> .../std/format/_utils.mojo
     relative_to: .../std/collections/bitset.mojo
SPY resolve('std.format._utils', project_root=set) -> .../std/format/_utils.mojo
     relative_to: .../std/memory/alloc.mojo
```

The first two calls — the only ones whose importer is `std/_gpu/_utils.mojo` —
answer with the importer. Every other importer in the same build answers
correctly, which is why the tree looks fine: **the defect needs a basename
collision in the importer's own directory, and only `std/_gpu/_utils.mojo` has
one in this stdlib.**

## 2. What it costs, measured

The build is not visibly wrong yet, and the reason is worth stating so nobody
reads "harmless" into it:

* Adding `from std.format._utils import FormatStruct` to the copy of
  `std/_gpu/_utils.mojo` and defining a local `FormatStruct` there does **not**
  change the build's verdict — it still walks on to the next import. So the
  self-resolution did not silently rebind the name to the importer's own copy; the
  closure walk reached the refusal through a *different* module (`std/memory/alloc.mojo`,
  `std/collections/bitset.mojo`, …), every one of which resolves correctly.
* So today the cost is that a dependency's source is attributed to the WRONG
  module: the chain a reader is shown says `std/_gpu/_utils.mojo` imports
  something that cannot be built, and the thing that cannot be built is a
  different file. That is the failure mode `tools/formal_sweep.py` and
  `tools/formal_chain_probe.py` both exist to prevent, in the one component they
  both trust.
* The blast radius is every build that imports a dotted name whose leaf collides.
  `_utils`, `constants`, `path`, `mask`, `id`, `info`, `alloc`, `glob`, `types`,
  `time`, `random` are all basenames that appear more than once in this stdlib, so
  one more `foo/bar.mojo` beside an importer that says `import …bar` is enough.
  A SELF-RESOLUTION (importer named `X.mojo` importing `a.b.X`) is the degenerate
  case and the most obviously wrong.

## 3. The exact next step

In `formal/imports.py::resolve_module_path`, do not let a near root's leaf
fallback pre-empt a far root's dotted path. The minimal shape:

1. collect candidates per root into two lists — DOTTED (`<name>.mojo`,
   `<name>/__init__.mojo`) and LEAF (`<leaf>.mojo`, `<leaf>/__init__.mojo`) — and
   scan **all** roots for a DOTTED hit first;
2. only if no root has one, scan all roots for a LEAF hit;
3. leave `_candidates` returning one root's four shapes (it has a caller-visible
   contract and its docstring is where the rule is explained), and put the
   two-phase scan in `resolve_module_path` where the root loop lives.

The leaf fallback stays, and it has to: it is what makes `import formal.types`
from inside `formal/` work (`_candidates`' own docstring), and
`_relative_candidates`' docstring records a second case. What changes is only
that it becomes a FALLBACK rather than a same-root tie-break.

Pins, in `test_formal_imports.py` beside the other resolution cases:

* `resolve_module_path('std.format._utils', relative_to=<...>/std/_gpu/_utils.mojo, project_root=…)`
  is `<...>/std/format/_utils.mojo` — §1's first case;
* the leaf fallback still answers when no root has the dotted path (the
  `formal.types` case), so step 2 is not a regression;
* a same-basename pair in the importer's own directory resolves to the DOTTED
  module, which is the property the fix exists to establish.

`tools/formal_chain_probe.py`'s own `test_formal_chain_probe.py` is the second
witness, and it is already written: its `EXPORT_GATE` cases pin the resolved FILE
per refusing module, and adding `std/_gpu/_utils.mojo` to `EXPORT_GATE` turns the
probe's key for those three files from wrong to right. That case is deliberately
NOT added here, because it belongs to whoever takes this fix and the failure
message is far clearer from the test than from §1.

## 4. Why nothing was done here

`formal/imports.py` is the module resolution rule for every formal build and
every dylib edge, it is not in `sweep20:std-os-io-2`'s claim, and this branch's
rule is not to work another claim's problem. §3 is small and specific precisely
so the next person can take it whole.

## 5. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
S=/Users/mrs/net/chatgpt/claude/new-modular/Mojo/stdlib
rm -rf .tmp/leafstd && cp -r $S .tmp/leafstd

# the collision, and the two files that prove which one wins
ls .tmp/leafstd/std/_gpu/_utils.mojo .tmp/leafstd/std/format/_utils.mojo
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from formal.imports import resolve_module_path, _candidates
p = '.tmp/leafstd/std/_gpu/_utils.mojo'
print('candidates under the importer\'s own root:',
      _candidates('std.format._utils', '.tmp/leafstd/std/_gpu', '.mojo'))
print('resolved:', resolve_module_path('std.format._utils',
                                       relative_to=p, project_root=p))
PY

# …and inside a real build, with the resolver instrumented
# (tools/memcap.py --gb 8 --label spy -- python3 .tmp/spy.py build --formal
#  --no-prove -o .tmp/leafstd/u.aout $PWD/.tmp/leafstd/std/_gpu/_utils.mojo)
```

No Lean runs; `MOJO_STDLIB` points the throwaway copy, and the real stdlib is only
ever read. The spy is six lines: wrap `formal.imports.resolve_module_path`, print
the module name and the answer, and `import fire; fire.main()`.