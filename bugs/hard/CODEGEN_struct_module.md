# CODEGEN: the `struct` module (binary pack/unpack) in the compiled path

**State: CLOSED.** Both recorded codegen gaps fixed (per-slot unpack kinds for mixed int/float formats;
`var`-declared class fields, which had been a NULL-deref segfault). The `.format`
residual recorded here was found to be misdescribed and has been moved to its own doc:
CODEGEN_struct_format_shadowed_by_format_attribute.md.


## Status (2026-09-25 audit — BOTH remaining codegen gaps closed)

Stages 1–4 (below) are landed and were sound. This pass audited what they
left open and closed the two that were codegen problems, recording one
that is not.

### Closed: mixed int+float unpack formats (was a documented degradation)

The Design section said a format mixing ints and floats "degrades to int64
slots". It does not degrade *gracefully* — `struct.unpack('<if', buf)`
returned `1 4607182418800017408`, i.e. the float's raw IEEE bits, because
the result is one `MojoList` and a `MojoList` carries a single element
ctype.

But the *format string is a compile-time constant*, so each slot's real
kind is statically known and only the CONTAINER is untyped. Fixed by
recording the per-slot kinds and letting the subscript pick the accessor
per index:

- `_struct_slot_kinds(codes)` (`emit_methods.py`) — one of
  `'int'`/`'double'`/`'bytes'` per value, in wire order.
- `_struct_tag_unpack_result` records it in a new
  `gen._struct_slot_kinds`, propagated to the local name by the `VarDecl`
  path exactly as `_elem_types` is (this propagation is load-bearing: with
  the unpack temp only, the `var m = struct.unpack(...)` spelling silently
  did nothing, which is how the first attempt at this fix appeared to fail).
- The `MojoList *` subscript path consults it for a **literal** index —
  the overwhelmingly common shape. A computed index genuinely has no
  static answer, so it keeps the uniform fallback rather than guessing.

Verified by real compile+link+run: `'<if'` → `1 1.0`, `'>dhh'` → `1.0 2 1`,
`'<Bd'` → `7 1.0`, `'<fd'` round-trip → `1.25 -0.5`, and the uniform cases
(`<2f`, `<3i`, `<4s`) unchanged. Regression tests
`gimple_struct_mixed_int_float_formats` and
`gimple_struct_uniform_formats_still_uniform` in `test_gimple_runner.py`.

### Closed: `var`-declared class field with a `struct.Struct(...)` default

The gap was recorded as "the constructor does not emit the initializer, so
the field is NULL at runtime" — and the real-world consequence is worse
than "does not work": the first `self.FIELD_STRUCT.size` **segfaulted**
(NULL dereference), and a scalar `var NAME = 'hello'` field read back `0`.

Root cause, and it was in three places, not one:

1. **Class-attribute registration** matched only a bare `NAME = ...`
   (`AssignStmt`), never `var NAME = ...` (`VarDecl`).
2. **The `_classattr_<Cls>__<X>` global declaration + init** loop had the
   same `AssignStmt`-only match, so even once registered there was no
   global and nothing to initialize.
3. **The field's own type** was assigned by a different loop that only
   recognised *container* defaults, so `var NAME = 'hello'` was typed
   `struct <Cls> *` — the "unknown field" fallback. That in turn defeated
   the allocator's per-instance init, which is gated on the field type and
   the `_classattr_` global type agreeing. This is the asymmetry that made
   the bare spelling work and the `var` spelling not: the bare form is an
   `AssignStmt`, so it never entered that loop at all.

Fixed by a shared `_class_field_decl(field)` helper returning
`(name, value)` for either spelling, used by both class-attr passes, plus
a literal-default type in the field-type loop (string → `char *`, float →
`double`, int/bool → `int64_t`) and a single type resolution in the
registration pass so the field and global types always agree.

Verified by real compile+link+run: `var FIELD_STRUCT = struct.Struct('<HH')`
now reads `1 2 4` (was a segfault), and `var NAME/N/ITEMS/TABLE` class
fields read `hello 5 0 0` (were `0 0 0 0`). Regression test
`gimple_struct_var_declared_class_field`.

### Moved to its own doc: calling `Struct.format(...)`

`.format` on a `Struct` is a real, separate defect, but this doc's earlier
note about it was wrong in both halves and has been replaced rather than
carried forward. Re-tested:

- the ATTRIBUTE READ `s.format` is **correct** (`<HH`, matching CPython) —
  not "a pointer-sized integer", as recorded here before;
