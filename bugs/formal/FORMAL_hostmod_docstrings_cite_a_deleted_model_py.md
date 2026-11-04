# FORMAL_hostmod_docstrings_cite_a_deleted_model_py: eight hostmod references to formal/model.py dangle on master

**Area:** FORMAL (`test_formal_link_accounting.py::test_hostmod_cross_references`, red on master as of 2026-11-03).

## What I ran

`python3 tools/memslot.py --gb 8 --label x -- python3 test_formal_link_accounting.py`
while working `bugs/formal/FORMAL_stdlib_module_names_are_not_classified.md` (whose
ledger lives in this file). Result: `331 passed, 1 failed, 332 checks` — the one
failure is the pre-existing one below, unrelated to that work.

## What I saw

`test_hostmod_cross_references` walks every `.mojo` under `formal/hostmods/`,
extracts the files their prose names, and asserts each exists. Eight references
point at `formal/model.py`, which is deleted:

| the reference | what it points at | where that now lives |
|---|---|---|
| `formal/hostmods/argparse.mojo:140` | `_FLOAT_SCALARS` | `formal/model/builtins.py:2186` |
| `formal/hostmods/argparse.mojo:717` | `string_compare_word_refusal` | `formal/model/values.py:2785` |
| `formal/hostmods/argparse.mojo:3288` | the "silently truncated" prose | to be located |
| `formal/hostmods/ast.mojo:37` | the "What a value is" section | `formal/model/cfg.py` (also `builtins.py`) |
| `formal/hostmods/ast.mojo:137` | the `char *` string convention | to be located |
| `formal/hostmods/enum.mojo:58` | the frame answers | `formal/model/frames.py` (to confirm) |
| `formal/hostmods/fcntl.mojo:202` | `VARIADIC_LIBC` | `formal/model/builtins.py:2802` |
| `formal/hostmods/fcntl.mojo:335` | the stack-frame offset prose | to be located |

The file went in two steps, both already on master: `31ca1c149`
("Reorganize formal/model.py into formal/model/*.py") split it into a package,
and `819e3d5f3` ("port the subscript-store model delta into the package; drop
corrupt model.py") deleted the shim. Neither updated the eight hostmod
references, so the accounting suite has been red on master since `819e3d5f3`.
This is the same failure class `test_hostmod_cross_references` was written for
(its docstring: four hostmod references to files that were not there) — a claim
with no evidence behind it, now a suite red.

## What I expected

`test_formal_link_accounting.py` green: the references name the file that
carries the thing, so a reader clicking through lands on it.

## Why this was not fixed here

It is the tail of the model package split (`bugs/formal/FORMAL_model_package_
split_left_duplicate_copies.md`), whose claim is held by another worker, and the
fix means reading each of the eight references and naming the sub-file that now
carries it — a change to four `formal/hostmods/*.mojo` files, which is this
worker's rule 5 territory (another worker's area). Reported rather than fixed.

## Next step

1. For each of the eight rows, locate the section/symbol in `formal/model/`
   (the table above has four of the eight; `grep -n "silently truncated\|What a
   value is\|char \*" formal/model/*.py` finds the rest) and rewrite the
   reference to name that file.
2. Re-run `python3 tools/memslot.py --gb 8 --label x -- python3
   test_formal_link_accounting.py` — the cross-reference check goes green when
   the last of the eight names a file that exists.
3. This doc is deleted with that commit.
