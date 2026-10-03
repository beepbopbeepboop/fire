# FORMAL_a_method_of_a_one_field_holder_reads_a_nested_frame_nothing_built: `var b = Box(); return b.get()` SIGSEGVs where the store half of the same program is refused

**Area:** FORMAL (`formal/build.py`, the one-field-holder receiver seeding that
`7632c881` landed; the method-call path that reaches it). Found 2026-10-03 on
`work/formal13-4` while measuring step 2 of
`bugs/FORMAL_method_call_on_a_construction_is_not_rewritten.md`. **Status: OPEN,
pre-existing, measured on both architectures, and it is a CRASH rather than a
refusal** — the outcome `bugs/FORMAL_per_export_contracts.md` §"The retraction"
and `formal/macho_linker.py`'s own comments both name as the one to avoid landing
a change against.

## The measurement

`.tmp/ow/nest2.mojo` — ten lines, no imports, one two-field struct and one
one-field struct:

```python
struct Opt:
    var v: Int
    var has: Int

struct Box:
    var inner: Opt

    def get(self) -> Int:
        return self.inner.v

def main() -> int:
    var b = Box()
    return b.get()
```

```console
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/ow/n2 .tmp/ow/nest2.mojo
Built: .tmp/ow/n2  [arm64/macho]
$ .tmp/ow/n2 ; echo $?
Segmentation fault: 11
139
$ … --backend=x86_64 -o .tmp/ow/n264 .tmp/ow/nest2.mojo && .tmp/ow/n264 ; echo $?
Segmentation fault: 11
139
```

CPython raises `AttributeError` (`Box` has no attribute `inner`), so there is no
answer to compare — and the honest answer here is a refusal, not a number.

## The boundary is the landed fix's own, on the other side

`7632c881` ("a ONE-FIELD struct whose sole field is a FRAME now seeds its method's
receiver, and the write half that would segfault is refused") landed with exactly
this program, and it works on both architectures today:

| program | arm64 | x86-64 | what it is |
|---|---|---|---|
| `var b = Box()` ; **`b.inner = Opt()`** ; `b.inner.v = 41` ; `return b.get()` | 41 | 41 | the landed case — the nested frame is BUILT first |
| `var b = Box()` ; **`b.inner.v = 5`** ; `return b.get()` | REFUSED | REFUSED | the landed "write half" clause. Message: `'b.v' is a field access through 'b'` — **which names `b.v`, and the source says `b.inner.v`**, so the store is at least loud |
| `var b = Box()` ; `return b.get()` | **SIGSEGV** | **SIGSEGV** | this document. The READ half through a method, with no store to refuse |
| `var b = Box()` ; `return b.get()` with a second field on `Box` (`var pad: Int`) | 0 | 0 | control: `Box` is then a FRAME, the receiver is an address into scratch, and the unwritten slot reads 0 |

So the landed fix made the STORE loud and left the READ through a method silent,
and the difference between the last two rows is `struct_is_framed(Box)` — False for
a one-field struct, True with the extra field. With one field, `Box`'s value is a
WORD and that word *is* `b.inner`, i.e. it is meant to be the address of an `Opt`
frame; `Box()`'s construction leaves it 0, and the receiver seeding then reads
`self.inner.v` as a load at address 0.

That is the whole of it, and it is worth stating plainly because the shape looks
harmless: **the program never asks for the nested frame, and reads it anyway.**
The refusal the landed fix added is on the channel a program can be caught by (a
store through the unestablished slot); a method that reads the slot has no such
channel, so the unestablished read walks straight into the load.

## Where the check belongs

Next to the landed one — `formal/build.py`'s receiver seeding for a one-field
holder (`7632c881`, and the `_one_word_field_map` flattening it uses), or in
`_check_frame_escapes`, which is where a frame read through an unestablished base
is otherwise caught. The question to ask is:

> for a one-field holder `h` whose field's declared type is a FRAMED struct, does
> any call site ever CONSTRUCT the frame at `h`'s word?

`h.inner = Opt()` does (and is why the landed program works). `h = Box()` does not,
because `Box()`'s construction initialises the WORD, not the frame it will hold —
and the difference between "0 for a field of a frame" and "a refusal" is the whole
of this bug. `bugs/FORMAL_a_one_word_frame_holder_constructor_is_answered_by_the_reader_rule.md`
is the neighbouring question about the same word (who answers a read of it), so the
two are worth reading together; this one is about who answers it when NOTHING has.

## Exact next step

1. Reproducer first, and it is ten lines with no C runtime in it: no `printf`, no
   host module, no dylib. Anything that "fixes" this by touching the printf path
   is fixing a different defect.
2. Decide the DIRECTION before writing the check: refuse (`b.get()` reading a
   nested frame no call site built — naming `b.inner` and saying what to write
   instead: `b.inner = Opt()`, which is measured working), or place the frame at
   the construction site (`struct_construction_plan` /
   `struct_nested_frame_fields`, which is what
   `bugs/FORMAL_method_call_on_a_construction_is_not_rewritten.md` step 2 needs and
   would answer two documents at once). **Refusing is the smaller change and the
   one this tree's conventions point at** — the same reasoning as the landed
   commit's own "the write half that would segfault is refused".
3. The four-row table above is the test matrix: all four rows must be either right
   or refused, and the control row (the two-field `Box`) is what says a fix did not
   simply widen a refusal to every read of a frame field.
4. `test_formal_receiver_position.py`'s `refuse_*` table is where a refusal case
   belongs (its rows pin the message, on both backends).