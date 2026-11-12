# CODEGEN: `#line` is emitted once per statement, so a `gcc -fgimple` error inside a statement that lowers to many lines is reported at the wrong source line (up to 70 lines off)

Status: OPEN. Filed 2026-11-12 from a failing self-host build whose three error locations did not point at the construct that failed. Class: easy (one emitter, one measurable property of the output).

## Symptom

`gcc -fgimple` reports `file.py:LINE` for an error in `fire.ci`, where LINE is the last `#line` directive's number plus the count of generated lines since it. A statement that lowers to N lines carries ONE directive, so an error on its k-th generated line is reported at source line (statement line + k), which is a different line, a comment, or past the end of the file.

Observed in the self-host build of 2026-11-12:

| gcc reported | what is there |
|---|---|
| `mojo/backend_gimple/module_gen.py:13818` | a comment block (`# base's would read _classattr_Base__tag ...`): nothing there can fail |
| `elaborate.py:1481` | a dict-literal line (`'ret': _mojo_type(ret) ...`); the regex call (`re.sub`) is at 1478 |
| `fire_compiler.py:7379` | the tail of a `ParseNode(... is_tstring=_is_t)` call; the regex statement it is blamed for starts at 7364 |

## Measured

Counting generated lines between consecutive `#line` directives in `.ci` files from current master:

| file | longest run of generated lines under ONE `#line` (excluding the preamble under `#line 1`) |
|---|---|
| `re3.py` (an 8-line program, one `re.sub` with a lambda) | **70** lines under `#line 4` |
| `mixed_ret2.py` (a 30-line program) | 13 lines under `#line 32`, 13 under `#line 26` |
| `re1.py` | 31 lines under `#line 9` |

So an error on the 70th generated line of `re3.py`'s line-4 statement is reported as about line 74 of an 8-line file.

## Why it matters

Every codegen error in the self-host closure (a 30 000-line compile) has to be found by reading the generated `fire.ci` around a guessed spot. The three errors above (see `CODEGEN_gen_module_impl_char_pointer_assigned_from_int64.md` and `CODEGEN_regex_tables_array_to_pointer_var_decl_non_trivial_conversion.md`) were each reported at a line that could not be the cause.

## Fix

Emit the directive so that every generated line maps to its statement's line: a `#line N "file"` before each generated line of the statement (or the equivalent GCC linemarker with the line repeated), not once per statement. Keep the output deterministic (the bootstrap compares stages byte for byte, so the change lands once and applies to all three stages).

## Acceptance

- In the `.ci` of a program with a multi-line lowering (the `re3.py` shape: `re.sub(r'(\\N\{[^{}]*\})|([{}])', lambda m: ..., s)`), no run of generated lines inside a function body is longer than one line without its own `#line`.
- A regression test, `test_line_directives_per_generated_line.py`, compiles such a program through `compile_to_gimple` and asserts that, inside every function body, each generated line is preceded by a `#line` naming its statement's source line.
- Behaviour-preserving apart from directives: the generated C with directives stripped is byte-identical before and after (`cmp` it on `re3.py` and one large succeeding case).

## Done when

`python3 test_line_directives_per_generated_line.py` passes and the stripped-output `cmp` is identical. A worker does not run the self-host build; say so.
