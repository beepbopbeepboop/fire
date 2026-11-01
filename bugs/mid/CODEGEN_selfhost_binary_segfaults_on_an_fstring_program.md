# CODEGEN: the self-hosted compiler binary segfaults (exit -11) compiling a small program with f-strings

## Status (2026-10-31, OPEN, found while verifying a perf change; reproduced on unmodified master)

`test_selfhost.py`'s binary check compiles a two-line program with NO f-string, so it cannot see this. Build the
self-host binary the way that test does (`test_selfhost.build(td)`), then:

    def f(a, b):
        return f"x={a} y={b + 1} z={a * 2}"
    print(f(3, 4))
    name = "w"
    print(f"hello {name} {len(name)}")

    <td>/mojo_selfhost --dump-full f.mojo      ->  exit -11, no .ci
    python3 fire.py --dump-full f.mojo         ->  29,667-byte .ci

Same result on master (`05d55428b`-era tree, binary built from an untouched checkout) and on a tree with a
token-memo edit, so it is not from that edit. f-string interpolation is the one place the compiled compiler
parses source text at codegen time (`emit_exprs._lower_StringLiteral`: `Parser(py_tokenize(text))._parse_expr(0)`,
then `ast_rewriter.rewrite_node`, then `lower_expr`), and an earlier note there records that this path once
lowered every interpolation to the empty string when compiled.

## Status update (2026-10-31, worker bug-mid-codegen-selfhost-binary-segfault): not reproduced here, no fix landed

What this round measured (light-worker budget: no self-host build, so the binary crash could not be reproduced
from the current tree):

- Ran the prebuilt `mojoc` in `mojo-reference/` (built 2026-10-23, an older tree than the one this doc names)
  on the two-function f-string program above, via `memslot --gb 8`: exit 0, 25,643-byte `f.ci`, no segfault.
  Interpolation is lowered correctly: `_slit_10000 = "x="`, `mojo_str_cat` chain over `a`, `b + 1`, `a * 2`,
  and the `hello {name} {len(name)}` line emits its pieces. So the crash is either newer than 10-23 or depends
  on the binary's build, not on the program alone.
- Static wiring of the f-string path checked and consistent: `emit_exprs._lower_StringLiteral` imports
  `Parser`/`py_tokenize` at module scope, calls `gimple_ctypes.ast_rewriter.rewrite_node` (which exists,
  `ast_rewriter.py:957`, and `mojo/middle/types.py:27` re-exports `ast_rewriter`), and wraps the whole
  interpolation in `except Exception`. An exception there becomes a warning plus literal text, so the crash is
  NOT a Python-level exception; it has to be a native fault (a bad pointer or a stack overflow in the compiled
  parser/rewriter) that `except` cannot see.

Next step (needs a self-host build, so it is the integrator's or a heavy worker's to run):

1. Build the binary the way `test_selfhost.build(td)` does and rerun the two-function program with
   `--dump-full`; confirm the exit -11 on the current HEAD (09a309b23) before anything else.
2. Bisect by field: the five interpolations one at a time (`a`, `b + 1`, `a * 2`, `name`, `len(name)`), each
   in its own program, to learn whether it is the field parse (`Parser(py_tokenize(text))._parse_expr(0)`),
   `rewrite_node`, or `lower_expr`. A binary-only fault with the Python path green points at the compiled
   parser's recursion or a boxed-value read.
3. lldb on the binary at the crash (`tools/gdbtool`, HOW-TO-DEBUG.html), then the fix at the faulting frame.
4. Regression: extend `test_selfhost.run_produced_binary` with an f-string program so the `selfhost` step covers it.

## Status update (2026-10-31, round 2, worker bug-mid-codegen-selfhost-binary-segfault): planning guide, no fix

Round output is a planning guide (no build allowed to this worker; the crash needs the self-host binary).

What is established by reading, not by running:

