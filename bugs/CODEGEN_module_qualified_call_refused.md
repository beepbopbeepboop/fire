# A module-qualified call `mod.fn()` is refused, and the message tells you to write one

**Area:** CODEGEN (formal arm64 + x86-64; `formal/build.py`'s
`check_module_symbols`). **Found while:** writing `struct.mojo` for the formal
backend (worker `mod-struct`), which is the change that made
`import struct` resolve — and so made this the next thing standing in the way
of the seven files that use it.

**Severity: a refusal, not a wrong answer** — which is the good case. It stops
the build at a message a reader can act on. The problem is that the message
names the wrong repair, and acting on it does not work.

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

The advice in that message is exactly the program above. It does not lower.

The other spelling of the same call, which the message does not mention, works:

```
$ cat AE.py
from struct import pack

def main():
    b = pack("<I", 7, 0, 0, 0, 0, 0, 0)
    return 0

$ python3 fire.py build --formal --no-prove AE.py
Built: AE.bin  [arm64/macho]
```

So the module boundary works and `struct.pack` is exported and callable; what
is refused is the SPELLING, and the diagnostic tells the reader to use the
spelling that is refused.

## Why

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
member='pack'))`, so `c.func` is a `MemberExpr` and the root `IdentExpr` is not
in the set. It then fails the placement test, `M.module_symbol('struct')`
returns the `imported` symbol, and `model.module_global_refusal` produces the
message. The refusal itself is CORRECT about the storage — the module object
truly has nowhere to live — and wrong about the remedy, because the call never
reads the module; it names a symbol the dylib exports.

The `dylib_syms` machinery downstream already handles the qualified name
(`formal/arm64_codegen.py`'s `_callee_symbol` flattens `obj.method` to a dotted
name, and `_dylib_syms.get(name, name)` rewrites it to the exporting library's
spelling), so the half that would make this work is present and the half that
refuses it is a missing case in one set comprehension.

## What it costs, measured

Every one of the seven files the sweep reported as blocked on `struct` writes
`struct.pack(...)` — module-qualified — and all seven are still refused:

```
$ python3 tools/formal_sweep.py formal/arm64.py formal/macho.py
NOT-ANSWERABLE/HOST-IMPORT: formal/arm64.py  (build: encode_adrp: 'struct' is
  imported from `struct`, so it is a module-level name of another module. …)
NOT-ANSWERABLE/HOST-IMPORT: formal/macho.py  (build: _build_segment_64: 'struct'
  is imported from `struct`, …)
```

and the sweep still reports `not-answerable/host-import by module: struct x2`,
which is now a FALSE statement: `struct` has Mojo source, is built into a
dylib, and exports working `pack`/`unpack_from`/`pack_into`/`calcsize`
(`test_struct_formal.py`, 142 checks, byte-for-byte against CPython). The
module is not missing; the call spelling is.

## Next step

Add the member-callee case to `callees`, keyed by the ROOT of the callee chain
rather than by the callee node — the same identity the `bracketed` map a few
lines below already computes:

```python
callees = {id(c.func) for c in M.iter_nodes(fn.body)
           if isinstance(c, F.CallExpr) and isinstance(c.func, F.IdentExpr)}
# …and a MODULE-qualified callee, `mod.fn()`, whose root is the module name.
# The call names an exported symbol; it does not read the module object, so
# its root is a callee and not a read.
for c in M.iter_nodes(fn.body):
    if isinstance(c, F.CallExpr) and isinstance(c.func, F.MemberExpr):
        root = c.func.obj
        while isinstance(root, (F.MemberExpr, F.SubscriptExpr)):
            root = root.obj
        if isinstance(root, F.IdentExpr):
            callees.add(id(root))
```

`model.module_global_refusal`'s "Give it a function (a `mod.fn()` call
lowers)" sentence then becomes true, which is worth doing in the same commit:
a diagnostic that recommends the refused form is worse than one that names no
repair at all, because following it wastes a build.

Two things to settle before landing, both outside my claim area
(`module:struct`), so I have not touched either:

1. It is a change to `formal/build.py` and therefore owes a full `make gate`.
2. A name that is BOTH a module and a local (`struct = 5` shadowing an
   `import struct`) must keep refusing the read. The root-identity exclusion
   above only exempts a name in callee position, so a real read elsewhere in
   the same function is still refused — but that is worth a test rather than
   an argument, and `test_formal_imports.py` is where it belongs.
