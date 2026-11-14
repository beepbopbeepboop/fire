# GIR: a typed IR for the gimple backend

Status: stages 0, 1 and 2a landed 2026-11-13. This file is the plan and the rules. Read it
before changing anything under `mojo/backend_gimple/` or `mojo/ir/`.

## 1. What is wrong today (measured 2026-11-13)

The gimple backend is `gimple_codegen.py` + `mojo/backend_gimple/*.py` +
`mojo/middle/*.py`: 148,753 lines, 2,591 functions. GCC's own C front end
needs about 2,700 lines to read the same GIMPLE text (`c/gimple-parser.cc`).

- **A type is a Python string** holding C spelling. There are 1,652 inline
  `== 'int64_t'`-style comparisons, 354 `.endswith(' *')` pointer tests, and ten
  different hand-written "scalar integer type" sets.
- **`int64_t` means four things**: a real integer, a pointer stored in an
  integer ("erased"), a dynamic word of unknown kind, and a tagged box. Which
  one a value is lives in about 57 dictionaries on `gen` keyed by the temp's
  NAME (`_elem_types`, `_boxed_vals`, `_dyn_word_vals`, ...). A copy
  `x = y` must copy up to 57 entries by hand; forgetting one is 15% of sampled
  backend bug fixes.
- **A statement is a string.** 2,850 call sites build text
  (`gen._emit(f"  {t} = mojo_list_len ({v});")`). Facts are then recovered by
  reading the text back: `_emit_raw` finds ` = mojo_` to decide ownership,
  `startswith('return ')` to decide control flow, and a `try` frame slices the
  value out of a `return` line.
- **Twelve functions hold 26% of the code** (`gen_module_impl` is 15,397 lines).

What is NOT wrong, also measured: the emitted text is type-consistent at the C
level. Over 188 generated files (726,918 statements) the checker finds 191
type findings, all of them call arguments. Explicit cast statements (106,000 in
`fire.ci`) make every copy legal. So the type-unsafety is in how the generator
REASONS, not in a flood of illegal statements. `_KNOWN_SIGS` (606 runtime
signatures, hand-written) also agrees with `runtime/*.h` on all but 2 entries.

### The call-argument hole (proven)

