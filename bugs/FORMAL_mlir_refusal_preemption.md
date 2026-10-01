# FORMAL_mlir_refusal_preemption: the refusal that NAMES the construct loses to the one that names a symptom

Found while closing the `_get_kgen_string` import-resolution gap on
`std/sys/_assembly.mojo`. It is a diagnostic-accuracy defect and not a
coverage one: every file affected is refused either way, and no image is wrong.

## The failing program

```mojo
def main() -> Int32:
    var q = Unplaced                       # a genuine unplaced name
    var v = __mlir_op.`pop.inline_asm`[    # the construct that is actually fatal
        _type=None, assembly="nop", constraints="",
    ]()
    print(v)
    return 0
```

```
$ python3 fire.py build --formal --no-prove .tmp/ord/b.mojo -o .tmp/ord/b
build: main: 'Unplaced' has no home: the module-level symbol table is empty for
this unit, and the reading function declares no local or parameter by that
spelling. …
```

Reverse the two lines and the build says the useful thing:

```
$ python3 fire.py build --formal --no-prove .tmp/asm/main.mojo -o .tmp/asm/main
build: main: __mlir_op is an MLIR dialect construct. This path has no MLIR: it
lowers a Mojo program to a Mach-O image whose only value is a 64-bit word, and
an MLIR attribute, type or operation has no representation in one …
```

Same construct, same backend, same file's worth of source — the verdict is
decided by **line order**. `__mlir_op` has a precise, arch-free, already-written
refusal (`model.mlir_dialect_refusal`, asked from both backends through
`model.mlir_template_refusal`'s sibling call in `_emit_expr`); it loses to a
message that names a register table.

## Why this is the pre-emption and not a bug in either message

`check_module_symbols` walks the body in source order and raises on the first
name it cannot place. It already has a pre-pass for exactly this reason — the
`bracketed` map, built before the per-name walk, holding the refusals that
*name a construct*. The file's own comment says what the pre-pass is for:

> The two refusals that NAME the construct are asked first, through the ONE
> reader both backends use, so the better-worded message wins here rather than
> being pre-empted by the symptom.

That is implemented, and it holds — but only for `SubscriptExpr`/`MemberExpr`
spellings (`__mlir_attr[…]`, `__mlir_op.`lit.…``). The **dialect** refusal
(`__mlir_op`, a bare name with the `__mlir_` prefix) is reached by a separate
`name.startswith(M.MLIR_DIALECT_PREFIX)` branch *inside* the per-name walk, so
it is subject to source order like any other name. The pre-pass is half
implemented, and the half that is missing is the one that matters for
`std/sys/_assembly.mojo`.

`std/sys/_assembly.mojo` is the live case: `NoneType` at line 94 pre-empts
`__mlir_op.`pop.inline_asm`` at line 95, so the seventeen files behind that
module are told a type name has no register rather than that the file's whole
purpose — inline assembly — cannot be lowered at all.

## Measured

Every `*.mojo` under `../modular/mojo/stdlib` parsed, and for each file that
contains an `__mlir_*` dialect name in some function body, the verdict of
`check_module_symbols` recorded and tested for whether it names the MLIR
construct:

| | files |
|---|---|
| an `__mlir_*` dialect name appears in a function body | **36** |
| …and the reported refusal IS the MLIR construct | **18** |
| …and something ELSE is reported instead | **18** |

So the ordering decides the message for **half** of the population it applies
to. The 18 that lose, relative to `../modular/mojo/stdlib/std`:

```
atomic/atomic.mojo              memory/memory.mojo
builtin/bool.mojo               memory/stack_allocation.mojo
builtin/globals.mojo            memory/unsafe.mojo
ffi/__init__.mojo               memory/unsafe_maybe_uninit.mojo
gpu/compute/mma.mojo            os/os.mojo
gpu/host/compile.mojo           python/_cpython.mojo
gpu/intrinsics.mojo             sys/_assembly.mojo
gpu/memory/memory.mojo          utils/numerics.mojo
gpu/primitives/cluster.mojo
gpu/primitives/grid_controls.mojo
```

## The next step

**Small, and it is the whole fix:** add the dialect branch to the existing
pre-pass, so it is recorded in `bracketed` by the root `IdentExpr`'s identity
alongside the two that are already there, and asked before the per-name walk.

```python
# in the `bracketed` pre-pass, alongside the two existing `why = …` asks
if why is None and root_ident.name.startswith(M.MLIR_DIALECT_PREFIX):
    why = M.mlir_dialect_refusal(root_ident.name)
```

**Then measure the 18, because the change is not obviously one-directional.**
`__mlir_dialect_refusal` is arch-free and true, so naming the construct is
better; but pre-emption cuts both ways. A file with an `__mlir_op` *and* a
genuinely unplaced name would move from the unplaced name to the MLIR
construct, and "which problem should the reader hear about first" is a
judgement, not a mechanical rule. The two cases to look at first are the ones
where the unplaced name is a *parameter of the MLIR template* (there the MLIR
refusal is unambiguously right) and the ones where it is unrelated (there it
is not obviously so).

**Two things this change must not do.** It must not reach past
`check_module_symbols` into a reordering of the walk itself — the walk order
is what the *other* construct refusals rely on. And it must not be done by
shortening `unresolved_name_refusal`'s enumeration: that text is correct for a
name that really is a value read, and several hundred files depend on it
saying so. The separate, larger problem that a bare type name in a value
position gets that same text is `FORMAL_type_name_as_a_value.md`; the two
should be closed in that order, because the type-name rule is the one that
belongs in the same pre-pass.
