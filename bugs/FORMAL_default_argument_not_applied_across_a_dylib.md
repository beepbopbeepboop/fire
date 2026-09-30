# FORMAL_default_argument_not_applied_across_a_dylib: a default that arrives as a stack address

**Status:** open. Not fixed here — it is in `formal/`, which the `mod-os` work
does not own, and the fix is a change to what the CALLER knows rather than a
patch. Found while writing the `os` module, which is why it is written up in
full: the module's whole public API had to be written without a single default
argument because of this, and that is a large and permanent-looking cost to
leave undocumented.

## What I ran

```
$ mkdir -p .tmp/da
$ cat > .tmp/da/dmod.mojo
def need_two(a, b=511):
    return b

def need_one(a):
    return a

$ cat > .tmp/da/dmain.mojo
from dmod import need_two, need_one

def local_two(a, b=511):
    return b

def main(n):
    printf("cross-default=%d@", need_two(1))
    printf("cross-explicit=%d@", need_two(1, 77))
    printf("cross-one=%d@@", need_one(5))
    printf("local-default=%d@", local_two(1))
    return 0

$ python3 fire.py build --formal --no-prove -o .tmp/da/dmain .tmp/da/dmain.mojo
Built: …/.tmp/da/dmain  [arm64/macho]
$ ./.tmp/da/dmain
cross-default=1867609072@cross-explicit=77@cross-one=5@local-default=511@
```

## What I saw

`need_two(1)` returns **1867609072**, which is a stack address, where the
callee's own default says 511. The identical call in the SAME file
(`local_two(1)`) returns 511, and passing the argument explicitly across the
same boundary returns 77. So it is neither the default's value nor the
argument passing: it is specifically **the default that is not applied**, and
only when the callee is in another image.

`formal/arm64_codegen.py:_emit_call` passes `list(e.args)` positionally into
X0..X7 and knows nothing about the callee's parameter list, because the callee
is not in `self._functions` — it is an export of a linked dylib. A missing
argument register therefore holds whatever the caller last put there. In one
image the callee's `FunctionDef` IS in the registry, so the defaults are
available and are filled in.

## What I expected

`need_two(1) == 511`. A default argument is part of the function's contract,
and a contract that holds in one image and not another is a contract the
boundary does not honour.

## Why this is worse than a missing feature

A missing default would be a refusal at the call site with a name in it. This
is a **silently wrong argument**, and it is worst exactly where the argument is
a number that is not checked: measured on the `os` module's own first cut,

```
os.makedirs(path)            # mode defaulted to 0777
```

created directories with **mode 0** — the process umask cannot widen a zero,
so the directory existed, `isdir` said 1, `makedirs` said 0, and the parent
process then could not read it. Every assertion in the test said the operation
had succeeded.

## The exact next step

Materialize the callee's defaults at the call site, from the callee's own
source. Everything needed is already reachable and none of it is new:

* `formal/imports.py` has `resolve_module_path` and `declared_kinds(path)`,
  which read the imported module's own source through the same
  `F.Parser(F.py_tokenize(text))` the module's dylib was built from — so a
  parameter list read there cannot disagree with the library on disk.
* `write_dylib_manifest` already records `arity` per export
  (`formal/build.py:3579`), so the executable build has a cheap cross-check
  that the count it is about to fill in matches what the library was built
  from. **Use it**: a call whose argument count is below the declared arity and
  which the callee has defaults for gets them; one that is below the arity with
  NO defaults for those parameters is a refusal naming the callee. That second
  half matters as much as the first — today `need_one()` called with two
  arguments is also accepted and the extra word is dropped.

The decision belongs in `formal/model.py` next to `function_param_shape` (which
is where a parameter list is already read) and is consumed by both backends'
`_emit_call`, for the same reason `string_comparison_lowering` lives there: one
answer, two architectures.

**While it is open, the rule for writing a module here is: no default argument
on anything another image can call.** `formal/hostmods/os/__init__.mojo`
states that at the top, and `getenv_or(name, default)` exists as a second function precisely so
that the two-argument form has a name instead of a signature that does nothing.