GCC verifies only functions tagged `__GIMPLE` (top-level `def`s are emitted
untagged, as plain C), and even in a tagged function it never checks a call's
arguments. A mismatched argument is passed unconverted:

    __GIMPLE int64_t g (void) {
      int _t1; int64_t _t2;
      _t1 = getint ();          /* returns -5 */
      _t2 = show (_t1);         /* show (int64_t) */

`show` receives 4294967291 at `-O0` and 9223372032559808507 at `-O2`
(gcc-mp-15 15.3, arm64): no sign extension is emitted. An integer passed to a
`double` parameter arrives in the wrong register. Real instances in the
compiler's own output: `MojoString.byte_length` (`mojo_box_word (<int>)`) and a
`pow (2.0, <int64_t>)` in `myinterpreter.py`.

## 2. The target

    AST --lowering--> GIR (typed values, typed instructions) --printer--> text
                           |
                           +-- verifier (every function, every argument)

Four layers, in `mojo/ir/`:

| file | what | state |
|---|---|---|
| `types.py` | `Type` objects, interned. `trivially_convertible`, `mismatch_class`, `cast_is_legal` are the ONLY code that decides type compatibility | landed |
| `instr.py` | `Ex` (operand), `Instr` (statement), `Function`, `Module`, `Sig`. Ten statement shapes cover 98% of today's emission | landed |
| `verify.py` | type-checks a `Module`, returns `Finding`s with stable codes | landed |
| `reader.py` | TRANSITIONAL. Parses emitted `.ci` text and `runtime/*.h` into a `Module`, so the verifier can check today's string backend | landed |
| `build.py` | the builder the lowering code will call instead of `gen._emit(f"...")` | stage 2 |

Beside it, in `mojo/middle/`: `rt_sigs.py` (generated runtime signatures) and
`rt_call.py` (which scalar arguments need a conversion statement).

Rules that hold from now on:

1. **No new type-compatibility logic outside `mojo/ir/types.py`.** If you need
   to know whether two types match, call it.
2. **`types.py`, `instr.py`, `verify.py`, `build.py` must stay self-hostable**:
   plain classes, every field annotated in `__init__`, no closures, no lambdas,
   no `re`, no tuple unpacking, no `getattr`, no generators. `reader.py` is
   tool-side and may use anything; the compiler must never import it.
3. **Unknown is not `int64_t`.** The verifier never guesses: an undeclared name
   or unknown callee is counted in `Report.unknown` and not checked.
4. **A finding count may only go down.** `test_gimple_lint.py` holds the
   baseline.

## 3. How to use the checker

    python3 fire.py --dump x.mojo            # writes x.ci
    python3 tools/gimple_lint.py x.ci        # summary by finding code
    python3 tools/gimple_lint.py -v --code arg-int-widen x.ci
    python3 test_gimple_lint.py              # unit tests + the ratchet (10 s)

Finding codes are `<position>-<class>`:

| position | meaning |
|---|---|
| `copy` | `a = b;` |
| `op` | an operand of a binary operation or `?:` |
| `cmp` | the two sides of a comparison |
| `ret` | `return v;` against the function's return type |
| `arg` | a call argument against the callee's parameter |
| `cast` | `a = (T) b;` where `T` is not `a`'s type |
| `lit` | as above, but the operand is a literal of the wrong KIND |

| class | meaning |
|---|---|
| `int-widen` | narrower integer where a wider one is expected |
| `int-narrow` | wider integer where a narrower one is expected (truncation) |
| `int-sign` | same width, different signedness |
| `bool-int` | `_Bool` vs integer |
| `int-ptr` | integer vs pointer (the erased-pointer hazard) |
| `int-float` | integer vs floating point |
| `ptr-kind` | two different pointer types. GIMPLE allows it; GIR does not |

Plus `cmp-result` (a comparison stored into a non-`_Bool`), `cast-illegal`,
`arg-count`.

The fix for an `arg-*` finding is almost always the same: the call was spelled
as text. Route it through `gen._call_expr(ret, fname, [(ctype, value), ...])`
or `gen._emit_call(...)`, which coerce each argument to the declared parameter
type from `_KNOWN_SIGS`.

## 4. Stages

Each stage has a ratchet, so partial progress is safe to land and cannot
regress. Byte-identical `.ci` output over a corpus is the oracle for any stage
that is meant to be behaviour-preserving:

    # before and after the change, in two empty directories:
    for f in <corpus>; do python3 fire.py --dump $f; done ; diff -r before after

- **Stage 0 (landed).** `mojo/ir` types, instructions, verifier, reader;
  `tools/gimple_lint.py`; `test_gimple_lint.py` registered as `gimple-lint`.
- **Stage 1 (landed 2026-11-13). The call-argument hole is closed for
  runtime calls.** `mojo/middle/rt_sigs.py` is GENERATED from `runtime/*.h`
  (`python3 tools/gen_rt_sigs.py`; 1,014 signatures, where the hand-written
  `_KNOWN_SIGS` has 606). `_repr_fix_args` in `emit_infra.py` is the last step
  of `_emit_call`: it takes the parameter type from the headers and the
  argument's type from its DECLARATION (`gen.var_types`), trusting neither the
  caller's `(ctype, value)` claim nor the partial table, and emits the
  conversion as its own statement. Three calls that were spelled as text
  (`mojo_cmp_fold`, `pow`, `main`'s `return result;`) were routed through it.
  Over the 188-file corpus (727,209 statements) the findings went 191 -> 1;
  the one left is `compile_to_gimple (src)` in `fire.py`'s single-module dump,
  a call to a program function with 1 of its 4 arguments (defaults not padded
  across modules), which is not a runtime call.
  `BASELINE` in `test_gimple_lint.py` is empty and must stay empty.
  Not covered: a call spelled as TEXT (`gen._new_val(t, f"mojo_x ({v})")`)
  never reaches `_emit_call`. That is stage 2.
- **Stage 2a (landed 2026-11-13). Runtime calls take values, not text.**
  `gen._rt_call(ret, 'mojo_x', [a, b])`, `gen._rt_into(dst, 'mojo_x', [a, b])`
  and `gen._rt_void('mojo_x', [a, b])` (`emit_resolve.py`) are THE way to call
  a runtime function. They take values, never `(ctype, value)` claims, and
  run the same `_repr_fix_args` as `_emit_call`. A script rewrote 501 of the
  527 text-spelled runtime calls; non-compiler programs in the corpus are
  byte-identical before and after. `TEXT_CALL_BASELINE` in
  `test_gimple_lint.py` (26) may only shrink; the remainder is
  `bugs/CODEGEN_runtime_calls_spelled_as_text.md`.
- **Stage 2a, casts (landed 2026-11-13).** `gen._cast(ctype, v)` and
  `gen._cast_into(dst, ctype, v)` state the type once. A script rewrote 540 of
  548 casts spelled as text; `TEXT_CAST_BASELINE` (8) may only shrink.
  `gimple-lint` is in the LANDING gate (`tools/gates.json`), so a branch that
  adds a text-spelled runtime call or cast, or a call-argument finding, does
  not land.
- **Stage 2b. The builder.** `mojo/ir/build.py`: `call`, `cast(value, type)`,
  `copy`, `binop`, `cmp`, `load_field`, `store_field`, `br`, `cond_br`, `ret`,
  `label`. Each returns a typed value and appends an `Instr`.
  `_rt_call`/`_emit_call`/`_new_val`/`_safe_coerce_emit` become thin callers.
  Ratchet: the count of `gen._emit(f"` (about 900 after stage 2a) may only
  shrink. The cast sites (`_new_val(T, f"(T2){x}")`, 418 of them) are the next
  mechanical batch: `gen._cast(T, x)`.
- **Stage 3. Statements are `Instr`, not strings.** `gen.body_lines` becomes a
  list of `Instr`; the four function-assembly sites print it. `_emit_raw`'s
  text sniffing (`' = mojo_'`, `startswith('return ')`) and `EmitFrame`'s
  return-slicing read `Instr` fields instead.
- **Stage 4. Types are `Type`, not strings.** `var_types` holds `Type`.
  The ten scalar sets and the 2,400 string tests are replaced by `Type`
  methods. Ratchet: counts of `.endswith(' *')` and `== 'int64_t'`.
- **Stage 5. One value-info record.** The 57 name-keyed tables become fields
  of one `ValueInfo` object per temp, with one `copy_info(dst, src)`.
  `int64_t` splits into Int / Erased(T) / DynWord / Box in the value's info.
- **Stage 6. Shape.** One loop builder replaces the 18 copies of the counted
  loop skeleton across 28 `_gen_for_*`/`_compr_*` functions; the giant
  functions are split along their `isinstance` arms.
- **Stage 7. Other printers.** The C++ coroutine lowering (`cpp_core.py`,
  `cpp_async.py`, 16,400 lines, a second walk of the same AST) and the direct
  GCC bridge (`gcc/fire/fire-gimple-bridge.cc`, today a stub that builds
  `int main(){return 0;}`) become printers over GIR.
