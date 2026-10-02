# RUNTIME: an int64 dict key in [2^31, 2^47) is dereferenced as a `char *`

## Status (2026-09-30 — OPEN, confirmed by execution; NOT fixed)

A program that uses a large integer as a dict key segfaults. Reproduced in the
runtime unit test, at -O0, -O2 and under AddressSanitizer:

    d = {}; d[3000000000] = 1        # SIGSEGV

Found while adding the float-key pool regression to `test_ptr_registry.py`, and
reported by name as that harness's `boxedstr` group — the registered
`ptrreg-boxed-str` test, `expect=`'d. It is a **pre-existing** bug, unrelated to
the float/pool work that surfaced it.

## Cause

`mojo_cstr_or_int_str(int64_t v)` (runtime/fire_runtime.c) has to answer "is
this word already a boxed `char *`, or an integer that needs a decimal?". It
delegates to `mojo_boxed_is_str`, which is

    _mojo_ptr_shaped(v) && !mojo_is_registered_list(v) && !mojo_is_boxed(v)

and `_mojo_ptr_shaped` (runtime/fire_runtime.c:904) is **range-only**:

    static int _mojo_ptr_shaped(int64_t addr) {
        uint64_t u = (uint64_t)addr;
        if (u < 0x80000000ULL) return 0;          /* below 2^31 */
        if (u >= 0x0000800000000000ULL) return 0; /* at/above 2^47 */
        return 1;
    }

So every **positive** `int64_t` in `[2^31, 2^47)` is classified as a pointer. A
plain integer in that window is then cast to `char *` and handed to `strcmp` /
`strlen`, and the process dies. Confirmed misclassified:

| value | hex | `mojo_boxed_is_str` |
|---|---|---|
| 2147483648 | `0x80000000` | 1 → crash |
| 3000000000 | `0xb2d05e00` | 1 → crash |
| 4294967296 | `0x100000000` | 1 → crash |
| 1099511627776 | `0x10000000000` | 1 → crash |
| 70368744177664 | `0x400000000000` | 1 → crash |
| 2147483647 | `0x7fffffff` | 0 → fine |
| 140737488355328 | `0x800000000000` | 0 → fine (at the ceiling) |
| any negative int64 | | 0 → fine (`u` is huge) |

Every `_kw` entry point routes through the same predicate —
`mojo_dict_get_int_kw`, `mojo_dict_contains_kw`, `mojo_dict_pop_int_kw`,
`mojo_dict_setdefault_int_kw` — so all four crash on such a key, as does
`mojo_cstr_or_int_str` itself (any string-context use: `%s` formatting,
concatenation, `f"{n}"`).

## Why the range is there, and why narrowing it is NOT the fix

The window is deliberate and documented at the predicate. Two things constrain
it from below and above, and the comment above `_mojo_ptr_shaped` is explicit
that both were derived from real failures:

- **2 GiB floor.** Values below it are `None`, small ints, bools, and the
  31-bit `zlib.crc32(name) & 0x7fffffff` struct type-tags that a compiled
  `type(node)` yields where a class object belongs. A previous predicate let
  those through and handed them to `strlen` — CRASH.md's segfault.
- **2^47 ceiling.** The struct predicate's canonical-userspace ceiling; a
  garbage 64-bit word above it must not reach `strlen` either.

The two registry exclusions (`!is_registered_list`, `!is_boxed`) exist because a
boxed float out of a heterogeneous list is pointer-shaped and is not a list —
`struct.unpack('<if', buf)` printed a wrong number as a segfault.

So the shape test is the only discriminator available, and **it is
information-theoretically unable to be right**: in this compiler's scalar body
model a `char *` and an `int64_t` are the same 64 bits with no tag. This is not
a bug with a one-line fix; it is the ambiguity the codegen already knows about,
which is exactly what the `_actual_types` map exists for.

Note what is *not* the fix, explicitly, because each looks reasonable:

- Tightening the range does not help — every choice of bounds trades one
  misclassification for another, and there is no bound that separates "integer"
  from "pointer".
- Requiring the address to be registered would reject every real string: dict
  slot keys are size-exact `malloc`s and codegen string literals live in
  `__TEXT`/`__rodata`, neither of which is in `_reg_*`.

## Next step

The production fix is to stop asking the runtime to guess: have the codegen
supply the answer, which is what it is already positioned to do. `emit_infra.py`
records what it *saw* type-erased in `_actual_types`; a call site that knows its
argument is a `double` (the float-key path) or a genuine `int64_t` should emit
the int-keyed entry point directly and never call the `_kw` one. That removes
the guess from every statically-typed site and leaves the predicate to answer
only the genuinely ambiguous ones, where "wrong answer" is at least the current,
documented behaviour.

Concretely:

1. In `mojo/backend_gimple/emit_infra.py`, wherever a `_kw` helper is chosen
   today, prefer the non-`_kw` entry point when the argument's ctype is known.
2. Re-measure how many sites remain genuinely ambiguous (the `lambda k: d[k]`
   case in the predicate's own comment is the model example).
3. Narrow the range only for the residue, and only as a *crash* guard, with a
   comment saying it is a guard and not a discrimination.

Step 1 is a real codegen change, so per CLAUDE.md it owes a full `make gate`,
and it cannot land without touching the compiled path's `_kw` selection.

## Coverage

- `test_ptr_registry.py --group boxedstr` (`test_boxed_str_discrimination`):
  asserts `mojo_boxed_is_str(big) == 0` for all five misclassified values, then
  that `mojo_cstr_or_int_str` renders each as its decimal, then the same key
  through a real `mojo_dict_set_int` / `mojo_dict_get_int` round trip. It fails
  today, on the first assertion, as a clean assert rather than a segfault —
  deliberately, so the report is legible.
- Registered as `ptrreg-boxed-str` with an `expect=` reason, so the suite shows
  it as EXPECTED and it flips to FAILURE the moment the predicate is fixed.
- 4294967296 was in `test_dict_and_itoa`'s `vals[]` before this, which is how the
  value entered the file — but that group never ran, because
  `python3-config --cflags` supplies `-DNDEBUG` and the whole harness is written
  in `assert`. See the note in `test_ptr_registry.py`'s `_flags`; the case is
  now in the `boxedstr` group so the two concerns are separate.
