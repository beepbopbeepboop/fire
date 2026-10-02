# RUNTIME: an int64 dict key in [2^31, 2^47) is dereferenced as a `char *`

## Status (2026-10-02 — the codegen supplies the answer in four places now;
## the PREDICATE is still unchanged and `ptrreg-boxed-str` is still red)

Landed, in this order of importance:

0. **2026-10-02: two more producers for `gen._int_word_vals`**, so the
   "monotone-safe, pure gain" argument below has two more instances of it.
   `_lower_UnaryOp` records `-n` / `~n` on an operand already recorded, and
   `_lower_binary`'s arithmetic tail records an integer result from two
   operands already recorded (read BEFORE the coercion block replaces the
   operand temps, marked at the final `t = lv op rv`, because every early
   return in between produces something that is not an integer). Neither
   involves inference, which is the whole reason they are safe: a miss falls
   back to the runtime's own discriminator, never to a crash.
   Measured: the case below SIGSEGVs on `bc17a62b` and matches CPython here.

   - `test_gimple_runner.py`'s `gimple_computed_dict_key_above_2gb_is_an_
     integer` — four shapes, one per way a large key can be *computed* rather
     than written: `i + 1` from a large literal, `-1`, literal + literal, and
     a small local times a large literal. `-1` is in the list because a
     negative word is OUTSIDE the predicate's window (a huge `uint64`), so the
     crash there is in the assignment rather than the lookup, and it is the
     shape that would pass a test written only for the positive range.

   Still not covered, and still the honest limit: an integer that arrives
   through an unannotated/erased parameter, a value read out of a
   heterogeneous container, or a call result. Those are not "no producer" but
   "needs real type inference", which is `mojo/middle/`'s to own — see the
   second bullet of the exact-next-step section below, unchanged.

1. **The codegen supplies the answer wherever it PROVABLY knows it.** A new
   positive record, `gen._int_word_vals`, is the exact complement of
   `_actual_types`: `_actual_types` records "this int64_t slot really holds a
   pointer", and `_int_word_vals` records "this value holds a plain Python
   integer". It is seeded in `_lower_IntLiteral` (an integer literal cannot be a
   pointer at ANY magnitude — no inference, no guess) and carried across
   assignments in `_track_pointer_actual_type`, which is the single chokepoint
   both the `VarDecl` and the plain-`AssignStmt` paths already use for exactly
   this kind of side-table carry, and which DISCARDS on an RHS the codegen
   cannot vouch for. That is what keeps it sound rather than optimistic:
   `k = 3000000000` marks `k`, `k = "s"` unmarks it.

   Two consumers:
   - `_char_to_cstr`'s `word_ok` branch — a dict-key site whose key is a known
     integer now renders its decimal with the new `mojo_int_str_transient` and
     uses the ORDINARY dict entry point, instead of handing the raw word to the
     `_kw` twin for the runtime to classify. Not a demotion: the dict
     re-normalises the text through `_canon_int`, so `d[5]` and `d["5"]` stay
     the one integer slot they have always been.
   - `_emit_call`'s `char *`-parameter coercion (see
     `CODEGEN_annotated_str_param_given_an_int_segfaults`, now fixed and its
     doc removed) — there a known integer goes through `mojo_str_from_int`,
     which is the KEPT variant, because the callee may store the pointer.

   `mojo_int_str_transient` is `_int_str_transient` published under a name
   that states the answer the caller already has: same block, same pool, same
   release protocol as `mojo_cstr_or_int_str`'s own integer half. It is not a
   second implementation.

   Measured on this tree: `d[3000000000] = 1; print(d[3000000000])` is
   `SIGSEGV` on the parent commit and `1` now, and the literal, a local bound
   from one, `in`, and a string key reached through a lambda (the `_kw` path,
   which must keep working) all match CPython.

2. **`ptrreg-boxed-str` is still red, correctly.** The `boxedstr` group asserts
   `mojo_boxed_is_str(big) == 0`, i.e. that the PREDICATE ITSELF becomes right.
   It does not, and by this doc's own argument below it cannot: the shape test
   is information-theoretically unable to separate an integer from a pointer.
   So the `expect=` marker stays, and this doc stays.

### What is NOT fixed

An integer that arrives in a `char *` slot or a dict key without the codegen
being able to type it: an unannotated/erased parameter, a value read out of a
heterogeneous container, a computed expression (`d[i + 1]`, `d[f()]`). Those
still go to the `_kw` twin or `mojo_cstr_or_int_str`, and an integer in
[2^31, 2^47) on one of them still SIGSEGVs. Nothing here narrows the range, so
nothing here can be blamed on a wrong guess.

### Exact next step

Two directions, and they are genuinely different jobs:

* **Widen `_int_word_vals`.** Every additional producer is monotone-safe — a
  miss falls back to today's behaviour, never to a crash — so this is pure
  gain. `_lower_UnaryOp` (`-n`, `~n`) and `_lower_binary`'s arithmetic tail
  (both operands recorded) are DONE (2026-10-02, the Status section at the top).
  The next ones in the same spirit, none of which needs inference:
  `_lower_CompareChain` (a comparison yields a `_Bool`, not an int64 word, so
  this is deliberately NOT one of them — the useful shape is a comparison whose
  result is immediately used as a dict key, which is not worth a producer), the
  `%`/`//` helpers (`_lower_floordiv`, `_lower_percent`'s generic numeric arm),
  and a call whose return type this codegen has RESOLVED to `int64_t`
  (`func_return_types` already records that, so a call returning `int64_t` from
  a known-int function is the same argument one level up — but note the
  resolution is a C type, and an erased `int64_t` return is exactly the case
  that is NOT evidence, so this needs the resolution and the erasure told
  apart, which is the same problem one level down).
  Beyond the mechanical producers it needs real type inference, which is
  `mojo/middle/`'s to own and not this file's.
