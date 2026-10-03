# The self-host closure still fails gcc in four unrelated families, once the two toplevel ones are gone

**State: OPEN, measured 2026-10-02 on `work/bugs4-3-c` at 163b9c8b. 13 distinct
gcc errors, none of them in the emission area the two DELETED
`<mod>_toplevel has no member` / `_mojo_elem_repr_<Struct> undeclared` families
used to name** — those are gone, with their fix (67 errors removed, 80 -> 13,
zero added), and this one carries what is left so the queue does not read as
empty while `selfhost` is still red. `git log --oneline` for
`work/bugs4-3-c`'s last two commits has both, with the measurements.

## How to measure (no heavy run, ~4 min)

The self-host closure's C, which is the artifact `test_selfhost.py` builds:

```sh
python3 - <<'EOF'
import gimple_codegen
src = open('fire.py').read()
open('.tmp/fire_full.ci', 'w').write(
    gimple_codegen.compile_to_gimple_cached(src, do_imports=True,
                                            filename='fire.py'))
EOF
$(python3 -c 'from build_config import find_gcc; print(find_gcc())') \
    -fgimple -fsyntax-only -O0 -g3 -ftrivial-auto-var-init=zero \
    -I runtime $(python3-config --cflags) -x c .tmp/fire_full.ci
```

Peak 1.3 GB. `-x c` is load-bearing (`gcc` here is clang by default and
silently treats `.ci` as a linker input), and `$(python3-config --cflags)` is
what makes the emitted C see `Python.h`. `compile_to_gimple_cached` is
content-addressed, so editing the compiler invalidates it and an unchanged tree
replays from cache.

**Do not count errors with `grep ' error: '` alone.** Four of the matches come
from the compiler's OWN source text quoted inside the generated C — comments
and docstrings that quote gcc diagnostics verbatim (`gimple_codegen.py:4331`'s
"internal compiler error: in build2"). Filter to lines that start with an
absolute path and a real suffix (`^/…\.(py|ci|h|c): error: `) or the count is
inflated by 4 on this tree.

## What is left, and where each one starts

| count | family | first site |
|---|---|---|
| 2 | `conflicting types for '_compute_exc_descendants'; have 'MojoDict *(MojoList *)'` — one definition, two declarations with different return types | `mojo/middle/types.py` (definition) vs `regex_compile.py` (the other declaration) |
| 3 | `passing argument 1 of '_mojo_repr_list' / 'mojo_repr_list_ints' makes pointer from integer without a cast` — a `char *` value reaching a `MojoList *` parameter | `mojo/backend_gimple/device_glue.py`, `emit_methods.py`, `mojo/middle/methods_shared.py` |
| 3 | `myinterpreter.py`: `assignment to 'int64_t' from 'struct MojoFunction *'`, plus `non-trivial conversion in 'component_ref'` and in `'var_decl'` | `myinterpreter.py` |
| 3 | `module_gen.py`: `assignment to 'int64_t' from 'MojoDict *'`, `assignment to 'MojoSet *' from incompatible pointer type 'char *'`, and `'gen_module_impl__is_foreign_main__mk_round_env' has no member named 'self'` | `mojo/backend_gimple/module_gen.py` |
| 2 | `fire_compiler.py`: `assignment to 'MojoList *' from incompatible pointer type 'struct Parser *'` and `implicit declaration of function 'mojo_mark_dict_bool_values'` (`module_loader.py`) | `fire_compiler.py`, `module_loader.py` |

## Why they are here and not spread over five docs

Every one of them is a type/ABI disagreement, and none is reachable from a
small fixture: each needs the whole-closure shape to appear. Splitting them
across five docs would give five docs that each cost the next reader a
4-minute measurement to re-establish the same baseline, which is the thing
this one file exists to hold.

## Ordering note for whoever picks these up

`_compute_exc_descendants` is the one to start with: two declarations of one
function with different return types in one translation unit is a signature
TABLE disagreement (`gimple_codegen._KNOWN_SIGS` / `_SELFHOST_SIGS` against the
definition), and the codebase already has a test that catches the analogous
drift (`test_gimple.py`'s `handwritten_selfhost_signature_tables_match_the_source`).
The `_mojo_repr_list` family and the `module_gen.py` coercions are each one
emission site's type inference; the `myinterpreter.py` trio is one per
statement shape.

## Suite-bucket note

`selfhost` (`python3 test_selfhost.py`, ~3.5 min, 2.2 GB), which is in `check`
and in `gate`. Both halves of its static check already pass — 61 modules' every
generator/async lowerable in place, and the one `fire_runtime.h` pinned C
signature matching its definition — so the failure is purely this compile
stage.