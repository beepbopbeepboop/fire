# FORMAL_module_attribute_access_refused: `import os` + `os.path.join(…)` does not lower, and the message says it does

**Status:** open, and it is the largest single blocker in the `os` work: 532 of
the measured `os` uses across the 87 sweep files are `os.path.join`, and every
one of them is written as an attribute of the module object. Found while
writing `os`; the refusal is `formal/model.py:module_global_refusal` reached
from `formal/build.py:_check_unresolved_names`, and the two backends'
`_emit_call` is where the fix lands. Not fixed here: it is a change to what a
call target may be in both codegens, it is in nobody's claimed area, and it
cannot be gated from this worktree.

## What I ran

```
$ cat > .tmp/mods/mymod.mojo
sep = "/"
def addup(a, b):
    return a + b

$ cat > .tmp/mods/prog2.mojo
import mymod

def main(n):
    printf("sum=%d\n", mymod.addup(2, 3))
    return 0

$ python3 fire.py build --formal --no-prove .tmp/mods/prog2.mojo
build: main: 'mymod' is imported from `mymod`, so it is a module-level name of
another module. This path compiles an import into a dylib, and a module-level
name is not exported as a word — there is no storage for it here: every value a
formal program can name lives in a function's own stack scratch, which is
reclaimed when the function returns. **Give it a function (a `mymod.fn()` call
lowers)** or write the value at the use site
```

## What I saw, and why the message is the problem

**The suggested repair does not work.** I believed the message and tried it:
`mymod.addup(2, 3)` is refused identically — same message, same name, same
`mymod`. So the diagnostic names a spelling this path does not accept, and a
reader who follows it lands on the same wall with less information than they
started with. That is worth fixing on its own account, quite apart from the
capability.

What DOES work is `from mymod import addup` and calling `addup(…)` — verified,
and it is the shape all 436 of `test_formal_os.py`'s path answers use.

The refusal itself is raised by `formal/build.py:_check_unresolved_names`
(`:3135`), which walks every `IdentExpr` in a function body and refuses one it
cannot place. A call's callee is exempt, collected as

```python
callees = {id(c.func) for c in M.iter_nodes(fn.body)
           if isinstance(c, F.CallExpr) and isinstance(c.func, F.IdentExpr)}
```

— `isinstance(c.func, F.IdentExpr)`. A **dotted** callee is a `MemberExpr`, so
the root `mymod` is treated as a READ of an imported name, and a read of an
imported name is what `module_global_refusal`'s `site == "imported"` case
describes. The intent of that case is right: a module-level VALUE is not
exported as a word. A module-attribute CALL is not a read of a value, and
should never have reached it.

## What is already half-built for the fix

`formal/arm64_codegen.py:_emit_call` comments the distinction itself:

> A method on a plain VALUE is not a call to a symbol spelled `recv.method`.
> `_callee_symbol` flattens both spellings to a dotted name, so the two are told
> apart by the receiver: a local is a value and the method is one of
> `model.BUILTIN_VALUE_METHODS`, **anything else is a module path and the dotted
> name really is an extern**.

So the codegen already *believes* a dotted name is an extern and emits
`BL mymod.addup`. What is missing is the mapping from that dotted name to the
symbol the library exports, and the name check that refuses the read one layer
earlier. Both are small and neither is new machinery:

1. **In the codegen**, resolve the dotted callee through the same
   `self._dylib_syms` map the bare form uses, keyed on the LAST component:
   `self._dylib_syms.get(name.rsplit(".", 1)[-1], name)`. With a module prefix
   check so `recv.method` where `recv` is not an imported module still cannot
   pick up an unrelated export — the existing `_is_value_receiver` test is
   already the discriminator, and the two together say exactly one thing.
2. **In the name check**, add a `MemberExpr`/`SubscriptExpr` callee to the
   `callees` exemption by ROOT IDENTITY, the way the MLIR-template pass at
   `:3107-3134` already does for the spellings that nest. Then
   `mymod.addup(2, 3)` reaches the codegen instead of the name check, and a
   call to `mymod.nonexistent` fails where it should: at the LINK, with the
   audit's message, which already names the symbol and asks the library.
3. **Fix the message regardless**, and before the rest: `module_global_refusal`
   should not suggest a repair that does not lower. Until (1) and (2) land, the
   honest text names the ONE spelling that works (`from m import f`) and says
   why the other is refused.

Steps 1 and 2 are in `formal/arm64_codegen.py` and `formal/x86_64_codegen.py`
plus `formal/build.py` and `formal/model.py` — four shared files, two
architectures, and a change to what may be a call target. That is a
FORMAL.md-shaped piece of work with its own measurement, not something to land
beside a module in the same commit.

## What `os` does in the meantime, and what it costs

`os` and `os.path` are complete and tested; they are reached with
`from os.path import join`. Sweeping all 87 files this list names, with `os`
out of `HOST_MODELLED`: **0 still stop at `os`.** 85 stop at the next host
module in the same file — `subprocess` 22, `re` 18 (one of them through
`fire_compiler.py`), `sys` 15, `platform` 5, `struct`, `socket`, `shutil`,
`functools` and one repository sibling — and the remaining 2 are the two whose
ONLY host import was `os`: `determinism_trace.py`, which reaches the refusal
this document is about, and `formal/model.py`, which reaches `fire_compiler.py`
and its `re` before it stops.

So the class does not move for 85 of the 87: they import other host modules
too, and `sys` and `re` are what decides it now. Those are other modules with
their own owners, and `struct` and `sys` are being written in parallel with
this. **What this item is worth is not the sweep class — it is that 532
measured `os.path.join` call sites and the rest of the `os.path` surface are
unreachable at all until it lands**, and that one of the 87 files is already
stopped here rather than stopped short.