* **Make the predicate sound**, which means giving the runtime provenance
  rather than a range: a registry of every string the program can hold, fed by
  the runtime's own string constructors AND by codegen for its string-literal
  pool. That is a real design change with a real failure mode of its own — a
  string built somewhere un-registered becomes a SILENT wrong answer rather
  than a crash, which this codebase consistently rates as the worse outcome —
  so it wants its own investigation, not a drive-by.

## Original report (2026-09-30)

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

## Next step (2026-09-30; step 1 is DONE — see the Status above)

The production fix is to stop asking the runtime to guess: have the codegen
supply the answer, which is what it is already positioned to do. `emit_infra.py`
records what it *saw* type-erased in `_actual_types`; a call site that knows its
argument is a `double` (the float-key path) or a genuine `int64_t` should emit
the int-keyed entry point directly and never call the `_kw` one. That removes
the guess from every statically-typed site and leaves the predicate to answer
only the genuinely ambiguous ones, where "wrong answer" is at least the current,
documented behaviour.

Concretely:

1. DONE — `mojo/backend_gimple/emit_infra.py`, `_char_to_cstr`'s `word_ok`
   branch: a key the codegen can prove is an integer now emits
   `mojo_int_str_transient` + the ordinary dict entry point and never reaches a
   `_kw` helper. `emit_infra.py` records what it saw type-erased in
   `_actual_types`, and the new `_int_word_vals` is the complement it lacked.
2. NOT DONE — re-measure how many sites remain genuinely ambiguous (the
   `lambda k: d[k]` case in the predicate's own comment is the model example,
   and it is still routed to the `_kw` twin, correctly).
3. NOT DONE, and now doubtful: narrow the range only for the residue, and only
   as a *crash* guard. Nothing landed narrows it — see the Status — and the
   predicate is still asked, so a narrowing here would trade one
   misclassification for another exactly as this doc's own "Why the range is
   there" section argues.

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
- `test_gimple_runner.py`'s `gimple_dict_key_above_2gb_is_an_integer` (added
  2026-10-01 with the codegen fix above): the end-to-end shape, pinned to
  CPython's own answers for a literal key, a local bound from one, `in` for a
  present and an absent large key, and the `lambda` string-key case that must
  keep going through the `_kw` twin. SIGSEGVs on the parent commit. It is the
  test that covers what landed; the `boxedstr` group covers what did not.
- `test_gimple_runner.py`'s `gimple_computed_dict_key_above_2gb_is_an_integer`
  (added 2026-10-02 with the two producers above): the same end-to-end shape
  for a key that is COMPUTED, in four spellings, pinned to CPython's answers.
  SIGSEGVs on `bc17a62b` for the whole program.
