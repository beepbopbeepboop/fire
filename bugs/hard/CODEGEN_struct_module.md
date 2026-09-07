# CODEGEN: the `struct` module (binary pack/unpack) in the compiled path

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

`compile_to_gimple(do_imports=False)` on `Lib/zipfile/__init__.py` was
already `gcc -fgimple -fsyntax-only` CLEAN before this change (the
`struct` uses inside `_Extra` never surfaced at the syntax-check level).
The remaining blocker there is `class _Extra(bytes)` — a **bytes-subclass**
feature — plus `_Extra.split` being a `@classmethod` generator and
`super().__new__`. `struct` itself is no longer a blocker for that file.