- the CALL `s.format(70)` returns **`0`** with exit 0, where CPython and
  this repo's own reference interpreter both raise `TypeError: 'str'
  object is not callable` — because `format` is an attribute shadowing the
  method, so calling it is an error;
- the LOCAL spelling fails exactly like the class-attribute one, so this is
  not a class-attribute-read-path bug.

Tracked, with the full evidence and the dispatch asymmetry that identifies
where to look, in
`CODEGEN_struct_format_shadowed_by_format_attribute.md`. Confirmed
identical on a clean `HEAD~1` worktree, so it is pre-existing and not a
consequence of anything in this doc.

### Audit result for the other two recorded gaps — still open, unchanged

- Keyword args to `struct.*` (`unpack_from(fmt, buf, offset=0)`) still
  fall through (guarded out); positional only.
- No interpreter (`myinterpreter.py`) `struct` module — compiled path
  only, so a comptime-evaluated `struct.Struct(...)` default still
  `NameError`s.

### Verification

`test_gimple_runner.py` 84/84, `test_gimple.py` 316/316,
`test_gimple_generator_runner.py` 128/128, `test_generators.py` 29/29,
`test_module_cache.py` 81/81, `test_link_mode.py` 3/3, and
`compile_stdlib.py` **664/664 with 0 unexpected** — the last run because
both changes touch class-attribute and field-type registration, which every
class body in the corpus passes through, so the stdlib breadth check is the
load-bearing one here rather than optional.

## Problem

The compiled path (`mojo_compiler.py` → `gimple_gen_*.py` → C/GIMPLE, runtime
in `runtime/`) had **zero** support for Python's `struct` module. No
`struct.pack` / `struct.unpack` / `struct.Struct` / `struct.calcsize`,
no `mojo_struct_*` runtime. It is needed by
`bugs/COMPILE_FAIL_zipfile___init__.md` (blocker 4:
`_Extra.FIELD_STRUCT = struct.Struct('<HH')`, `struct.unpack(...)`,
`except struct.error:`) and is used across pickle / wave / aifc /
plistlib / many `Tools/*`.

## Design

Packed data **is** `bytes` (`MojoBytes` — `{uint8_t* data; int64_t len}`,
`mojo_bytes_*`, from `bugs/hard/CODEGEN_bytes_value_type.md`). A compiled
format is an opaque `MojoStructFmt *` carrying the resolved byte order,
`calcsize()`, and an expanded op list (one `MojoStructOp` per value; `x`
padding folded into offsets, `s`/`c` one op of N bytes).

GIMPLE cannot pass a mixed int64/double vararg list, so codegen lowers
`struct.pack(fmt, a, b, c)` to a `MojoList *` of values —
`mojo_list_append_int` for integer/bool codes, `mojo_list_append_double`
for `f`/`d`, a `MojoBytes*` pointer in an int slot for `s`/`c` — and calls
`mojo_struct_pack_list(fmt, MojoList*)`. `mojo_struct_unpack` returns a
`mojo_mark_as_tuple`'d `MojoList*`; codegen tags its element ctype from
the (statically known) format: all-int → `int64_t` slots, all-float →
`double`, all-`s` → `MojoBytes *`. A genuinely **mixed int+float** format
degrades to int64 slots (documented gap — rare; the common integer
formats used by zipfile/pickle/wave are exact).

`struct.error` reuses the exception-tag mechanism:
`mojo_struct_raise_error` sets tag `MOJO_STRUCT_ERROR_TAG`
(`== crc32("struct.error") & 0x7fffffff == 1315445615`, matching
`gimple_gen_infra._exc_type_id('struct.error')`), so `except struct.error:`
catches it.

### Format mini-language

Prefix `< > = ! @` (`@` native size+align default; `<` LE, `>`/`!` BE,
standard sizes for `<>=!`, no padding). Codes `x b B h H i I l L q Q f d s
? c` with optional leading count (`4h`, `10s`). Whitespace ignored.
Native `l`/`L` is `sizeof(long)` (8 on LP64); standard is 4. Signed reads
sign-extend.

## Where it lives

- **Runtime**: `runtime/mojo_runtime.c` (`mojo_struct_*` section, before
  `mojo_char_to_str`) + `runtime/mojo_runtime.h` decls.
  `mojo_struct_compile` / `calcsize` / `pack_list` / `pack_h` / `unpack` /
  `unpack_from` / `unpack_h` / `unpack_from_h` / `pack_into` /
  `pack_into_h` / `new` / `size` / `format` / `raise_error`.
- **Return types**: `gimple_ctypes.py` `_RUNTIME_RET` (~370) and the
  parallel copy in `gimple_codegen.py` (~249); signatures in
  `gimple_codegen._KNOWN_SIGS` (~2197).
- **Module-call dispatch**: `gimple_gen_methods.py`
  `_lower_struct_module_call` + `_STRUCT_METHODS`, hooked in
  `_lower_method_call` right after `module_name = func.obj.name`.
- **`struct.Struct` instance methods**: `_lower_struct_instance_method`,
  hooked on `ot == 'MojoStructFmt *'` after `method = func.member`.
- **`s.size` / `s.format`**: `gimple_gen_exprs.py` `_lower_MemberExpr`.
- **`FIELD_STRUCT = struct.Struct(...)` class attr**: `_class_attr_ctype`
  (`gimple_ctypes.py`) → `'MojoStructFmt *'`; init emission +
  `_collect_self_assigns` + VarDecl-field-default inference in
  `gimple_module_gen.py`.
- `MojoStructFmt` added to `_CPP_OPAQUE_PTR_STRUCTS`.

## Status — LANDED (2026-09-06)

Stages 1–3 landed together as one coherent changeset (shared runtime
substrate + one codegen dispatch site).

**Stage 1 — module-level functions.** `struct.calcsize`, `struct.pack`,
`struct.unpack`, `struct.unpack_from`, `except struct.error:`. Verified
compile+link+run: `calcsize('<HH')==4`, `pack('<HH',1,2)`,
`unpack('<HH', b'\x01\x00\x02\x00')==(1,2)`, `pack('>i',258)`,
`pack('4s', b'ab')`, signed `<q` round-trip, `<f`/`>d` float round-trip,
`unpack_from` at offset, `struct.error` on a short buffer.

**Stage 2 — `struct.Struct`.** `s = struct.Struct(fmt)` (compiled once),
`s.pack` / `s.unpack` / `s.unpack_from`, `s.size`, `s.format`. A
`Struct` held as a **bare class attribute**
(`FIELD_STRUCT = struct.Struct('<HH')`) and used as
`self.FIELD_STRUCT.unpack(...)` works end to end.

**Stage 3 — `struct.pack_into(fmt, buffer, offset, *values)`** writes into
a `bytearray`. Verified.

**Follow-up (same session).** Two shapes that only surfaced on real
`Lib/zipfile/__init__.py`:
- `struct.pack(fmt, a, *rest)` — a trailing splat arg. `_struct_build_
  value_list` now `mojo_list_extend`s from the iterable's raw int64
  slots (struct splat args are ints in practice) and forces the
  per-index code map off.
- `struct.pack(...) + X` where `X` isn't statically `MojoBytes *` (a
  struct field / param codegen inferred as a bare pointer or int64
  handle). The scalar `+` path was casting the bytes handle to int64
  and emitting `int64 + pointer`, which ICE'd GCC's GIMPLE FE
  (`build2 at tree.cc:5204`). `gimple_gen_exprs._lower_BinaryOp` now
  coerces the non-bytes operand to `MojoBytes *` and uses
  `mojo_bytes_concat` whenever exactly one side is bytes.
Both covered by `gimple_struct_pack_splat_and_concat` in
`test_gimple_runner.py`.

### Known gaps

- A `var`-declared **instance field** with a `struct.Struct(...)` default
  (`var FIELD_STRUCT = struct.Struct('<HH')`) gets the right field ctype
  now but the constructor does not emit the initializer, so the field is
  NULL at runtime. The **bare class-attribute** form (what real zipfile
  uses) works. Not chased further.
- Mixed int+float unpack formats degrade to int64 slots (see Design).
- Keyword args to `struct.*` (`unpack_from(fmt, buf, offset=0)`) fall
  through (guarded out); positional only.
- No interpreter (`myinterpreter.py`) `struct` module — this is the
  compiled path only. A comptime-evaluated `struct.Struct(...)` default
  (e.g. a generic-param-shaped first field) still hits the interpreter
  and `NameError`s.

## zipfile re-probe

`compile_to_gimple(do_imports=False)` on `zipfile/__init__.py` is
`gcc -fgimple -fsyntax-only` CLEAN with this change (it was already clean
before, via `struct.pack` being an unknown int64-returning stub — the
follow-up fixes above keep it clean now that `struct.pack` is real and
returns `MojoBytes *`). The remaining blocker there is `class
_Extra(bytes)` — a **bytes-subclass** feature — plus `_Extra.split` being
a `@classmethod` generator and `super().__new__`. `struct` itself is no
longer a blocker for that file.
