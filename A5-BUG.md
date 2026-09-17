# A5 Frontier: compiled codegen can't iterate boxed dict/list fields

This file documents the remaining open native-backend bugs blocking the
self-hosted binary (`mojoc` / `stage2/mojo`) from functioning, along with the
patch currently in the tree that addresses the core one and the known residual
it exposes. It is written as a handoff: everything below was root-caused by
direct inspection of generated `.ci` output and GCC errors; the fixes listed
as DONE are committed.

---

## 1. The A5 frontier bug (primary)

### Symptom

`make clean; make bootstrap` builds and links `stage2/mojo` but the stage2
validation loop fails on **every** file with:

```
mojo_unsupported_iter: 'for' loop over unsupported iterable type
  .../ast_rewriter.py:270: int64_t
```

so the compiled binary cannot `--dump` any file. The root cause is in the
compiled `ast_rewriter` pattern matcher, which is invoked while compiling
every input file.

### The failing code (`ast_rewriter.py`)

```python
# ast_rewriter.py:85
class Node:                                   # NOT a dataclass
    def __init__(self, node_type, **fields):
        self.type = node_type
        self.fields = fields                 # dynamic dict, set at runtime

# ast_rewriter.py:264
def _collect_discriminators(pat, path, out):
    if isinstance(pat, Node):
        out.append((path, 'TYPE', pat.type))
        for fname in pat.fields:              # <-- ast_rewriter.py:270
            _collect_discriminators(pat.fields[fname], path + [fname], out)
```

`pat` is an untyped function parameter (boxed `int64_t`), and `pat.fields` is
a dict attribute set dynamically in `__init__`.

### How it lowers in the compiled codegen

1. `pat.fields` compiles to `_mojo_dispatch_getattr(pat, "fields")` (the A5
   boxed-member path in `_lower_MemberExpr`). At runtime this returns the real
   `MojoDict *` pointer, but **boxed as `int64_t`**.
2. `_lower_MemberExpr`'s A5 field-typing cannot recover a static type:
   `_known_field_type('fields')` is **ambiguous** —
   `Node.fields` is registered as `int64_t` (boxed, because `**kwargs` params
   default to int64_t) while `StructDef.fields` is `MojoList *`. The A5 path
   only types a field when every struct carrying it agrees, so it falls back
   to the generic boxed `int64_t`.
3. `_gen_for_iter` (`for fname in <boxed int64>:`) resolves the type via
   `_get_actual_type` → still `int64_t` → hits the "unsupported iterable"
   fallback → `mojo_unsupported_iter` → the loop body runs **zero times**.
4. Consequently `_collect_discriminators` returns nothing and the rewrite
   engine produces empty patterns for every input file; worse, the
   `mojo_unsupported_iter` diagnostic on stderr makes every `--dump`
   validation run fail.

`Node.fields` IS correctly registered in the reflection dispatch
(`_mojo_getattr_Node` returns `obj->fields`), so the runtime value is a real
dict — only the **static type knowledge** is lost.

### The patch in the tree (runtime-dispatch iteration)

`gimple_codegen.py`, `_gen_for_iter`'s unsupported-iterable `else` branch now
emits a runtime dispatch instead of dropping the loop:

```c
if (mojo_is_registered_dict(_t)) { <dict-key iteration> }
else if (mojo_is_registered_list(_t)) { <list iteration> }
else mojo_unsupported_iter(...)
```

- `mojo_is_registered_list` / `mojo_is_registered_dict` were added to
  `_KNOWN_SIGS` (runtime registries already existed in `mojo_runtime.c`).
- The dict branch uses `_gen_for_dict`, the list branch `_gen_for_list`, each
  on a cast of the boxed pointer.
- This makes the compiled `ast_rewriter` iterate `pat.fields` correctly, so
  the stage2 binary can `--dump` files again.