- The crash is in the compiled CODEGEN of an f-string, not in parsing `f.mojo`. The two-line program with no
  f-string is clean on the same binary, and every f-string site is in `emit_exprs._lower_StringLiteral`'s
  f-string branch (`mojo/backend_gimple/emit_exprs.py` ~L357-420; `gimple_codegen.py:5187` forwards to it).
- Python-level failures inside an interpolation are caught by `except Exception` (~L392) and become a warning
  plus literal text. So a -11 means a native fault. Work that runs OUTSIDE that `try` is the set of candidates
  where a binary-only fault can escape:
  1. `gen._parse_fstring_parts(val)` (`mojo/middle/resolve_shared.py:1863`, wired as `gimple_codegen.py:5698`).
     Its 4-tuple slots are the same ones the self-hosted type-inference comment warns about (only the first
     slot was once typed; the annotation fixed that). The `while i < len(inner)` scan indexes `inner[i+1]`
     directly; an off-by-one or a boxed `inner` would read past the string.
  2. The `_lit`/`_all_lit` loop and the `plain += _as_str(_pv2)` accumulation (near the top of the f-string branch, ~L366-390): reads `_pv2` from
     the boxed slot.
  3. The accumulator loop after the `try` (~L420 onward): `acc_val` / `free_left` / `free_right` ownership.
     A wrong free on a borrowed `_slit_` or variable temp is a use-after-free crash that shows up only when
     more than one interpolation is concatenated, which fits `f(a,b)`, whose three interpolations and literal pieces make many cats in one expression.
- Inside the `try`, a native fault can still happen in `Parser(py_tokenize(text))._parse_expr(0)` (the compiled
  parser on a fresh string at codegen time), `rewrite_node`, `lower_expr`, `_stringify_value`, `_repr_value`,
  `_apply_fstring_spec` (`mojo/backend_gimple/emit_infra.py:4839`, uses `spec[1]` after `len(spec) >= 2`).

Decisions needed (controller/integrator, once a binary exists):

- Whether the first fault is in the parse (candidate 1, a str-slot read), the cat chain (candidate 3, a free),
  or inside the `try`. Decided by lldb on the binary, not by this reading. If lldb shows the faulting frame in
  `mojo_str_cat` or a `free`, it is candidate 3; if it is in `_parse_fstring_parts` or the tokenizer, candidate 1.

Implementation plan once the frame is known:

1. Reproduce: `test_selfhost.build(td)` then `<td>/mojo_selfhost --dump-full f.mojo` (exit -11 expected).
2. Field bisect: five single-interpolation programs (`{a}`, `{b + 1}`, `{a * 2}`, `{name}`, `{len(name)}`), each
   in its own file, to split the parse/rewrite/lower causes from the cat-chain cause.
3. lldb: `tools/gdbtool` on the binary, break at the fault, `bt`, then the source line in
   `emit_exprs.py` or `resolve_shared.py`.
4. Fix at the faulting frame. A fix in `_lower_StringLiteral` must not change the generated C for programs
   without f-strings: `cmp` the `--dump-full` output for `test_selfhost`'s two-line program before and after.
5. Regression: a new one-program test with an f-string added to `test_selfhost.run_produced_binary`'s cases,
   plus a quick check that the generated `.ci` for `f.mojo` is byte-identical to the Python-path `.ci` in
   the parts that are not f-string text. The `selfhost` step (heavy) must run it, so it is an integrator job.

Heavy jobs this needs (NOT run by this round): the `selfhost` step (`python3 tools/suite.py selfhost`), and the
self-host binary build (`test_selfhost.build`). Light check that was run: none new this round.

## Next step

1. Reduce: which of the five f-string fields crashes (try each alone), and whether it is the field parse,
   `rewrite_node`, or `lower_expr` (lldb on the binary; `tools/gdbtool`, HOW-TO-DEBUG.html).
2. Fix it, then extend `test_selfhost.run_produced_binary` to compile a program that contains an f-string so
   this class is covered by the gate (a green `selfhost` today says nothing about f-strings).
