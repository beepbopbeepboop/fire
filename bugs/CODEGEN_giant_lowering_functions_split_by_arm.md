# The giant lowering functions still hold about 2,400 lines of movable `if` arms

Class: easy, mechanical. A tool does the edit and checks it. Read
`doc/GIR.md` "Stage 6, arms of the giant functions" first.

## What is wrong

A lowering function such as `_lower_subscript` is one long chain of
`if <shape>: ... return ...` arms. A reader, or a model with a small context,
has to hold the whole function to change one arm, and an arm can quietly read
or overwrite a local that another arm owns. Each arm that reads only the
function's own parameters can be its own function.

`_lower_call` and `_lower_method_call` were done on 2026-11-14 (35 arms,
3,951 -> 1,423 and 3,261 -> 2,060 lines). Measured the same day on this tree
with `python3 tools/extract_arm.py --list FILE PARENT 25`:

| file (`mojo/backend_gimple/`) | function | movable lines |
|---|---|---|
| `emit_methods.py` | `_lower_dict_method` | 466 |
| `emit_calls.py` | `_lower_subscript` | 444 |
| `emit_exprs.py` | `_lower_IdentExpr` | 384 |
| `emit_calls.py` | `_lower_call` | 377 |
| `emit_calls.py` | `_lower_named_call` | 252 |
| `emit_exprs.py` | `_lower_MemberExpr` | 207 |
| `emit_exprs.py` | `_lower_binary_tail` | 126 |
| `emit_methods.py` | `_lower_struct_method_call` | 87 |

## Goal

Move every arm the tool lists, one function per round. Do one PARENT, verify,
commit, then the next.

## Steps for one PARENT

1. List the arms:

       python3 tools/extract_arm.py --list mojo/backend_gimple/emit_calls.py _lower_subscript 25

   Each line is `LINE: N lines  returns|falls through  extra inputs: ...`.
   A line that says `NO (...)` cannot be moved; skip it.

2. Take the baseline. In an empty directory OUTSIDE the tree:

       python3 /path/to/tree/fire.py --dump /path/to/tree/mojo/backend_gimple/emit_calls.py

   Keep the `.ci` file. Dump two or three other compiler sources and five
   test programs from `test/` the same way; these are the corpus.

3. For each `extra input`, find its C type in the `.ci` file: search for the
   PARENT's definition (`MojoList * _lower_subscript_<hash> (int64_t gen,`)
   and read the declarations under it. The annotation to pass is:

   | declaration in the `.ci` | pass on the command line |
   |---|---|
   | `char * ot;` | `ot:str` |
   | `_Bool flag;` | `flag:bool` |
   | `int64_t ov;` | `ov:` (nothing after the colon) |
   | `MojoList * xs;` | `xs:list` |
   | `MojoDict * d;` | `d:dict` |

   An arm with `extra inputs: none` needs nothing.

4. Move the arms from the BOTTOM of the function upwards (highest LINE
   first), so the lines of the arms not yet moved shift by a known amount.
   After each move, run `--list` again and use the new LINE numbers.

       python3 tools/extract_arm.py mojo/backend_gimple/emit_calls.py _lower_subscript 12345 \
           _ls_slice_of_bytes "\`x[a:b]\` where \`x\` is bytes." ot:str ov:

   The new name starts with a prefix for the PARENT (`_ls_` here; `_lc_` and
   `_lmc_` are taken) and says what the arm lowers. It must not exist
   anywhere under `mojo/` or in `gimple_codegen.py`:
   `grep -rn "def _ls_" mojo gimple_codegen.py` must print nothing first.
   The text in quotes becomes the docstring; say what source shape the arm
   handles.

5. Do not edit the moved code by hand. The tool refuses when it cannot prove
   the move is safe; a refusal is the answer for that arm.

## How to verify

1. Dump the corpus again into a second empty directory. Every `.ci` file
   except the edited file's own must be byte-identical (`diff -r`).
2. In the edited file's new `.ci`, find each new function's definition line.
   Its parameter types must be the types from step 3. One exception is
   correct: a parameter passed as `name:` may come out as a container
   pointer (`MojoDict * name`) when the arm uses it as one. Then the line
   before the call in the PARENT must cast the argument to that type
   (`_t5 = (MojoDict *)_t4;`). `_lmc_generator_method` is the example.
3. `python3 test_gimple.py` must print the same pass count as before the
   change with 0 failed.
4. `python3 tools/suite.py stdlib-syntax stdlib-dylib gimple-lint` must pass.

## Done when

`--list` prints `0 lines can be moved` for every function in the table (or
only `NO` lines remain), the checks pass, and this file is deleted in the
same commit (then run `python3 tools/dangling_doc_refs.py --ratchet`). A
partial round removes the finished rows from the table.
