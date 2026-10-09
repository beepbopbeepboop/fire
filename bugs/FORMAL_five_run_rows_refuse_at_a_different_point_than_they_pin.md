# Five `test_formal_run.py` rows are red on `master`, and three of the five refuse at a DIFFERENT point than the row pins

**Area:** `test_formal_run.py` — `COMPTIME_BINDING_CASES` (rows 1–3) and
`ORIGIN_OF_CASES` / the wide-receiver group (rows 4–5). **Found 2026-10-05 on
`work/merge-formal44`** while running the narrow `test_formal_*.py` files for a
four-branch merge · **pre-existing on `master`: measured, not inferred** (see
"Reproducing") · **arm64 and x86-64 both, and the two architectures AGREE in
every one of the five**, so none of this is a backend divergence.

It is filed because the shape is the one this corpus keeps meeting from the other
side: **three rows pin WHICH refusal fires and the tree now refuses earlier, and
two rows pin that a construct with no representation must not build and it
does.** Both are honest rows — a refusal that moved is a real change and a
refusal that disappeared is a real change — and neither is recorded anywhere.
`test_formal_run.py` is the `formal-run` job in the **`proofs` bucket, which is
in neither `check` nor `gate`**, so these have been red with nothing watching.
The precedent for how they surface is `test_formal_call_proof_gen.py`'s
`TestTheZeroDivisorGuardAgainstLean` (3 red, owned by
`FORMAL_a_division_by_a_symbolic_value_leaves_the_zero_guard_open.md`): also an
ungated bucket, also red, also needing a reader to go and look.


**Status 2026-10-06 (`work/formal94-docs`): the five rows are REPAIRED to pin
what each program actually does today, the fold question is ANSWERED, and one
newly-found defect is filed separately.**

