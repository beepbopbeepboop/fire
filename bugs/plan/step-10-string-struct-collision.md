# plan/step-10: the `String` frame-vs-`char *` collision (zero-argument `String()` used as a receiver)
Class: mid      Size: M      Depends: 01a, 01b (convention only; no Lean change here)      Blocks: 11
Source: `bugs/FORMAL_string_value_model.md` § "NOT the string value model: the 16 ..." (line ~190) and "Wave 8" §2 (line ~983, the SIGBUS-turned-refusal reproducer).

## Current state (measured 2026-11-05)
- **P0, the tree does not import.** `python3 -c "import formal.model"` fails with `NameError: name 'threading' is not defined` at `formal/model/layout.py:3155` (`_LIBSYSTEM_LOAD_LOCK = threading.Lock()`); commit `13ae7d389` removed `import threading` from `formal/model/__init__.py`. Every `fire.py build --formal` dies with it. I measured everything below with a scratch wrapper that injects `builtins.threading`. Worker FIRST runs `python3 -c "import formal.model"`; if it prints the NameError, add `import threading` at the top of `formal/model/layout.py` (NOT `__init__.py`; `13ae7d389` removed it from there for a host-module-closure reason) and re-run it. If the error is already gone (someone fixed it), skip. Commit that as its own first commit, message "formal/model/layout.py: import threading".
- Reproducer, verbatim (this is `test_formal_value_model.py:2257` and the `_park_construction_mismatches` docstring, `formal/build.py:6064`):
```
struct String:
    var _ptr_or_data: Pointer[UInt8]
    var _len_or_data: Int
    var _capacity_or_data: Int
    def size(self) -> Int:
        return self._len_or_data

def main(n: Int) -> Int:
    var a = String()
    a._len_or_data = 5
    return a.size()
```
  Today (both backends): build REFUSES with `a = String(...) binds a to a value this path holds as TEXT, and a.<field> asks for a frame: String is declared here as a struct of 3 field(s)...` (text: `model.construction_mismatch_refusal`, `formal/model/structs.py:1544`). Before that refusal existed it was SIGBUS exit 138. CPython answer: 5.