Verified: with the patch, `mojoc` compiles `minimal_main.mojo` to a `.ci`
that `gcc -fgimple` accepts and that runs (prints `42`); the A/B harness runs
all 28 builtin cases (previously 0 — mojoc couldn't even start). `make check`
stays green and `test_selfhost` passes.

### Known residual: stdlib regression (4 modules)

The dispatch compiles loop bodies that were previously silently dropped,
exposing latent codegen gaps. The ones hit by `make check`/self-host were
fixed and committed in `4e463f3`:

- `os.path.isabs(p)` compact `&&` / pointer-deref-in-comparison → branch +
  char temp + int compare.
- dict-key boxing `(int64_t)(uintptr_t)key` (GIMPLE rejects a double cast in
  one statement) → split `void *` then `int64_t` temps.
- pointer negation `-<char*>` (a dead dict-iteration branch) → coerce all
  pointers (incl. `char *`) to `int64_t` for unary `-`/`~`.
- `_gen_for_dict` declared every tuple var `char *` (first-decl-wins poisoned
  a function-pointer slot) → value slots declared `int64_t`.
- a local variable called as a function (`func(...)`) wasn't routed to
  `_lower_fnptr_call` when its declared type was a misleading `char *` →
  treat any var-types local callee as a fnptr call.
- `_compr_list_loop` tuple unpack boxed `get_str` unconditionally → respect
  the var's declared type.
- heterogeneous tuple per-slot element types (`_tuple_slot_types`) so a
  `(char *, pointer)` pair's pointer slot is read via `get_int`, propagated
  through list literals and comprehensions.

**The one remaining gap** that regresses 4 stdlib modules when the dispatch
is enabled:

```
../modular/mojo/stdlib/std/collections/counter.mojo:631:
    for item in self.items():
        if item.value < 0:
            result[item.key] = -item.value
```

`for item in <d.items()>: ... item.key ... item.value` — a SINGLE loop var
holding a dict-item PAIR, with `.key`/`.value` member access. The codegen has
**no pair-accessor support** (`_lower_MemberExpr` has no `.key`/`.value` case
for a tuple/pair receiver), so:

- `item.value` resolves to an identity/0, and `-item.value` negates the pair
  handle or key pointer.
- In the dead dict branch `item` is a char* key, so `-item.value` /
  `X - item.value` produce GIMPLE "wrong type argument to unary minus" /
  an ICE in `build2`.

The affected modules: `counter.mojo`, `interval.mojo`,
`collections/string/_unicode.mojo`, `collections/string/string_slice.mojo`.
Reverting the dispatch restores the 0-skip stdlib baseline (verified).

**What the resolver needs to do**: implement `.key`/`.value` on a tracked
dict-item-pair loop variable (read pair element 0 as the key — `get_str`, and
element 1 as the value — `get_int`/`get_str` per the dict's value type). A
side-table `_dict_items_pairs` was prototyped and removed; the cleanest design
is to record, when a single loop var iterates a dict-items source, that the
var holds a pair, then special-case `_lower_MemberExpr` for `.key`/`.value` on
it. Both the dict and list dispatch branches must compile (the dict branch's
`item` is a key — reading it as a pair is dead-branch-only, which is fine, but
the emitted C must still be valid).

---

## 2. `_slit_` string-pool corruption (todo item)

### Symptom

The native codegen's string pool for a user file with multi-character string
literals emits corrupt entries:

```c
static char * _slit_10000 = "o";     /* "foo" truncated */
static char * _slit_10001 = "r";     /* "bar" truncated */
static char * _slit_10002 = "\n";
```

or, worse, empty/address entries (`static char * _slit_N = "";`), and the
A/B harness fails with `UnicodeDecodeError` reading the native `.ci` (raw
address bytes embedded). The function bodies reference the right `_slit_N`
names; only the pool **values** are wrong.

### Root cause chain

1. `_decode_str_literal_text` returns `(text, is_fstring)` — a heterogeneous
   `(str, bool)` tuple.
2. **Pass 2c** (`_infer_return_elem_type`) inferred this tuple's element type
   as `int64_t` (with `var_types` empty it can't type the local `val` as
   `char *`), so call sites unpacked **both** slots via `mojo_list_get_int`
   and read the text pointer as an integer, storing its address in the pool.
3. Partially fixed in `c3cf1fa` by returning `is_fstring` as `""`/`"1"`
   (homogeneous `[char*, char*]` tuple) so Pass 2c infers `char *`.
4. **Still broken**: with a fix in place, a trace at the call site showed
   `_return_elem_types['GimpleGen__decode_str_literal_text']` reading as `''`
   (empty) even after Pass 2c ran — the value for that key is empty or a
   dangling pointer, and `val` still reads as a raw address. This points to
   corruption in the compiled binary's own dict handling of
   `_return_elem_types` (the same `_char_to_cstr` boxed-key class of bug that
   was fixed in `11e3a3b` for `var_types`, but not for this table), OR to
   `_intern_string` receiving a truncated escaped string from the compiled
   `_decode_str_literal_text`.

### What the resolver needs to do

Reproduce with `echo 'def main(): print("abc")' > /tmp/x.mojo &&
./mojoc /tmp/x.mojo --dump` and inspect `static char * _slit_*` in the output
`x.ci`. Fix the compiled-path dict membership/value read so
`_return_elem_types[...]` and `_str_pool` lookups return the real stored
strings. Check `_intern_string`'s `self._str_pool[escaped] = ...` and the pool
emission loop (`for escaped, sname in sorted(self._str_pool.items(), ...)` in
`gen_module`) against the `_char_to_cstr` fix pattern in `11e3a3b` (a boxed
`char *` treated as a raw char byte because `_actual_types` had no record).
The A/B harness cases affected: `string_ops`, `fstring`, `string_concat`,
`string_methods`, and any file whose strings reach the pool with multiple
literals.

---

## 3. Emission-ordering diffs (A/B byte-identity, not corruption)

### Symptom

The A/B harness (`test_ab_shim.py`) now RUNS all 28 builtin cases and the
native `.ci` files are valid C (many compile cleanly with `gcc -fgimple`),
but all 28 FAIL on byte-identity diffs that are **ordering/cosmetic**, not
corruption. Two specific divergences:

1. **`_mojo_type_name` forward declaration.**
   - Python path: NOT emitted for a user file.
   - Native path: `static char * _mojo_type_name (int64_t);` emitted.
   - Root cause: the codegen's OWN compiled `gen_stmt` runs
     `node_kind = type(node).__name__` (gimple_codegen.py:14991) for every
     statement. In the compiled binary this lowers through
     `_lower_MemberExpr`'s `type(x).__name__` branch, which sets
     `self._needs_type_name_table = True` as a side effect — so every user
     file compile emits the (valid but unused) type-name table + fwd-decl. In
     the Python path the same line is real Python and never touches the flag.
   - The emitted table is harmless dead code (the native `.ci` still compiles
     and runs), but it breaks byte-identity.
   - Fix direction: gate `_needs_type_name_table`'s side-effect on the
     self-host path (`_is_selfhost_file`) OR only when the USER code (not the
     codegen's own internal `type(node).__name__`) triggers it. Note a user
     file that legitimately uses `type(x).__name__` DOES need the table — the
     gate must not break that.

2. **Struct-method auto-stub ordering** (`test_simple` case).
   - Native `.ci` is ~166 lines SHORTER than Python (2725 vs 2559) and emits
     `#ifndef _MOJO_STUB_ADD ... int64_t add (...);` in a different position
     than Python.
   - Root cause not fully chased; it looks like the `_elaborated_externs`
     (auto-stub) emission lands before the reflection fwd-decls in native but
     after in Python, and some section is omitted/merged differently. The
     section order in `gen_module`'s final assembly differs between the two
     paths for some state-dependent condition (`_is_selfhost_file`,
     `_needs_type_name_table`, or the number of emitted modules).

### What the resolver needs to do

For #1, reproduce with `minimal_main` (`print(42)`) and diff the Python vs
native `.ci` around line ~924. For #2, use `test_simple.mojo`. These are the
LAST remaining A/B divergences once the corruption bugs (sections 1–2) are
fixed; the goal is byte-identical `.ci` per the AB-PLAN.

---

## Reproducing and verifying

```sh
# self-host guard (must stay green):
python3 test_selfhost.py

# A/B harness (28 builtin cases; native .ci must be valid C and ideally
# byte-identical to Python):
python3 test_ab_shim.py

# stdlib dylib (baseline is 0 skips; the dispatch patch regresses counter/
# interval/_unicode/string_slice until section 1's residual is fixed):
rm -f build/libmojostdlib.dylib
python3 -c "import build_stdlib_dylib as bsd; bsd.build_stdlib(jobs=8)"

# bootstrap (stage1 + stage2 build must succeed; stage2 --dump validation
# fails on every file until section 1 is fixed):
make clean && make bootstrap
```

## Status summary

| Bug | Status |
|-----|--------|
| A5 frontier: boxed dict field iteration (`pat.fields`) | **PATCHED** in tree (runtime dispatch); compiled binary can dump files again. Residual: `item.key`/`item.value` pair accessors regress 4 stdlib modules — open. |
| `_slit_` pool corruption (multi-char strings) | Open. Partial fix `c3cf1fa`; `_return_elem_types`/`_str_pool` dict reads still corrupt in the compiled binary. |
| Emission-ordering diffs (`_mojo_type_name`, struct-stub order) | Open. Byte-identity only; native `.ci` is valid C. |
| `_dedup_variadic_externs` self-host regression | **FIXED** (2026-08-04). Used `.finditer()`/`.findall()` inside a method/local-var regex — both are self-host-unsafe (confirmed independent of self-hosting: no codegen lowering for `.findall()` at all). Rewrote using plain `.split`/`.find` string ops. This, NOT the `item.key`/`item.value` gap, was the actual blocker making `mojoc --dump` fail on every file — the doc's earlier "PATCHED" claim for section 1 was not reproducible until this was also fixed. **Follow-up regression + fix (same day)**: the rewrite's `'extern' not in stmt` guard was a naive substring check — a `#line N "…/test_external_call.mojo"` directive contains "extern" as a substring of "external", which misclassified the following ordinary function-call statement (`std_testing___init___assert_false(_t5);`) as a concrete prototype, causing the REAL variadic extern declarations for that function to be dropped everywhere ("implicit declaration of function", `compile_stdlib.py`'s `test/ffi/test_external_call.mojo`). Fixed with a proper per-line `startswith('extern ')` check instead of a bare substring test. Verified via `compile_stdlib.py` against a clean isolated worktree of the pre-fix commit (`ef934c5`, 0% CAS hits, genuinely fresh compile): confirms the OTHER 8 stdlib/test failures compile_stdlib.py reports (the 4 already-documented ones plus 4 previously-undocumented ones — `test_atof.mojo`, `test_iterators.mojo`, `test_ref_iteration.mojo`, `test_numpy.mojo`) are pre-existing, NOT caused by this session's fixes; only `test_external_call.mojo` was a genuine regression, now fixed and confirmed back to the 8-failure baseline. |
| `isinstance(x, list/dict/set/str)` true for NULL pointer | **FIXED** (2026-08-04), `_isinstance_one_type` in gimple_codegen.py. Root cause of a severe, previously-undiscovered bug: once section 1's dict/list dispatch patch made loop bodies actually execute (rather than silently no-op), `getattr(obj, "field", None)` returning a NULL `MojoList *`/`MojoDict *` (the struct-doesn't-have-this-field default case) was misidentified as a real list/dict purely by STATIC type, with no NULL check. This let `_register_imported_structs__collect`'s worklist walk treat NULL as "more work," causing unbounded memory growth (confirmed via lldb: RSS 5GB→13GB+ climbing, killed) or a downstream wild-pointer crash, when self-hosting on a real-sized file (`mojo_compiler.py`) — never reproduced on trivial files. Fix: pointer-typed isinstance matches now also check the value is non-null. Verified: confirmed present in the CLEAN pre-fix `ef934c5` state too (not caused by the `_dedup_variadic_externs` fix), test_selfhost/test_gimple/test_module_cache all green, stdlib skip count unchanged (4). |
| `mojo_repr_str` wild-pointer crash on real self-host dump | **OPEN, well-characterized, not yet fixed.** `./mojoc mojo_compiler.py --dump` still segfaults (`EXC_BAD_ACCESS addr=0x4`) even with the two fixes above applied — this is a SEPARATE, third bug. Backtrace: `mojo_repr_str` ← `_mojo_repr_VarDecl` ← `_mojo_repr_list` ← `_mojo_repr_StructDef` ← `_mojo_repr_list` ← `_gimple_main`. A real (non-degenerate) `VarDecl *` object's `name` field (declared `char *`) holds the raw integer value `4` instead of a string pointer — confirmed via lldb register read (`x0=4` at the crash, `x19`=valid obj pointer, `[x19+offsetof(name)]`=4). Investigated leads that did NOT pan out: (1) the hardcoded self-host `struct_field_types['VarDecl']` table (gimple_codegen.py ~line 24524) is stale — real `VarDecl` has 5 fields (name/type_ann/value/line/col), the hardcoded seed only has 3 — and critically, real per-file struct-field derivation (~line 24759/24790) only fills a struct's fields `if name not in struct_field_types`, so the hardcoded stale entry permanently wins and is never refreshed from the real dataclass. Adding line/col to the hardcoded table did NOT fix the crash (rebuilt clean, same exact crash, same address). (2) Not a CAS/build-cache staleness issue — reproduces identically after `rm -rf ~/.gmojo/cas ~/.gmojo/jit` + full rebuild. Reproduction: `MOJO_NO_SHIM=1 python3 fire.py build fire.py -o mojoc && ./mojoc mojo_compiler.py --dump` (use `ulimit -t 30` — it used to hang/grow unboundedly before the isinstance fix above; now it fails fast). Does NOT reproduce on trivial files (`minimal_main.mojo`) or on a synthetic same-named `VarDecl` class in an isolated `.mojo` file placed in this repo dir — the trigger needs the REAL self-referential parse of mojo_compiler.py's own class bodies. Next step: use lldb watchpoints on the specific corrupted object's `name` field slot, set right after `_alloc_VarDecl` for the specific instance that ends up corrupted (heap address differs per run), to catch the actual wrong WRITE rather than reasoning about it after the fact. |
