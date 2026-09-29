# A module-qualified call `mod.fn()` was refused, and the message told you to write one — FIXED

**Area:** CODEGEN (formal arm64 + x86-64): `formal/build.py`'s
`check_module_symbols` and `load_dylib_manifests`. **Found while:** writing
`struct.mojo` for the formal backend (worker `mod-struct`), which is the
change that made `import struct` resolve — and so made this the next thing
standing in the way of the seven files that use it.

**Status: FIXED in the same branch that added `struct.mojo`** (both backends,
by construction — the fix is in the shared front end, `formal/build.py`). The
write-up below is kept whole because the two halves failed DIFFERENTLY and
only measuring both showed that; the second one is the half a single-minded
reading of the first would have got wrong.

## What I ran

```
$ cat AD.py
import struct

def main():
    b = struct.pack("<I", 7, 0, 0, 0, 0, 0, 0)
    return 0

$ python3 fire.py build --formal --no-prove AD.py
build: main: 'struct' is imported from `struct`, so it is a module-level name
of another module. This path compiles an import into a dylib, and a
module-level name is not exported as a word — there is no storage for it here:
every value a formal program can name lives in a function's own stack scratch,
which is reclaimed when the function returns. Give it a function (a
`struct.fn()` call lowers) or write the value at the use site
```

The advice in that message is exactly the program above. It did not lower.

The other spelling of the same call, which the message did not mention, worked:

```
$ cat AE.py
from struct import pack

def main():
    b = pack("<I", 7, 0, 0, 0, 0, 0, 0)
    return 0

$ python3 fire.py build --formal --no-prove AE.py
Built: AE.bin  [arm64/macho]
```

So the module boundary worked and `struct.pack` was exported and callable;
what was refused was the SPELLING, and the diagnostic told the reader to use
the spelling that was refused.

## Why — and why fixing only this was not enough

`check_module_symbols` walks a function's `IdentExpr` nodes and refuses any it
cannot place. A call's callee is excluded, because a callee names a symbol
rather than reading a value — but the exclusion is collected by node identity
and only for a callee that IS an `IdentExpr`:

```python
# formal/build.py:3095
callees = {id(c.func) for c in M.iter_nodes(fn.body)
           if isinstance(c, F.CallExpr) and isinstance(c.func, F.IdentExpr)}
```

`struct.pack(...)` parses as `CallExpr(func=MemberExpr(obj=IdentExpr('struct'),
member='pack'))`, so `c.func` is a `MemberExpr`, the root `IdentExpr` is not
collected, and the placement test refused it as a module-level name with no
storage. The refusal is CORRECT about the storage — the module object truly has
nowhere to live — and wrong about the remedy, because the call never reads the
module; it names a symbol the dylib exports.

**Fixing only that is not enough, and this is the part worth keeping.** With
the placement refusal gone, the same program failed differently:

```
build: the image would bind 1 symbol(s) that nothing provides: struct.pack.
Nothing on this link line defines them … (Provider check: asked the C library
(dlsym).)
```

`struct.pack` genuinely is not on the link line — under that spelling. The
dylib exports it as `struct_pack_02a19a`, and the manifest's `map` is keyed by
the BARE name (`pack`), because that is how `from struct import pack` writes
it. `_callee_symbol` flattens `obj.method` to the dotted name `struct.pack` and
`_dylib_syms.get(name, name)` looks THAT up, so the rewrite found nothing, the
BL kept pointing at `struct.pack`, and the image died in the loader on a symbol
the library had defined all along.

So the fix has two halves, in two files, and the second is only visible after
the first:

1. **`formal/build.py`, `check_module_symbols`** — collect the ROOT of a
   module-qualified callee by node identity, so the root is a callee and not a
   read. ROOT identity, and only for a call: the same name in a genuine read
   position (`len(struct)`) is still refused, which is the point — a module
   object has no storage either way, and what has no storage is the READ, not
   the call through it.
2. **`formal/build.py`, `load_dylib_manifests`** — register the
   module-qualified spelling of each export alongside the bare one, so the
   rewrite the codegen already performs has something to find:

   ```python
   amap.setdefault(e["name"], e["symbol"])
   mod = e.get("module")
   if mod and mod != e["name"]:
       amap.setdefault(f"{mod}.{e['name']}", e["symbol"])
   ```

   `setdefault`, so a library that exports a function genuinely named
   `struct.pack` keeps the bare name to itself.

   The one place to put it: the two `dylib_syms` loops in `formal/build.py`
   (the executable path and the dylib path) each rebuild the same map from
   `d["map"]`, so the row belongs in the map they both read rather than in
   either of them.

## What it cost, and what it bought

Before, all seven files the sweep reported as blocked on `struct` still were:

```
$ python3 tools/formal_sweep.py formal/arm64.py formal/macho.py
NOT-ANSWERABLE/HOST-IMPORT: formal/arm64.py  (build: encode_adrp: 'struct' is
  imported from `struct`, so it is a module-level name of another module. …)
not-answerable/host-import by module: struct (CPython stdlib) x2
```

— a FALSE line, since `struct` had Mojo source, built into a dylib, and
exported working entry points.

After, `struct` is gone from the report entirely and the seven files fail on
what is actually wrong with them:

```
CODEGEN: formal/arm64.py  (build: encode_sxtb_wd_wn: '_SXT_BASES' is bound at
  module level, and this path has no module-global storage for it: …)
CODEGEN: formal/macho.py  (build: buf.extend() is a method call on a value, and
  this backend lowers only append, close, write …)
CODEGEN: formal/macho_linker.py  (build: build_macho_executable:
  'NOEXTERN_ENTRYOFF' is bound at module level …)
NOT-ANSWERABLE/HOST-IMPORT: formal/elf.py  (build: elf.py imports 'typing' …)
NOT-ANSWERABLE/HOST-IMPORT: formal/x86_64.py  (build: x86_64.py imports 'enum' …)
NOT-ANSWERABLE/HOST-IMPORT: formal/x86_64_decode.py  (… 'dataclasses' …)
NOT-ANSWERABLE/HOST-IMPORT: test_x86_64_decode.py  (… 'sys' …)
```

Three files now report a REAL construct finding in themselves — a
module-global table, and a `list.extend` this backend does not lower — and the
other four are blocked on `typing`/`enum`/`dataclasses`/`sys`, which are other
workers' claims (`mod-os`, `mod-sys`). Neither is a fact about `struct`
anymore. `test_struct_formal.py` covers the working spelling end to end:
`import struct` + `struct.pack("<I", …)` builds, links, and returns CPython's
bytes.

## Still owed, and by whom

This is a change to `formal/build.py`, so it owes a full `make gate` — the
integrator's job, not the worker's. Two things that gate should be asked to
confirm, and one that a test now covers:

- `_audit_bound_symbols` receives the enlarged `dylib_syms` map, so the
  "every extern is accounted for" check now sees both spellings. That is
  right — both name the same symbol — but it is the kind of change where a
  count in a coverage report is a claim, so the sweep's own totals are worth
  reading rather than assuming.
- A name that is BOTH a module and a local (`struct = 5` shadowing an
  `import struct`) must keep refusing the read. The root-identity exclusion
  only exempts a name in callee position, so a real read elsewhere in the same
  function is still refused — which is an argument, and
  `test_formal_imports.py`'s `test_host_module_still_refused_despite_same_named_sibling`
  is the natural home for the assertion that it is a fact.
