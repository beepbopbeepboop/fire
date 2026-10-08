# `printf("%s", <a list>)` builds, prints nothing and exits 0 — the THIRD cell of the container table

**Area:** FORMAL, both backends — `printf`'s vararg placement. **Status: NOT
FIXED.** Found 2026-10-08 (`work/formal169-docs`) while closing the `%d`
sibling (`bugs/FORMAL_printf_d_of_a_container_prints_its_address.md`, now
deleted with its fix).

## What I ran, what I saw, what I expected

```console
$ cat .tmp/pl/s.mojo
def main() -> Int32:
    var xs = [1, 2, 3]
    printf("v=%s", xs)
    return 0

$ python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/pl/s .tmp/pl/s.mojo
Built: .tmp/pl/s  [arm64/macho]
$ ./.tmp/pl/s ; echo "exit=$?"
v=exit=0

$ cat .tmp/pl/sc.mojo
def main() -> Int32:
    var d = {"a": 1, "b": 2}
    printf("v=%s", d)
    return 0
$ ./.tmp/pl/sc ; echo "exit=$?"
v=exit=0
```

Nothing on stderr, exit 0, and the operand's content is nowhere in the output.
A container's value on this path is the frame ADDRESS of a counted blob
(`is_list_kind`; a dict and a `bytearray` are the same counted blob), so `%s`
walks bytes at that address — the blob's COUNT word — and stops at the first
zero byte. The program on the screen is not the program the source wrote.

## Why this is the missing cell and not a new family

The `printf` container table has four cells, and three are decided:

| conversion \ operand | number | container |
|---|---|---|
| `%d` | answered | **refused** — `model.printf_container_conversion_refusal` (2026-10-08) |
| `%s` | refused — `model.printf_arg_text_evidence`'s step 3/5 | **this row: not refused** |

`printf("%s", 42)` is refused by name because `%s` is the one conversion that
DEREFERENCES what it is handed. A container is the same hazard with a different
word: `printf_arg_text_evidence` asks whether the operand is text, and for a
container it answers `None` (the permissive direction it reserves for an
unannotated parameter), so the refusal never fires and the frame address reaches
the C library. `print(xs)` already refuses this shape ("print() cannot tell
whether … is a string or a number"), so the builtin and the raw `printf`
disagree about the same operand.

## The exact next step

**One row, beside `printf_container_conversion_refusal`, on the text axis.**
`printf_arg_text_evidence` already receives the receiver as `arg` and has
`vk.kind_of`; a container answer (`is_list_kind`) there would produce an evidence
string and let `printf_text_conversion_refusal` fire — but its sentence is
written for an integer ("an integer is a NUMBER … a small integer"), so the
cleaner shape is a dedicated reader with its own words, asked from
`printf_format_refusal` beside the number-conversion row and handed the SAME
kind hook the emitters already pass (`self._expr_str_kind`). The message should
name the conversion and the operand's kind, as CPython's own
`TypeError: %s format: … not list` does, and say that the word is the blob's
frame ADDRESS rather than its bytes.

Two things the next reader should decide rather than assume:

1. **Whether the `%s`-of-a-container refusal can move a stdlib or hostmod
   build.** `%s` is common and a blob reached as `char *` may be an intentional
   pattern somewhere this change did not look; the file was filed rather than
   landed because a light worker cannot run the stdlib sweep that would measure
   it. The narrow `%d` sibling moved nothing, and this one should be measured
   before it lands.
2. **A `bytearray` is the third spelling** (same counted blob, `list:byte`), so
   the row must be asked of the KIND (`is_list_kind`) exactly as the number row
   is — a fix written against a list constructor's name would pass the list case
   and miss the dict and the `bytearray`.

The test belongs beside `printf_d_of_a_list_is_refused` in
`test_formal_run.py`'s `PRINTF_TEXT_CASES`, as a `refuse:` row (both
architectures must produce the SAME words), with a control that `%s` of a string
and `%s` of a `String` field still print.

## Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
printf 'def main() -> Int32:\n    var xs = [1, 2, 3]\n    printf("v=%%s", xs)\n    return 0\n' > .tmp/pl/s.mojo
python3 tools/memslot.py --gb 8 --label s -- \
    python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/pl/s .tmp/pl/s.mojo
./.tmp/pl/s ; echo "exit=$?"     # v=  exit 0 — a green build, nothing printed
```