- Control that must keep working (measured: builds, prints `[]`): same `struct String` declared, then `var s = String(); printf("[%s]\n", s); return 0`. `s` is a `char *` (text reading) because it is never used as a receiver.
- Cause: both emitters intercept `String()` as a type conversion BEFORE struct construction: arm64 `formal/arm64_codegen.py:12011-12024`, x86-64 `formal/x86_64_codegen.py:13280-13293` (`type_constructor_prefers_local_struct` is deliberately false for `STRING_TYPE_CTORS` = `("String","str","StringLiteral","StringSlice")`, `formal/model/types.py:103`, because `Pointer`'s identity conversion must keep winning). The build pass asks a different question: `model.call_lowers_as_framed_construction` (`formal/model/types.py:1049`), called from `formal/build.py:3718, 6129, 9196, 10003` and `formal/model/frames.py:250`. `_park_construction_mismatches` (`formal/build.py:6064`) parks the disagreement; `check_construction_mismatches` (`formal/build.py:6138`, called at `:3165`) raises it.
- `model.string_has_static_storage()` (`formal/model/values.py:4414`) is defined and consumed by nobody (grep: only a comment in `strings.py`). The draft's "argument-position analysis (D4)" is NOT needed by this design: a frame-reading `String` goes through the existing framed-struct by-reference machinery (wave 3/8), which already decides argument positions and returns.
- The "16 files" sweep family cannot be re-measured cheaply and the doc itself says the ceiling of the stdlib files is zero (they hit a SECOND frame refusal). Do not promise a sweep delta.

## Decisions already made
- **ONE rule, per call node, in `formal/model/`:** a call `C(...)` has the FRAME reading iff ALL of: `C` is in `STRING_TYPE_CTORS`; this module declares `struct C` and `struct_is_framed(C)`; `nargs == 0`; `C` is not a function name in the image; the call is the value of a single-name binding (`frame_binding_target`/`frame_binding_value`, `formal/model/frames.py:151,175`) whose target name is the root of a `MemberExpr` somewhere in the same function body (this is the exact "used as a receiver" test `_park_construction_mismatches` already applies via `_root_ident(node)[1] >= 1`). Everything else keeps the TEXT reading, unchanged.
- The decision is stored ON THE CALL NODE: attribute `_string_frame_reading = True`, set once by a new build-pass function before any binding analysis runs. Reason: five analysis sites and two emitters all hold the `CallExpr`; a node mark is one fact read everywhere, so they cannot disagree (the exact bug being fixed). Precedent for hanging a verdict on an AST node: `fn._construction_mismatch`.
- A frame-reading local that is later used as a text value (`printf("%s", a)`) is NOT special-cased: the existing "frame address passed where a value is wanted" refusals apply. Do not add new refusal text for it unless a test row below fails.
- `String("x")` (nargs>0) followed by a field store keeps the existing `construction_mismatch_refusal`. That refusal stays, and its test row stays.

## Work order
1. (P0 above.)
2. `formal/model/frames.py`: add `string_frame_reading_calls(fn, structs, functions=()) -> list` returning the `CallExpr` nodes satisfying the rule. Walk `iter_nodes(fn.body)` exactly like `struct_constructor_bindings` (line 187). Receiver test: any `F.MemberExpr` node whose root identifier (`formal/build.py:3322 _root_ident` is build-only: move its body to `formal/model/frames.py` as `root_ident` and make build.py's `_root_ident` delegate to it, one definition) equals the binding target.
3. `formal/model/types.py`: add `call_is_string_frame_reading(call) -> bool` (`getattr(call, "_string_frame_reading", False)`). Change `call_lowers_as_framed_construction(callee, structs, nargs, functions=(), call=None)`: first line `if call is not None and call_is_string_frame_reading(call): return True`. Export both from `formal/model/__init__.py` (the star-imports do it if no `__all__`; check with `python3 -c "from formal import model as M; M.call_is_string_frame_reading"`).
4. `formal/build.py`: new `_mark_string_frame_readings(functions, framed)` that, for each fn, calls `M.string_frame_reading_calls` and sets the attribute. Call it at the TOP of the frame pass, before line 4449 uses `framed` for bindings: place it immediately after `framed = M.framed_struct_names(structs)` (line 4449). Pass `call=value` (resp. `call=node`) at the four build.py call sites and the `frames.py:250` site (each already holds the `CallExpr` as `value`/`node`).
5. `formal/arm64_codegen.py` ~12011 and `formal/x86_64_codegen.py` ~13280: immediately BEFORE `if not is_extern_call and name not in self._functions:` insert `if M.call_is_string_frame_reading(e): self._emit_struct_constructor(e, name, self._structs[name]); return`. Same text on both.
6. Tests. (a) `test_formal_value_model.py:2257` row `a_name_that_is_both_a_struct_and_a_conversion_is_refused`: change its source's constructor to `String("x")` (one argument) so it keeps pinning the mismatch refusal, rename to `a_one_argument_string_conversion_written_through_is_refused`. (b) `test_formal_run.py` `BOTH_ARCH_CASES` (line 6536; shape `(name, source, want_exit, want_stdout)`; runner `run_both_arch_case`): add `string_frame_reading_reproducer` = the reproducer above, exit 5; `string_frame_reading_returned` = same struct plus `def make() -> String:` / `var s = String()` / `s._len_or_data = 5` / `return s`, and `main` does `return make().size()`, exit 5 (the returned half is wave 8's `RETURNED_FRAME_CASES` machinery; if it refuses, STOP per If stuck); `string_text_reading_control` = the control above, exit 0, stdout `[]`. (c) Optional unit row (skip if `test_formal_value_model.py` has no non-build check function to imitate: `grep -n "^def \|^class " test_formal_value_model.py`) calling `M.string_frame_reading_calls` on the parsed reproducer (1 node) and on the control (0 nodes).
7. Docs: in `bugs/FORMAL_string_value_model.md` Status add a dated entry (what landed; what remains = the 16 stdlib files still hit a second refusal, unmeasured). Do NOT delete the doc.

## Do NOT
- Do not make `type_constructor_prefers_local_struct` return True for `STRING_TYPE_CTORS`: it flips `var s = String(); printf("%s", s)` (measured working) to a frame, and breaks `Pointer`'s identity conversion.
- Do not decide per function ("any receiver use anywhere"): decide per call node.
- Do not touch `lib/`.
- Do not run `tools/formal_sweep.py`.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_value_model.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py string_frame_reading_reproducer string_frame_reading_returned string_text_reading_control a_name_that_is_both_a_struct_and_a_conversion_is_refused
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py
```
(the last, full file, is long: run once at the end; if over the memslot time, run it in the background and read the tail.)

## Done when
- [ ] `python3 -c "import formal.model"` exits 0
- [ ] the three new `test_formal_run.py` rows pass on both backends (reproducer answers 5)
- [ ] `test_formal_value_model.py` passes with the renamed one-argument refusal row
- [ ] `grep -n "_string_frame_reading" formal/*.py formal/model/*.py` shows exactly: the setter in build.py, the model predicate, two emitter reads

## If stuck
Write into `bugs/FORMAL_string_value_model.md` Status: the failing row's name, the exact refusal text, and which of steps 4/5 you had landed; leave tests of the failing row out and commit the rest only if the full `test_formal_value_model.py` is green. Then stop.
