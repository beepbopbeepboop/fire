# Every module carries ~3.5 KB of generic-repr helpers it cannot reach

## What I ran

While merging the `bugs3` batch I hit `test_module_cache.py`'s two "client
object is tiny" checks red — 8264 against an 8192 budget, and 10432 against
10240 — and measured where the bytes go.

The client is `test_module_cache.py`'s own `stage2` fixture
(`test_stage2_3_dylib_and_cas`), compiled with `gimple_codegen.compile_to_gimple_linked`
and then `gcc -fgimple -Iruntime -c`, i.e. exactly what the test does.

* base `d0796643`: 8144 bytes (stage2), 10120 (reflect)
* merged tree: 8264 / 10432

Diffing the generated C against base attributes the +120 to one place, in the
always-emitted `_mojo_repr_list`:

```c
+ char *_re = mojo_list_repr_elem(lst, _e);
+ if (_re) { _buf = mojo_str_cat(_buf, _re); free(_re); continue; }
```

which is the fix for a struct stored in a container printing through the
struct's own `__repr__` (`aab36167`). The reflect client's extra +192 is the
per-struct `_mojo_elem_repr_<Sn>` shim and its forward decls.

So the growth is necessary and in the acknowledged category. That is not the
finding though.

## What I saw

The five always-emitted helpers are:

```python
parts.append("static char * _mojo_dispatch_repr (void *);")
parts.append("static char * _mojo_repr_list (MojoList *);")
parts.append("static char * _mojo_repr_dict (MojoDict *);")
parts.append("static char * _mojo_generic_elem_repr (int64_t);")
parts.append("static char * _mojo_repr_pair (MojoList *);")
```

`mojo/backend_gimple/module_gen.py:943-947`, plus their definitions a few
hundred lines further down. `nm`/`otool` on the client's object puts them at
0x22c, 0x26c, 0x2fc, 0x4f4 and 0x60c — `_mojo_repr_list` alone is 0x1f8 = 504
bytes and `_mojo_repr_pair` 0x118 = 280.

Three facts make them removable per module:

1. They are all `static`. Nothing outside the translation unit can name them.
2. Nothing registers one **by address** — there is no `mojo_register_repr` /
   repr-function-pointer table. The only references are mutual, inside the
   cluster, plus the struct `__repr__` helpers calling
   `_mojo_generic_elem_repr`.
3. Hand-deleting all five definitions and forward decls from the stage2
   client's C **compiled and linked with no undefined reference**, and the
   object went 8760 -> 5208 bytes: 3552 bytes of per-module dead weight, on a
   client whose own code is a few hundred.

## What I expected

A module that cannot produce a container value and holds no reflected struct
should not carry a container repr, and the test's own budget comment has been
bumped twice for precisely this family
(`_mojo_repr_set`, then `_mojo_generic_elem_repr` + `_mojo_repr_pair`).
Three bumps is the point at which the guard has stopped guarding.

## Exact next step

Gate the cluster. The gate has to be **reachability from this module's own
generated code**, not a source-text heuristic, and the cheap correct version is
a post-pass over the parts already emitted:

1. Emit the cluster as today, into a single `parts` slice, so it can be
   withdrawn as a unit rather than five separate `parts.append` calls.
2. After the module's bodies are generated, count references to each of the
   five names in `''.join(parts)` outside the cluster's own text. Drop the
   whole cluster when the count is zero for all five.
3. The two forward decls at module_gen.py:11130-11131 are a SECOND emission of
   the same five (a different code path — the link-mode/imports preamble).
   They must be gated by the same decision or the module will not compile, and
   that is the loud failure mode to expect while landing this.

The predicate to be careful about is `_mojo_generic_elem_repr`: it is called
from a struct field's `__repr__` when the field's static type is not a
primitive, so a module whose only container is a struct FIELD still reaches
the cluster. Counting references after emission gets that right for free; a
"does the source mention a list" scan does not.

## Why this was not landed with the merge

The failure mode of getting the gate wrong is a link error
(`undefined reference to _mojo_repr_list`) somewhere in the self-hosted
closure, and the only step that can clear that is `make bootstrap` — a whole
closure compile the merge worker is not permitted to run. Landing an
unverifiable change to the code generator inside a merge, whose whole job is to
combine other people's verified branches, is the wrong trade. The two budget
lines were raised by the file's own documented 1024 increment with the
measurement and this doc recorded next to them, so the number is not a guess
and the next bump does not have to re-derive any of this.