* **Row 1 (`comptime_binding...parameter`).** The two-call-site question is
  now answerable and the answer is: **the fold reads the instantiation, and it
  is sound.** A program with two `Box` instantiations in one image, each read
  through its instance, answers per-instantiation (`len=3 4` on arm64 and
  x86-64, where CPython's own reading of the source is the same); one
  instantiation answers CPython's `3`. Two `b.size()` calls on two
  instantiations in ONE `main` still refuse (`'size' is not one of those
  methods of those receivers`), so the measurement uses attribute access.
  The row becomes
  `comptime_binding_reading_a_struct_parameter_now_folds_the_instantiation`
  (expects `len=3`) plus a guard
  `comptime_len_of_a_parameter_reads_each_instantiation_distinctly` (`len=3 4`).
* **Row 2 (variadic).** The comptime-over-variadic arm is **unreachable**:
  with any actual construction of a variadic struct the tuple-index refusal
  fires first, and without a construction the comptime binding is never
  read. The row now pins the tuple-index refusal under the name
  `comptime_binding_reading_a_variadic_parameter_is_unreachable_behind_the_tuple_index_refusal`.
* **Row 3 (control).** The claimed control — bare `Box.length` from a free
  function with a LITERAL class binding — **no longer builds** (the no-home
  refusal fires), so the row's comment was false. The control now reads the
  constant through the instance and still prints `3`.
* **Row 4 (`origin_of...`).** The annotation is NOT the live defect: the
  program is refused at the BINDING — a generic struct's construction with
  inferred type arguments (or an annotated local) loses its binding home on
  both architectures. The row pins the actual refusal
  (`nothing this image can see about 'm'`) and the defect is filed as
  `bugs/FORMAL_generic_local_binding_has_no_home.md`. With the explicit
  spelling `Marker[Int](b.a)` the same program builds, which is the control
  that says the refusal is about the binding's classification, not the
  annotation.
* **Row 5 (`type_argument_list_on_a_struct_this_unit_declares`).** For an
  instance type argument the container/escape check fires first ("a S
  receiver is stored in a container"), and for the type-name spelling the
  tuple-index refusal fires; no program reaches the explicit-parameter-list
  sentence for this construct any longer. The row pins the actual refusal;
  the explicit-parameter-list message itself is still pinned by
  `type_argument_list_on_a_type_constructor` (`Pointer[Int, s]`), which still
  passes.

Verification: `python3 tools/memslot.py --gb 8 --label t -- python3
test_formal_run.py <the six rows>` → `PASS=79 FAIL=0`. The sweep was NOT
re-run (as before), so any global regression claim still rests on the narrow
suites. The §1 "decide which is sound" question is no longer open; the
§2 bookkeeping below is done. What remains open is the binding-home defect
above.

## 0. What I ran

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py
# formal run: PASS=1139 FAIL=5

# each row on its own, which is how the messages below were read:
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py \
  comptime_binding_reading_a_struct_parameter_is_its_own_refusal
# … and the other four by name; each prints exactly one FAIL and PASS=73 FAIL=1
```

`master` scores `PASS=1137 FAIL=6` on the same tree, the same six minus
`interpolated-census`. **So these five are on `master` and this merge neither
added nor removed one.**

## 1. The two that BUILT where the row says they must not

`COMPTIME_BINDING_CASES` pins two shapes as refusals, because at the class body
there is no instantiation and so no value to read. Both now build:

| row | pinned | measured |
|---|---|---|
| `comptime_binding_reading_a_struct_parameter_is_its_own_refusal` | arm64 refuses, and the refusal must no longer contain `a formal value is one 64-bit word with nowhere to keep a non-literal one` (the `refuse_without:` half, which the row's own comment calls load-bearing) | **rc=0 on both architectures.** The row's own program — `def size(self) -> Int: return Self.length`, `main` returning 0 — builds, runs, exits 0, prints nothing |
| `comptime_binding_reading_a_variadic_parameter_is_its_own_refusal` | arm64 refuses, naming `Self.length reads a \`comptime\` class attribute of Pair, whose value is \`len(Self.values)\` — and what it reads is 'values', a PARAMETER of Pair` | **rc=0 on both architectures**, same program shape (`*values: T`, `len(Self.values)`) |

**And the built answer is RIGHT, which is what makes this a decision rather than
a repair.** Reading the field off an instantiation, on both architectures:

```
struct Box[T: AnyType, keys: List[T]]:
    comptime length = len(keys)
    def size(self) -> Int:
        return Self.length

def main(n):
    var b = Box[Int, [1, 2, 3]]()
    printf("len=%d", b.size())
    return 0
```

    arm64   rc=0  stdout='len=3'
    x86_64  rc=0  stdout='len=3'

`len(keys)` at the class body, with `keys = [1, 2, 3]` at the only call site, is
3, which is what the source says — so something is now reading the instantiation
rather than refusing to. **Whether that is sound is the question, and it is not
answered by one call site.** Two instantiations of `Box` in one `main` are
refused for an unrelated reason (`'size' is not one of those methods of those
receivers`), so the two-call-site experiment cannot be run through this spelling
today; that refusal is what would have to be got out of the way first.

**Next step, row 1.** Decide which of these two is true and then say it in the
row's own comment:

1. **The fold is sound** — it reads the instantiation's argument through the same
   unanimity-over-call-sites table the truthiness and `len()` rows already pin
   (`formal/model.py::_parameter_argument_shape`), so `len(keys)` is the
   instantiation's `len`, and the row's `refuse:` becomes a CPython PAIR with
   `"3"` and `"1 4 0"`-shaped expectations like the `len()` rows. That also
   means the `refuse_without:` clause this row calls load-bearing is now about a
   refusal that does not exist, and it has to be deleted rather than kept as
   decoration.
2. **The fold is not sound** — it is reading a literal from a spelling the class
   body cannot see, which is the fabricated word this whole refusal was written
   for. Then the arm is missing and the two rows go back to refusing.

Measuring (1) needs one program whose two call sites disagree, so the FIRST
sub-task is a way to ask it: a `Box` instantiated with two different list
lengths in one image, or a free function reading `Box.length` per instantiation
with the receiver collapsed. **Do not close either row before that program
exists** — the single-call-site measurement above cannot tell (1) from (2).

**Next step, row 2.** `Pair[Int, 7, 8, 9]()` — the variadic shape the row's own
comment calls "the stdlib's own" — is now refused for the TUPLE BLOB's subscript,
on both architectures:

    Refused rather than computing a plausible flat index, and rather than using
    the tuple blob's own address as the index — that builds, runs, and returns
    an element nobody asked for.

So the `comptime`-over-a-variadic-parameter refusal is now unreachable behind a
tuple refusal, and the row pins a message no program can produce. Either give
the row a program whose variadic parameter is not subscripted (if there is one),
or accept that the variadic arm of this rule has no observable and mark the row
`disabled` with this doc — **not** by widening the needle list, which would let a
row whose subject is gone keep asserting something.

## 2. The three that refuse EARLIER than the row pins

All three are `formal/model.py`'s **"has no home"** family, and in every case the
refusal is identical on arm64 and x86-64.

| row | pinned | the refusal that actually fires |
|---|---|---|
| `comptime_binding_with_a_literal_value_still_builds` (the CONTROL: `comptime length = 3`, read as `Box.length` from a free `show()`, expects exit 0 and `3`) | builds and prints `3` | `build: show: 'Box' has no home: the module-level symbol table is empty for this unit, and the reading function declares no local or parameter by that spelling` |
| `origin_of_in_a_local_type_annotation_is_still_a_type` (a `var m: Marker[origin_of(b)] = Marker(b.a)`, expects exit 7) | exit 7 | the same family, on the one-field struct's base: *nothing this image can see about `'m'`'s binding establishes which, so a store to the field with no home lands in a register the next function reads as its first parameter* |
| `type_argument_list_on_a_struct_this_unit_declares` (expects a refusal naming `compile-time explicit-parameter list`) | arm64 refuses naming `compile-time explicit-parameter list` | arm64 refuses with the frame-has-no-home message instead, so the expected words are absent: *…o the function which created it, so it can only be read, written, copied, or passed as a method's receiver* |

**The interesting one is the third, because it is a refusal REPLACED by a
refusal.** `bugs/FORMAL_wide_receiver_by_reference.md` — which the row's own
message cites — is the design record for the by-reference receiver, and the row
was pinning the refusal that design produces. A no-home refusal is strictly
EARLIER, so whatever the explicit-parameter-list rule was there to stop is now
stopped by a different rule, and **the row can no longer see the construct it
watches.** That is the same class as a `reject=` regex over a child that prints
nothing, and the same class as `--dump` writing an empty `.ci`: the instrument
went quiet without the thing changing.

**Next step, all three.** Each is one line of bookkeeping plus one measurement,
and the measurement is the same question: **is the no-home refusal CORRECT for
these programs, or is it a name that merely has not been given a home?**

* For `comptime_binding_with_a_literal_value_still_builds`: `Box.length` read
  from a free function is a class attribute of a GENERIC struct, and "the
  module-level symbol table is empty for this unit" is a true statement about
  the erasure this path performs. If the fold now produces `3` for
  `comptime length = 3`, the read has an answer and the refusal is stale →
  rewrite the expectation to `("3")` and say the generic-struct class attribute
  is folded per instantiation. If it has no answer, the row is a REAL refusal
  and its comment's claim ("the same class body with a LITERAL builds, runs, and
  prints the constant") is false on this tree and must be corrected.
* For `origin_of_in_a_local_type_annotation_is_still_a_type`: the row exists to
  say a type ANNOTATION is not a run-time expression. The no-home refusal is
  about `Marker(b.a)`'s BASE, not about the annotation, so the row is no longer
  evidence about its subject. Either give it a `Marker` whose base has a home
  (a local `var s = Marker(...)` first) or re-point it at the annotation being
  dropped; **as written it can no longer fail for the reason it documents.**
* For `type_argument_list_on_a_struct_this_unit_declares`: find a spelling of
  "type-argument list on a struct this unit declares" that gets PAST the
  no-home rule, and pin that. Until one exists the row is a hole, and the
  `wide_receiver_by_reference` design's refusal has no test.

## 3. Why it is not fixed here

This merge touched `test_formal_run.py` only to resolve a conflict, and its claim
is `merge:formal44`. Two of the five are in `formal/model.py`'s
class-attribute/`origin_of` families and three are in the wide-receiver
family — both of which have live claims (`FORMAL_wide_receiver_by_reference.md`
is held by `formal42-1`), so "rewrite the expectation" is a decision for the
owner of that rule and not a line for a merger to take. The measurements are
above so that none of it has to be re-derived: every refusal is quoted whole,
both architectures were run, and the two that BUILD were run and their answers
compared with what the source says.

## Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py
# formal run: PASS=1139 FAIL=5

# each row alone prints its whole message and PASS=73 FAIL=1:
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py \
  comptime_binding_reading_a_struct_parameter_is_its_own_refusal \
  comptime_binding_reading_a_variadic_parameter_is_its_own_refusal \
  comptime_binding_with_a_literal_value_still_builds \
  origin_of_in_a_local_type_annotation_is_still_a_type \
  type_argument_list_on_a_struct_this_unit_declares

# and the two that build, RUN, on both architectures — `len=3` is CPython's answer:
python3 - <<'PY'
import os, subprocess, sys, tempfile
sys.path.insert(0, '.')
import test_formal_run as T
src = ("struct Box[T: AnyType, keys: List[T]]:\n"
       "    comptime length = len(keys)\n"
       "\n"
       "    def size(self) -> Int:\n"
       "        return Self.length\n"
       "\n"
       "def main(n):\n"
       "    var b = Box[Int, [1, 2, 3]]()\n"
       "    printf(\"len=%d\", b.size())\n"
       "    return 0\n")
td = tempfile.mkdtemp(prefix='reds-')
p = os.path.join(td, 'box.mojo'); open(p, 'w').write(src)
for backend in ('arm64', 'x86_64'):
    out = os.path.join(td, 'box.' + backend)
    rc, text = T.build_formal(p, out, backend=backend)
    print(backend, 'build rc=', rc, text.strip()[-200:] if rc else '')
    if not rc:
        argv = [out] if backend == 'arm64' else ['arch', '-x86_64', out]
        r = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        print('   run exit=', r.returncode, repr(r.stdout))
PY
```
