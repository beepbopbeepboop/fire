# FORMAL_a_subscript_of_a_field_declared_a_framed_struct_is_a_wrong_answer: `w.d[0]` reads a frame's first field as a blob count and returns a number nobody wrote

**Area:** FORMAL, both backends. **Status: OPEN, measured on this tree; it is a
SILENT WRONG ANSWER, not a fault, which is why it is a separate document from
the one whose fix left it out.** Found 2026-10-03 while fixing
commit f0df70b2,
whose census said "the frame kind is out of scope for that fix" and whose fix
therefore deliberately excluded it.

## What I ran

A struct field whose DECLARED type is a framed struct of this module, read
through a subscript:

```python
struct Deep:
    var x: Int
    var y: Int
struct Wrap:
    var d: Deep
    var t: Int
def main() -> Int:
    var w = Wrap()
    w.d.x = 3
    w.d.y = 4
    printf("%d", w.d[0])
    return 0
```

```
arm64    prints 4, exit 0
x86-64   prints 4, exit 0
```

CPython refuses it — `TypeError: 'Deep' object is not subscriptable` — so there
is no oracle number and the program is one no reader would write on purpose.
The answer is 3 if anything: `w.d` is `Deep`'s frame base and slot 0 of that
frame is `x`. The two machines print **4**, which is `Deep`'s SECOND field, and
that is not an accident of the layout — it is the arithmetic:

```
count  = mem_read_u64(w + 0)              # Deep's slot 0 == x == 3
addr   = w + 8 + 8*count                  # w + 32
value  = mem_read_u64(addr)
```

`w + 32` is past `Deep`'s two slots, so the number is whatever the frame's
scratch region holds next to it. It happened to be 4 here; nothing guarantees
it, and the same program with one more spilled local would print something else.
This is `frame_container_operand_refusal`'s own paragraph ("offset 0 of a frame
is the struct's FIRST FIELD") reaching a spelling its recogniser cannot see.

## Why the fix for the sibling doc left it out, and why that was right

`model.NON_CONTAINER_SLOT_KINDS` is `(INT_KIND, TYPE_KIND)`, and `FRAME_KIND` is
deliberately excluded — the docstring says so and gives the reason: a frame
address read as a container is a wrong ANSWER rather than a fault, so it is a
different defect. Two measurements decided it rather than taste:

* **In the corpus it is ambiguous.** Every `X.<field>[i]` in the 610-file stdlib
  corpus was classified by its field's declared type; the census is in
  `model.slot_container_operand_refusal`'s docstring. 7 sites land in the frame
  bucket, and following two of them (`std/collections/dict.mojo`'s `self._dict`
  at `self._dict._order[i]`, `benchmarks/collections/bench_dict_string.mojo`'s
  `self.keys[i]`) shows the census attributing FRAME_KIND through a
  `structs_declared` lookup that finds a *framed struct of the same name* in
  the module — `Pointer[...]` is not a frame, so those two are misattributions.
  A rule that fired on that bucket would have refused sites the census cannot
  account for, and a refusal that fires on a site the corpus needs is the
  failure mode every other fix in this family is arranged to avoid.
* **The correct answer is not obviously a refusal for a frame field.** A struct
  on this path is a frame of 8-byte slots, and `h.f` where `f` is declared as a
  framed struct IS a frame base — so `w.d[i]` could be *given* an answer the
  way `w.d.x` is, by reading slot `i` of the frame the slot names. That is a
  lowering, not a diagnostic, and it is a different decision from the one the
  sibling doc settled.

## The exact next step

1. Decide, and write down, whether `X.f[i]` with `f` declared a framed struct is
   (a) a refusal — "`f` is the ADDRESS of a `Deep` frame and this path reads a
   container's count out of offset 0, which for a frame is its first field" — or
   (b) a load at `base + 8i`, which is what `w.d.x` already is one level up.
   `model.subscript_base_lowering`'s `("blob", 8, False, None)` row is the
   decision point and its own docstring says a base nothing establishes is
   deliberately left as a blob; a base established to be a FRAME is the case
   that row was written to exclude and does not.
2. Whichever is chosen, it belongs beside `NON_CONTAINER_SLOT_KINDS` and
   `slot_container_operand_refusal` in `formal/model.py`, and the emitters need
   no new arm — `_refuse_slot_container_operand` already asks the shared
   question and would fire the moment `FRAME_KIND` is in the set. That is the
   whole of the fix on the emitter side, and it is why the set is named.
3. Re-run the corpus census with a `structs_declared` lookup that excludes a
   type whose name is in `IDENTITY_TYPE_CTORS`, and only then widen the set.
   Until that number is right, 7 is not a coverage cost — it is noise.
4. Test: the program above as a `refuse:` row in
   `test_formal_x86_64_parity.py`'s `REFUSALS` if the answer is (a), with the
   needle naming the frame rather than the slot; or as a positive row with the
   CPython oracle beside it if the answer is (b).