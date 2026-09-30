# FORMAL_frame_receiver_handoff: who can take a frame address, measured rather than asserted

> **WAVE 8 (H1) — one row of the table below is now WRONG, and it was this
> file's own defect class.** The `len` row reads "refused, soundly: `len(x)`
> reads a length out of an object; a frame address is a pointer to slots", and
> that verdict is right about the CATEGORY and about the wrong question. For a
> user type, `len(x)` is `x.__len__()` — a method of the receiver's own struct,
> which is row 1's hand-off, and the two spellings now go through one lowering.
> 39 stdlib files moved; §14 has the measurements and the two routes it takes.
> Everything else in the table, and every section below it, stands as written.

Wave 4 (D4). The question this file answers is the one wave 3 left open: of the
three kinds of callee a frame address can be handed to, **which can take it,
and which is refused for a reason that is not operating.**

The short answer, and every clause of it is a measurement below:

| callee | answer | what settles it |
|---|---|---|
| **a method of the receiver's OWN struct, in an IMPORTED module** | **it can — and the refusal was a binding bug in this repository, not a limit** | the callee is compiled into the module's dylib and the manifest did not advertise it; fixed, and the program computes the right answer on both machines |
| **an ADDRESS constructor** (`Pointer`, `UnsafePointer`, `CPointer`) | **it can — the refusal's own reasoning was upside down** | `Pointer` is an *identity* conversion, so the address handed over is the answer; three frames' addresses come out one frame-size apart |
| **a C library entry point that takes the struct's BYTES** (`stat`, `ioctl`, …) | **refused, soundly — but the stated reason was wrong** | the frame block **is** the struct's C layout for a struct of 8-byte fields, measured; what is unestablished is that *this* struct matches *the C library's* declaration of it |
| a value-only builtin (`len`, `isinstance`, `String`, …) | refused, soundly | `len(x)` reads a length out of an object; a frame address is a pointer to slots |
| a genuinely cross-module free function (`discover_closures`, `__get_mvalue_as_litref`) | refused, soundly | there is no definition in hand, whatever the argument |
| a struct CONSTRUCTOR (`R(r)`, `Repeat(x)`, `StringSlice(x)`) | refused, soundly — and it was reported as an *invisible callee*, which is false twice over | `S()` takes no arguments on this path, so a one-argument construction has no lowering at all; verified by lifting the refusal and watching the constructor refuse it by name |
| a non-first argument position | refused, soundly — and "a position whose meaning this path cannot see" was a statement about the analysis in a message a reader takes to be about the program | all three things under it are wrong answers without the check; each was built and run |
| a frame address RETURNED | refused, soundly — and "returned from the function that created it" is **false** for a frame that arrived as a first parameter, which is the larger half of the family | the creator is the caller, and nothing here establishes the caller is still on the stack |

Nothing in this repository newly compiles, and the honest reason is in
"Still open": the binding fix unblocked eleven files to a CPython host import
they were always also blocked by. The work removed a class of *wrong reason*,
turned one unjustified refusal into working code on both machines, and found
one reachable two-backend divergence that had been masked by the refusals it
replaced.

## 1. Case (c) is a binding bug, and it is the largest single thing here

**23 of this repository's 25 "which this module does not compile" hand-off
sites were a method of the receiver's own struct, reached across a module
boundary.** The remaining two were a genuinely cross-module free function
(`discover_closures`, in `formal/build.py`) and a struct constructor
(`Repeat`).

The refusal said the callee *is not compiled*. It **is** compiled. Measured,
on two files differing in nothing but a struct's field count:

```
liba.mojo   struct S: var x, var y   +  def S.get(self)   ->  manifest: helper ONLY
libb.mojo   struct T: var x         +  def T.get(self)   ->  manifest: helper2, T_get
```

Same code path, same `_export_entries` probe — and the probe *does* find
`S.get` in both cases (it is `reflect.collect_exports_src`, and the export SET
was never the thing excluding it). The filter was in
`formal/build.py`'s `_method_exports`:

```python
if not M.struct_fits_one_word(st):
    continue          # refused at lift time, never compiled
```

and **its own comment is the receipt**: "refused at lift time, never compiled"
was true when a multi-field struct had no representation, and stopped being
true the moment wave 3's by-reference receiver landed. A wide struct's method
*is* compiled — its receiver word is the frame's address — so the filter was
dropping the export of code that was sitting in the library, and the importer's
call had no symbol to bind to. The gate in front of it,
`_check_frame_escapes`, then reported the symptom as a layout problem.

**Both halves are fixed**, and the fix needs nothing new: the callee is a
method of the receiver's own struct, and the importer derived that struct's
field list from the very file the dylib was built from (`imported_struct_defs`
parses the same source), so `base + 8k` is computed from the same field list on
both sides of the boundary. That is the by-reference design's own argument,
applied across an image boundary for the first time.

```
struct S:                                  struct S:
    var x: Int64                              var x: Int64
    var y: Int64                              var y: Int64
    def get(self): return self.x*10+self.y     def set_a(self, v): self.a = v

from liba import S                          from liba import S
def main(n):                               def main(n):
    s = S(); s.x = 3; s.y = 4                  s1 = S(); s1.a = 2; s1.b = 9
    return s.get() + helper(1)                 r = s1.set_a(5)
                                              return s1.a*10 + s1.b + r

  36    (the source says 36)                  68    (5, 9 and 9 — a wrong
                                                       address gives 38)
```

Both arm64 and x86-64, both with the write case checked from the **caller's**
side, because the write is what a wrong address would break: `S_set_a` writes
`self.a`, which on the caller's side is the caller's `s1.a`.

**What makes it sound rather than merely possible**, and it is worth being
precise because the alternative reading is that any address can be passed
anywhere:

* the callee is a method of the receiver's **own** struct, so there is one
  field list, not two;
* that field list came from the same source file on both sides;
* a frame address is absolute and the callee's own frames and blobs are below
  every frame the caller owns (`Frame.frame_frames_no_alias`), so neither can
  scribble on the other.

What is **still** refused, and must be: an extern, and a method of a *different*
struct than the receiver's — `_check_method_receiver_types` already refused the
latter, and it covers imported owners too because they are in
`structs_by_name`.

**The residual, stated.** The dylib build has a check for symbols a library
*binds outward* and none for symbols it *advertises inward*: `_formal_exports`
emits a method entry only for a function that is in `ordered`, so the export set
is a subset of the compiled set structurally, but nothing verifies the emitter
produced code for each. Every program in the four sweeps was run, so nothing
reachable in this corpus hits it, and it is a hole in a check rather than a
wrong answer.

## 2. Case (a), the address constructors: the refusal was upside down

`Pointer` sat in `FRAME_VALUE_ONLY_CALLS`, whose text says the callee "wants the
object itself … so what would arrive is the address `Pointer()` would then
dereference as one". For `Pointer` that is the reasoning inverted:
`Pointer` is in `IDENTITY_TYPE_CTORS`, so `type_constructor_kind` answers
`("identity", None)` and the conversion **yields the word it was handed** — and
for a multi-field struct that word is the frame's base address, which is exactly
what a pointer to the object means.

Measured, both machines, three two-field objects in one function:

```
p=1806298976 q=1806298992 r=1806299008   dq=16 dr=32
```

Sixteen and then thirty-two: the frame size. Three consecutive frames, not three
unrelated leftover registers. (A no-op that left a stale register would not
produce a stride equal to the frame size; the earlier draft of this measurement
did exactly that and was discarded for it.)

`FRAME_ADDRESS_CTORS` is **derived** — `IDENTITY_TYPE_CTORS` minus
`STRING_TYPE_CTORS` — not written out, because the question it answers is "does
this callee dereference its argument" and that is what those two tables already
say. A hand-written copy is how the two come apart.

**What it does not make safe is a dereference through the result**, and that is
already refused by name: `DEREFERENCE_METHODS` covers `value`/`unsafe_value`,
and says why in terms a reader can act on. The word that escapes is one nothing
on this path dereferences.

### 2b. Case (a) again: `origin_of`, which has no body to dereference anything

Added 2026-09-30, and it is the same mistake as `Pointer` one step further
out. `origin_of` was in `FRAME_VALUE_ONLY_CALLS`, so the same sentence refused
it: *"it wants the object itself … so what would arrive is the address
`origin_of()` would then dereference as one"*. But `origin_of` is not a callee
this model lowers at all — it is a COMPILE-TIME intrinsic with no body here, so
there is no call to emit and nothing on this path reads the word it names. The
clause that makes the sentence false is the last one, and it is the only one that
mattered: the sentence describes a dereference that does not exist, and its
advice (`origin_of(self.n)`) sends a reader to rewrite a program that is already
correct. **7 stdlib files** were refused this way, and every one of them is in
the shape the corpus actually uses — a TYPE argument,
`Self.IteratorType[origin_of(self)]`, `Pointer[Deque[T], origin_of(self)]` — so
the reader being misled was being misled about a construct that is not even a
runtime expression.

It is now `FRAME_IDENTITY_CALLS`, the first branch of
`frame_receiver_escape_refusal` beside `FRAME_ADDRESS_CTORS`'s, and it is
erased to its operand by `build._rewrite_identity_intrinsic_calls`. **A rewrite
and not an emitter lowering**, for a reason this file's row 1 already states in
another form: the escape analysis reads the AST, so an emitter that lowers the
call leaves `origin_of(s)` standing in the tree the build pass has walked.
Measured, on both machines, with the identity in the emitters: `return
origin_of(s)` builds, runs and returns the frame's own address modulo 256, and
`printf("%d\n", origin_of(s))` prints 1793355120 and exits 0 — the second of
those is the exact failure §13's `FRAME_C_VALUE_CALLS` message cites as its
reason. Three regressions for it are in `test_formal_run.py`
(`ORIGIN_OF_REFUSALS`: the return, the variadic C call, the container), because
the rewrite erases the CALL and not the CHECK.

The identity is not a convenience: `myinterpreter.py` — this project's own
reference for the language — defines `origin_of` as
`lambda x, *args, **kwargs: x`, so there is an oracle for the answer in the tree
rather than a judgement call about it.

## 3. Case (b): the frame layout and the struct's C layout **coincide**, and
## it is measured

The refusal's premise was *"the frame holds the fields at `base + 8k`, which is
not the struct's own layout"*. For a struct whose every field is 8 bytes wide
and 8-aligned, that is **false**, and the program that shows it is four lines:

```python
struct S:
    var a: Int
    var b: Int

def main(n):
    s = S()
    s.a = 0
    s.b = 0
    memset(Pointer(to=s), 65, 16)
    return (s.a == 0x4141414141414141) * 100 + (s.b == 0x4141414141414141)
```

`101` on arm64 and on x86-64. Sixteen bytes written by the C library through a
pointer taken from the frame, and **both slots read back as the sixteen bytes
it wrote**. The frame block is the struct's storage: contiguous from `base`,
field `k` at `base + 8k`, declaration order — which is the C layout of such a
struct. `byref_frame_bytes_are_the_structs_c_layout` is that program.

**So the refusal is still right, and the reason it gives is now a different
one.** The struct `stat`/`ioctl`/`fcntl` knows about is the **C library's own
declaration** of it, with widths and padding from the C headers, and nothing on
this path compares that against the Mojo declaration here. For `struct stat` the
comparison is not merely absent, it is **impossible on this host**: the corpus
file is `std/os/_linux_aarch64.mojo` and this is a Mac. The coincidence is
per-struct and unestablished, and that — rather than a claim about the frame
layout — is what the message now says.

## 4. Three refusals that named a cause which was not operating

Rule 4 of the wave-4 brief: a refusal for a reason that is not actually
operating is a defect, because it sends the next reader after a non-bug and
inflates the sweep's finding count. Three were found, and all three were
**refusals that stand** — the messages were wrong, not the verdicts.

### 4a. "A position whose meaning this path cannot see"

A statement about the analysis, in a message a reader takes to be a statement
about the program. It is also three different things, and all three are wrong
answers without the check — built and run, one check removed:

| the program | what it built and returned | what is actually wrong |
|---|---|---|
| `take(1, r).a` where `def take(x, y): return y` | **0**, source says 7 | the callee's non-first parameter is not a frame HOLDER, so a field read through it misses every slot table |
| the same shape with the creator one frame deeper | **10**, source says 7 | the frame's bytes are gone |
| `printf("val=%d\n", r)` | the frame's ADDRESS as a decimal, exit 0 | a wrong CATEGORY of argument: `printf` is variadic and reads the word by the format's conversion |

The rule is the right one and the message now says so, with the measurement in
it. One sub-case is worth recording because it is what makes the rule *look*
wrong: **`w.emit(s)` is rewritten to `W_emit(w, s)`, whose FIRST parameter is
the receiver**, so `s` is the method's second parameter and is correctly not
followed. A reader who expects "first argument = first parameter" will read the
refusal as a bug until they know that.

A fourth sub-shape — a method call the rewriting did not lift, so there is no
callee name at all — was reported as "a call whose callee this path does not
recognise", which sends the reader looking for a missing function. It now names
the method and says the two reasons nothing is followed: dispatch is by NAME off
a receiver that is not a frame, and the method-call rewriting runs before any
frame analysis exists. Six stdlib files.

### 4b. "Returned from the function that created it"

False for a frame that arrived as a first parameter, and **that is the larger
half of the family**: the holder fixpoint makes a callee's first parameter a
holder, so `def fwd(r): return r` in a program whose object `main` built was
reported as returning from the creator. The reader is sent to `fwd` for a
construction that is in `main`. The refusal is right — nothing here establishes
the creator is still on the stack, and the measured cost of getting it wrong is
returning 10 where the source says 7 — and it now distinguishes *created here*,
*received by a plain function* and *received as a method's receiver*.

### 4c. A struct CONSTRUCTOR reported as an invisible callee

`R(r)`, `Repeat(x)`, `StringSlice(x)`, `ElementFn(x)`,
`_DeviceGraphBuilderEnqueuer(x)`, `IdentExpr(x)`. "Which this module does not
compile" is false **twice over**: the struct is declared in the very file being
compiled — it is the only reason the argument is a frame address at all — and a
struct is not a function, so there was never a body to compile.

The limit is real and is one level down, and it already has a diagnostic of its
own: `S()` takes no arguments on this path, so a one-argument construction has
no lowering whatever it is handed. Verified by lifting this refusal and
watching the call arrive at `_emit_struct_constructor`:

```
build: R(...) takes no arguments on this path: a struct is default-initialized
and its fields assigned, and a 1-argument construction is not a shape this
backend can honour
```

A copy construction wants a **fresh block and a field-by-field copy into it**.
That is a feature, not a binding, and the message now says so.

**One measured miss while fixing this**, recorded because it is the kind of
thing a "looks right" argument gets wrong: the first version of the constructor
branch fired on `Pointer`, because `Pointer` is *also* a struct some files
declare. `std/os/_macos.mojo` was then reported as a copy construction — a
strictly worse message than the one it replaced, about a construct the source
does not contain. The guard is `type_constructor_kind(callee) is None`, the
model's own test, so a name added to the type-constructor tables is classified
correctly without this file being told.

### 4d. A name the model knows and cannot represent

`Error(frame)` — `std/benchmark/bencher.mojo`'s only frame finding. `Error` is
in `UNREPRESENTABLE_TYPE_CTORS`: a real type, no representation, one word is
all a value is. It was reported as "a name this module does not compile",
which is false a third time over. Same for `SIMD`, `Span`, `Optional`,
`StringRef`.

## 5. A two-backend divergence the refusals were masking

`Pointer(to=x)` is spelled with a **keyword**. arm64's `_emit_type_constructor`
has always accepted a keyword-named operand — its own comment says refusing
every keyword form "blocked 78 stdlib files on a shape the language allows" —
and x86-64's read `e.args` alone:

```
$ Pointer(to=t) - t        # a ONE-field struct: no frame anywhere
arm64    Built
x86_64   build: Pointer(...) takes exactly one value to convert on this path (got 0 argument(s))
```

Pre-existing, with no receiver involved, and harmless until this change made it
*reachable*: the frame analysis used to refuse the file on both machines before
either emitter was reached. `operands = list(e.args) + [v for _n, v in
(e.kwargs or [])]` on x86-64, matching arm64, with arm64's comment as the
justification. The arity refusal stays for a genuine mismatch.

## Still open after wave 4 (D4)

* **Nothing in this repository newly compiles, and the reason is not the
  binding.** Eleven repo files (and eleven stdlib-scope ones) moved
  `codegen → not-answerable/host-import`: the hand-off is now accepted and the
  next fact is that the file imports `os`/`sys`/`re`, which no backend here can
  reach. That moves eleven files OUT of the measured denominator without making
  them answerable, which is the one direction of denominator drift that
  flatters a number — repo coverage reads 80/120 = 66.7% against a baseline of
  80/131 = 61.1%, and **the 61.1% is the honest figure.** Called out here
  rather than left in a table.
* **A frame address in a non-first parameter is refused, and following it is
  implementable.** The fixpoint already follows the first parameter; extending
  it to every position would make `take(1, r).a` compute 7. It is not a small
  change: the callee's own escape check would then fire on `return y` inside
  the callee, which needs the "returned from a function that did not create it"
  wording this change introduces, and the lifetime reasoning has to be
  re-derived for a parameter the callee did not receive from its caller.
* **`S(x)` — a copy construction — has no lowering**, for any struct and any
  argument. A fresh block plus an `n`-slot copy is a feature in both backends.
* **A hand-off to a method of a DIFFERENT imported struct** is refused by
  `_check_method_receiver_types`, which covers it. Nothing measured here says
  the wrong-struct case across a module boundary is reachable; it is covered
  because the owner is in `structs_by_name`, not because it was tested.
* **`reflect.collect_exports_src` crashes on two files in this repository** —
  `gimple_codegen.py` and `fire_compiler.py`, with
  `AttributeError: 'AssignStmt' object has no attribute 'name'` from
  `_struct_layout_sig`, on a field declaration that is an `AssignStmt` rather
  than a `VarDecl`. Not this lane's file, and it is the reason the
  `GimpleGen_gen_module` files cannot be built here even now: the import chain
  dies in the export probe before any codegen. **A real bug, found and not
  fixed** — see below.
* **The string sub-family is unchanged at 20 files** and is not a hand-off
  problem. Six are a `String` frame RETURNED and eight are one in a
  non-first position; both are the same representation collision
  `bugs/FORMAL_string_value_model.md` names — a `String` local is a three-slot
  frame under the lifetime analysis and a `char *` under the method lowering —
  and D2's field derivation is the next step, not this one. Two of the twenty
  are now diagnosed better as a side effect (`Error()` as an unrepresentable
  type, `StringSlice()` as a copy construction).

## Found, deliberately NOT fixed

* **`reflect.collect_exports_src` raises `AttributeError` on
  `gimple_codegen.py` and `fire_compiler.py`.** `reflect.py` is not in this
  lane, `reflect` imports `gimple_codegen` and this path must never pull the
  gimple engine in, and five agents share the tree. The next step is one line in
  `_struct_layout_sig` (`formal/../reflect.py:108`): a field whose body is an
  `AssignStmt` has to be read as `target`/`value` rather than `name`, or
  skipped. Measured, and it is a crash rather than a wrong answer, so nothing
  is silently wrong today.
* **A dylib advertises exports without checking the emitter produced them.**
  The export set is structurally a subset of the compiled set
  (`_formal_exports` emits only for `fn in ordered`), but there is no `nm`-style
  verification on the formal path the way `build_stdlib_dylib.py` has for the
  gimple one. A method that is lifted and then dropped by the emitter would
  advertise a symbol nothing defines.
* **`__get_mvalue_as_litref`** (five stdlib files) is a comptime reflection
  intrinsic with no representation on this path. The new message says "a name
  with no definition in hand", which is true and unhelpful; the useful message
  would name it as a compile-time intrinsic, which is a model change.
* **`getattr`/`setattr` and the other host builtins** reach the same "no
  definition in hand" branch. Correct, and the same fix as above.

## Verification

Judged by the `detail` text, not the class label — C1's classifier is in flux
and 22 files moved class in this change for reasons that are not changes in
what the backend can do.

| command | baseline (wave 3/4) | after |
|---|---|---|
| `python3 test_formal_run.py` | `PASS=146 FAIL=0` | **`PASS=158 FAIL=0`** (12 added; 10 fail pre-change, 2 are labelled guards) |
| `python3 test_formal.py -j 18` | `PASS=40 KNOWN-GAP=3 FAIL=0` | unchanged |
| `python3 test_formal.py --backend x86_64 -j 18` | `PASS=43 KNOWN-GAP=0 FAIL=0` | unchanged |
| `python3 test_formal_dylib.py` | `PASS=11 FAIL=0` | unchanged |
| `python3 test_formal_imports.py` | `PASS=24 FAIL=0` | unchanged |
| `python3 test_formal_sweep.py` | `55 tests, OK` | unchanged |
| `python3 formal/x86_64_model_test.py` | `agree 43 WRONG 0` | `agree 43 WRONG 0 NO-RUN 0 build-fail 0` |
| `python3 test_suite.py` | `43 passed, 0 failed` | unchanged |
| `python3 tools/suite.py check` | `7 passed, 0 failed` | `7 passed, 0 failed` |
| `stdlib-dylib` | skip count 0 | **skip count 0** |
| `compile_stdlib.py -j 18` | `FAILED: 0 (0 expected, 0 unexpected)` | **`FAILED: 0 (0 expected, 0 unexpected)`** — `U` is zero and did not move |
| `formal_sweep --no-stdlib` arm64 | 284 files, `PASS=80`, coverage 80/131 = 61.1% | 284 files, **`PASS=80`**, coverage 80/120 = 66.7% — **11 class moves, all `codegen → not-answerable/host-import`**, 0 gained, 0 lost |
| `formal_sweep --no-stdlib --arch x86-64` | 284 files, `PASS=79`, 0 of 204 differing | 284 files, **`PASS=79`**, **0 of 204 shared files differ in detail text** |
| `formal_sweep` (DEFAULT) arm64 | 578 files, `PASS=105`, coverage 105/414 = 25.4% | 578 files, **`PASS=105`**, coverage 105/403 = 26.1%; 0 gained, 0 lost; 22 class moves (11 → host-import, 11 → `codegen/dependency`) |
| `formal_sweep --arch x86-64` (DEFAULT) | 578 files, `PASS=103`, 92 of 473 differing | 578 files, **`PASS=103`**, 95 of 470 differing — **0 of the 95 touch a message from this change**; all are the pre-existing `ComptimeIfStmt` / `ComptimeForStmt` / `SubscriptExpr` / `EllipsisLiteral` / unary-`^` x86-64 gaps |

**Zero files gained and zero files lost a PASS, in either scope and on either
architecture.** The two class-move directions are both reported above: 22
files left the `codegen` denominator without becoming answerable, which is the
direction of drift that flatters a number.

### The twelve new cases, and which ten fail before the change

`/tmp/d4base` is this tree as it stood when wave 4 (D4) started — D1's, D2's and
D3's work landed, none of D4's — with this change's `test_formal_run.py`
dropped in. `PASS=2 FAIL=10`.

| case | pre-change | why |
|---|---|---|
| `byref_pointer_to_a_frame_is_the_address` | FAIL — refused | the `Pointer` refusal |
| `byref_frame_bytes_are_the_structs_c_layout` | FAIL — refused | the same, and it is also the x86-64 kwarg gap |
| `byref_copy_construction_names_the_struct` | FAIL — different words | "which this module does not compile" |
| `byref_refuse_nonfirst_position_names_it` | FAIL — different words | "a position whose meaning this path cannot see" |
| `byref_refuse_c_entry_point_in_a_position` | FAIL — different words | same |
| `byref_refuse_returned_from_a_receiver` | FAIL — different words | "from the function that created it" |
| `byref_refuse_returned_from_a_method_receiver` | FAIL — different words | same |
| `byref_refuse_unrepresentable_type_constructor` | FAIL — different words | "which this module does not compile" |
| `byref_cross_module_wide_receiver_reads` | FAIL — refused | the export filter |
| `byref_cross_module_wide_receiver_writes` | FAIL — refused | the same |
| `byref_pointer_to_a_list_is_still_the_identity` | **PASS — GUARD** | `Pointer(to=l)` on a list has always been the identity |
| `byref_cross_module_one_field_receiver` | **PASS — GUARD** | a one-field struct's method has always crossed the boundary |

The two guards are labelled as guards and are not demonstrations. They exist
because the rules they cover have a side where they already worked, and a fix
that broke that side would otherwise pass every demonstration above.

---

# Wave 5 (E3): the position family, split in three — and the wrong answer that
# was at the FIRST position the whole time

D4's "Still open" named this one precisely:

> **A frame address in a non-first parameter is implementable** — extend the
> fixpoint to every position and `take(1, r).a` computes 7. **Not small:** the
> callee's own escape check then fires on `return y` inside the callee, which
> needs the "did not create it" wording this change introduces, plus
> re-derived lifetime reasoning for a parameter the callee did not receive from
> its caller.

Both halves of that are now done, and the finding that reorganised the work is
not the one the note was about.

## 6. The finding: the first position was never sound either

Before touching the position rule, the lifetime reasoning D4 asks for was
re-derived — and it does not hold at index 0 today, in the shipped tree, with
no check lifted:

```
struct R: var a: Int; var b: Int
def f(x: Int, y: Int) -> Int: return x.a
def main(n: Int) -> Int:
    var r = R(); r.a = 7; r.b = 8
    return f(r, 1) + f(2, 3)
```

**Built, ran, and died with SIGSEGV (exit 139), on both architectures.**  `f` is
compiled with `x` a frame holder because one call site hands it a frame
address; `f(2, 3)` arrives with `x = 2`, and `x.a` is a load eight bytes from
wherever 2 points.

A parameter's being a frame holder is a property of **the whole image at once**,
and the fixpoint only ever asked one call site. So the rule the position family
was written about — "a frame only works as the first parameter" — was never the
thing that was wrong. The rule is **"a frame works at any position, and every
call site has to agree about it."**

Two more measured holes in the same family, both reachable today with nothing
lifted, both found while establishing the premise the extension depends on:

| program | arm64 | x86-64 | what it is |
|---|---|---|---|
| `var q = [1,2,3]; q[0] = r; return q[0].a` | **0** | **0** | a subscript store; the element is a heap cell, so the address outlives the frame — and it exits 0 |
| `G = x` in a callee, `return G.a` in the caller | **10** | **0** | a module-level write; see §9, which is why this one is *not* refused |

The subscript store is now refused. The module-level write is not, and §9 says
why refusing it would be a refusal for a reason that is not operating.

## 7. The three-way split, and which of the 33 files falls in each

The brief's number was 40 (32 stdlib + 8 repo). Measured on the baselines named
in it: **the family is 33 files, not 40** — 8 in the repo scope and 25 in the
DEFAULT scope, of which 7 are the same repo files. D4's own table already said
"all three are wrong answers without the check"; the arithmetic in the brief is
loose. Nothing else about the brief's description was loose.

| case | verdict | files |
|---|---|---|
| **1. a parameter that IS a holder, in any position** | **IMPLEMENTED** | all 7 in-image position files + 20 in-image method-call files moved to their next blocker; see the table below |
| **2. a variadic position** | refused, with the *variadic* reason | 0 of the corpus reached it — it was unreachable before, because the old loop only asked the value question at index 0 |
| **3. a genuinely opaque position** | refused, marked as a limit of the analysis | 21 (the 20 method-call-on-a-value-receiver files + the 1 cross-module non-first) |

Per file, on the two baselines (`/tmp/s6_arm64.txt`, `/tmp/s6_stdlib.txt`):

| file | before | after | case |
|---|---|---|---|
| `detect_real_type_errors.py` | position 1 of 5 | **opaque** — the callee is compiled into an imported module | 3 |
| `test_type_system.py` | position 2 of 4 | **opaque** — same | 3 |
| `module_loader.py` | position 3 of 5 | **disagreement** in `ModuleLoader_load_module` (§8) | 1→new |
| `mojo/middle/solvers.py` | position 1 of 4 | next blocker (a field of a field) | 1 |
| `fire_compiler.py` | position 1 of 2 | next blocker (a receiver returned) | 1 |
| `tools/suite.py` | position 2 of 3 | next blocker | 1 |
| `ownership_destruct.py` | position 1 of 4 | **host-import** — the position refusal is gone and the real blocker surfaces | 1 |
| `gimple_codegen.py` | method call, no callee name | opaque, now naming the method and the position | 3 |
| `base64.mojo` | position 1 of 2 | `_b64encode` is **imported** — "no definition in hand", which is true | 3 |
| `interval.mojo` | position 2 of 6 | same (`debug_assert` is not this module's) | 3 |
| `string/format.mojo` | position 1 of 4 | opaque method call | 3 |
| `string/string.mojo` | position 1 of 2 | `String()` is a value-only constructor | 2-class |
| `numpy.mojo` | position 2 of 3 | **class move** `codegen → codegen/dependency` | 1 |
| `philox.mojo` | (was dependency) | **class move** `codegen/dependency → codegen`, now a *disagreement* | 1 |
| 20 more (`debug_assert`, `format_int`, `simd`, `string_literal`, …) | "a position whose meaning this path cannot see" | opaque, naming the callee and the position | 3 |

**Zero files gained a PASS and zero lost one**, in either scope, on either
architecture — see §10.

## 8. The lifetime argument, stated once, and what it does and does not licence

> A frame belongs to the function that created it, and reclaimed when that
> function returns. An address only ever travels **down an active call chain**:
> it is created in some activation, passed as an argument to a callee nested
> inside it, and passed on only to callees nested inside that one. So the
> creator of a holder that arrived as an argument is an **ancestor of the callee**,
> and its bytes are live for every instant of the callee's activation.

From that, the callee may **read and write** through the word. Measured, both
architectures:

```
def take(x: Int, y: Int) -> Int: return y.a * 10 + y.b   # 78, source says 78
def put(x, y, v): y.a = v; return y.a                     # 52, source says 52
```

`put` is the stronger of the two: a read would still come out right if the word
were a *copy* of the frame, but a write through a copy lands in the copy and the
caller's `r.a` would still read 1. Both are pinned with the creator **one frame
deeper** as well (`main` holds no frame in either), which is the case that would
catch a lifetime error rather than a missing slot table.

What the argument does **not** licence is letting the word **leave** the callee.
`return`, a container, a field, a subscript are each refused by name, and the
fixpoint is what makes two of them visible at all: before it, `y` was not a
holder inside `stash`, so the container check had nothing to fire on and the
address went into a list and was read back after its frame was gone.

**D4's literal program, and why it is refused rather than computing 7.**
`def take(x, y): return y` *returns* the address, so `take(1, r).a` is the
RETURN family wearing the position family's clothes. It is now refused by
`frame_return_refusal` with the wording that says what is true — "returned from
a function that did not create it: the address arrived as one of its
parameters". With only the position check lifted it built, ran, and returned
**10 on arm64 and 0 on x86-64** where the source says 7: a use-after-free, and
the two architectures disagreeing about what the reused bytes held. The
implementable form of the same idea is `def take(x, y): return y.a`, and that one
computes 78.

**Lifting the return refusal for a received holder is sound, and is not done
here.** The §8 argument says the creator is always an ancestor of the *caller*,
so handing the address back to the caller is safe, and each channel that would
let it outlive the creator is refused. What stops it is that the argument is
about the whole image and two of the channels it leans on are not yet refusals
(§9), and rule 4 of the wave-5 brief is explicit: *"the callee can read it but
must not outlive it."* The next step is named in §11.

## 9. Found, deliberately NOT fixed: module-level names are not module-level

`G = 5` at module level, read from a function, returns **10 on arm64 and 0 on
x86-64** where the source says 5. Three shapes measured, all the same answer:
a plain module-level `G = 5`; `f()` doing `G = 5` and `main` doing `return G`;
and `var H = 5` in `f`, `return H` in `main`.

This is **not a frame problem**, and it is why the frame analysis must not
touch it. `_load_var` falls back to X19 for a name it does not recognise as a
local, so a name written in one function and read in another is not shared
storage — it is two unrelated registers. And **a name that is only ever
introduced by `x = …` is indistinguishable from a module-level one**, so any
refusal keyed on "not a local of this function" would refuse correct code: it
would call `g = r` in `main` a global store. That is a refusal for a reason
that is not operating, which is the defect this whole file is about.

The next step is a module-level symbol table published by
`_prepare_functions` and read by **both** backends' local collection, so that a
name declared at module level and a local are two different things in the
register allocator. Until then the honest position is that a module-level
binding is a **name-resolution gap, not a frame-lifetime one**, and no frame
refusal should claim to speak for it.

Two repo files hit this in the sweep and are reported with it rather than
refused by it: `module_loader.py`'s `_module_loader = ModuleLoader()` and
`philox.mojo`'s `Random_step(self._rng)`.

## 10. Verification

Judged by the `detail` text, not the class label. The baseline is
`/tmp/e3base`, a copy of this tree as it stood when wave 5 (E3) started, with
E1's, E2's, D1's, D2's, D3's and D4's work landed. **It is not `/tmp/s6_*`**:
E1's `refuse_module_level_mlir_templates` landed after those baselines were
taken and costs `std/builtin/type_aliases.mojo` a PASS, so 105 → 104 is E1's
and not this change's.

| command | baseline (`/tmp/e3base`) | after |
|---|---|---|
| `formal_sweep --no-stdlib` arm64 | 284 files, `PASS=80`, 80/120 = 66.7% | 284 files, **`PASS=80`**, 80/119 = **67.2%** |
| `formal_sweep --no-stdlib --arch x86-64` | 284 files, `PASS=79`, 79/119 = 66.4% | 284 files, **`PASS=79`**, 79/118 = **66.9%**, **0 of 205 shared files differ in detail text** (was 0 of 205) |
| `formal_sweep` (DEFAULT) arm64 | 578 files, `PASS=104`, 104/403 = 25.8% | 578 files, **`PASS=104`**, 104/402 = **25.9%** |
| `formal_sweep --arch x86-64` (DEFAULT) | 578 files, `PASS=102`, 102/403 = 25.4% | 578 files, **`PASS=102`**, 102/402 = **25.4%**, 58 of 474 shared files differ (was **59**) — **0 new** |

**Zero files gained a PASS and zero lost one, on all four axes.** Three class
moves, all this change's, all in the good direction or net-zero:
`ownership_destruct.py` `codegen → not-answerable/host-import` (the position
refusal is fixed and the real blocker surfaces — the file leaves the `codegen`
denominator **without becoming answerable**, which is the direction of drift
that flatters a number, so the coverage percentages above rising by 0.5 points
is *not* a gain); `numpy.mojo` `codegen → codegen/dependency` and
`philox.mojo` `codegen/dependency → codegen`, which cancel.

`not-pass` counts are identical on all four axes: 206/206, 207/207, 476/476,
478/478.

**Byte-identical machine code for a program that already worked**, which is the
standard `CLAUDE.md` sets for a behaviour-preserving change — and the analogue
here, since this path emits Mach-O and not C. `struct Pair` + `def bump(x)`,
pre-change against pre-change-plus-only-this-diff, same output filename:

```
arm64    BYTE-IDENTICAL Mach-O (51056 bytes)
x86_64   BYTE-IDENTICAL Mach-O (51056 bytes)
```

(The first attempt at this reported 124 differing bytes and it was the
**dylib id string**: the output *filename* is embedded in the image, and the two
runs used different names. Worth recording because "124 bytes differ" read like
a codegen change.)

### The suites

| command | result |
|---|---|
| `make check` | **7 passed, 0 failed, 0 skipped** |
| `test_formal_run.py` | **PASS=233 FAIL=1** — 14 added or re-pointed, **12 fail pre-change and 2 are labelled guards**. The one failure is **E4's**, in flight: `over_refusal_zero_arg_string_constructor_is_the_empty_string` has the same source text as in `/tmp/e3base` and only its *expected stdout* changed there (`"len=%d\\n 0"` → `"len=%d\n 0"`); the program prints a literal `\n`. Not this lane. |
| `test_formal_dylib.py` | **PASS=10 FAIL=1** — `default path emits a checked proof`, and it is **E5's**: `lib/ProofLib.lean:4865` does not compile (`Application type mismatch … mem_read_after_write_u64_ne`). The generated proof for `def triple` is **byte-identical** before and after this change and so is the dylib (34736 bytes), which is the receipt that this change did not reach it. |
| `test_formal_imports.py` | **PASS=37 EXPECTED=0 FAIL=0** |
| `test_formal_sweep.py` | **Ran 55 tests … OK** |
| `python3 test_suite.py` | **43 passed, 0 failed** |
| `formal/x86_64_model_test.py` | **agree 43 WRONG 0 NO-RUN 0 build-fail 0** on `/tmp/e3base`; on the working tree it cannot run at all, for E5's `ProofLib.lean` reason above. Reported, not fixed, not waited on. |
| `test_formal.py` / `--backend x86_64` | see the note in the report — blocked on the same `ProofLib.lean` |

### The new cases, and which eleven fail before the change

`/tmp/e3base` with this change's `test_formal_run.py` dropped in: `PASS=2
FAIL=12`. The two that pass before and after are the guards, and both are
labelled as such in the file.

| case | pre-change | why |
|---|---|---|
| `byref_nonfirst_holder_reads_correctly` | FAIL — refused | the position rule |
| `byref_nonfirst_holder_reads_with_creator_one_frame_deeper` | FAIL — refused | the same; the use-after-free guard |
| `byref_nonfirst_holder_writes_through_to_the_caller` | FAIL — refused | the same; a write proves it is the frame and not a copy |
| `byref_refuse_a_received_frame_address_returned` | FAIL — different words | "a position whose meaning this path cannot see" |
| `byref_refuse_a_received_frame_address_stored` | FAIL — different words | the same |
| `byref_refuse_a_variadic_position_as_variadic` | FAIL — different words | the same |
| `byref_refuse_two_call_sites_that_disagree` | **FAIL — it BUILT** | the shipped-tree SIGSEGV |
| `byref_refuse_a_disagreement_in_a_frame_free_caller` | FAIL — different words | the same, from a function holding no frame |
| `byref_refuse_a_frame_address_stored_through_a_subscript` | **FAIL — it BUILT** | returned 0 where the source says 7 |
| `byref_refuse_nonfirst_position_names_it` | FAIL — different words | D4's case, re-pointed at the return refusal that is now what fires |
| `byref_refuse_c_entry_point_in_a_position` | FAIL — different words | D4's case, re-pointed at the variadic reason |
| `byref_address_ctor_is_not_called_variadic` | FAIL — different words | §13: `Pointer()` was called "a C library entry point … variadic", every clause false |
| `byref_refuse_an_opaque_position_as_opaque` | **PASS — GUARD** | the narrow case was already refused; it is here so the split has to keep it narrow |
| `byref_address_ctor_stays_the_identity_in_a_nonfirst_position` | **PASS — GUARD** | `Pointer(to=s)` in a non-first position; it passed before only because the position rule refused the file first, so the exclusion in §13 had to be checked against it |

## 11. The next step, and the proof-side lemma E5 should specify rather than
## me land

**The next code step** is lifting the return refusal for a holder that arrived as
a parameter, which §8 argues is sound. It is gated on two things and both are
named so nobody has to re-derive them:

1. **§9's module-level symbol table.** The argument is "every channel that would
   let the word outlive its creator is refused", and a module-level write is not
   currently one of them. Until it is, lifting the return refusal would let
   `def stash(x, y): G = y` through, and the measured answer to that program is
   10.
2. **A `*args` / `**kwargs` parameter list.** `params` records a flat list of
   names with no `vararg` and no `kwonlyargs`, so a call `f(1, 2, r)` against
   `def f(x, *rest)` is read as three fixed parameters. The fixpoint is safe
   today only because `plist[pos]` on a two-element list cannot reach a third
   index; a real `*args` would make position 1 name a *tuple* of arguments, and
   a frame address inside one is a container store, which is refused by a
   different name. `formal/../fire_compiler.py`'s `FunctionDef` already carries
   `param_has_default`/`param_defaults`, so the same treatment is available.

**The proof-side lemma** (E5's `lib/`, not mine — specified, not landed):

> For a frame holder `h` in function `f` that arrived as parameter `i` of `f`,
> every word at `[h + 8k]` for `k < slot_count(struct(h))` is the same word at
> every instant of `f`'s activation.

Stated over the model `Frame.frame_frames_no_alias` already provides: a frame
address is absolute, and a callee's own frames and blobs are below every frame
the caller owns, so nothing `f` does can scribble on the region the address
names, and nothing the caller does between the call and the return can move it.
The part that is **not** in the model and would have to be added is the
*reachability* half — that the creator is an ancestor of the callee — because
`Frame`'s theorems are about disjointness of two frames at one instant and say
nothing about which activations are live. A caller/callee relation on
`Arm64State` (or a `LiveFrames` set threaded through the step function) is the
honest encoding, and until it exists the disjunction "the frame is live" is not
something the proof can state.

## 12. Where the code is

| what | where |
|---|---|
| the fixpoint edge, every position, keywords by name | `formal/build.py` `_frame_receivers`, with `_frame_argument_slots` |
| the callee-first dispatch (the split) | `formal/build.py` `_check_frame_escapes`, the argument loop |
| the whole-image agreement pass | `formal/build.py` `_check_holder_agreements` |
| the subscript-store channel, recorded not raised | `formal/build.py` `_defer_subscript_escape` + `check_frame_subscript_escapes` |
| the three messages | `formal/model.py` `frame_variadic_refusal`, `frame_opaque_position_refusal`, `frame_holder_disagreement_refusal` |
| `_who` / `_where`, shared by all three | `formal/model.py` |


## 13. Two defects this change found in ITSELF, after the suites were green

Both were found by reading the diff rather than by a test, and both had the
shape the brief calls the worst outcome: **a refusal whose stated reason is
entirely false.** Recorded because the process is the point — the suite was
`PASS=231 FAIL=1` at the moment both were found.

**`Pointer()` was called a C library entry point, and said to be variadic.**
`_callee_wants_a_value` decided "does this callee read its argument as a value"
from `type_constructor_kind`, and `Pointer` is an `identity` type constructor,
so the answer came back yes. But `Pointer` is in `FRAME_ADDRESS_CTORS`:
handing it a frame address is the **answer**, and `frame_receiver_escape_refusal`
returns `None` for it. The `or M.frame_variadic_refusal(...)` that stood behind
it — a second copy of a message the model already owns — caught the `None`:

```
$ Pointer(0, r)
before: a R receiver is passed to Pointer(), a C library entry point, in argument
        position 1 of 2. This is not a question about the position: Pointer() is
        variadic and takes its arguments as values …
after:  Pointer(...) takes exactly one value to convert on this path (got 2 argument(s))
```

Every clause of the "before" is wrong: `Pointer` is not a C entry point, it is
not variadic, and the mechanism actually operating is an arity check. That is
strictly worse than "a position whose meaning this path cannot see", which at
least admitted ignorance. Fixed by excluding `FRAME_ADDRESS_CTORS` first — and
`frame_variadic_refusal` is **deleted**, not repaired: a predicate and the
function that answers it can only agree, so the fallback arm was dead as well as
dangerous, and the surviving message is `frame_receiver_escape_refusal`'s own
`FRAME_C_VALUE_CALLS` branch, which already says the variadic thing.

**The subscript message printed the AST.** `_subscript_chain` spelled the index
with `str(index)`, and a `MemberExpr` has no `__str__`, so
`REGISTRY[s.name] = spec` was reported as

```
is stored through "REGISTRY[MemberExpr(obj=IdentExpr(name='s', line=255, col=9), …)]"
```

A reader sent to a repr has to go and find the source to work out what the
compiler was looking at, which is the entire cost the spelling exists to remove.
Both spellings now go through one `_expr_spelling`, and a shape neither has a
short name for degrades to the same honest placeholder rather than to a repr.

**And a process finding worth more than either.** The subscript refusal was
first written as a fourth branch of `_check_frame_escapes`, which raised it from
`_prepare_functions` — and the sweep immediately showed `mojo/middle/closures.py`
moving `not-answerable/host-import → codegen`. That is the exact defect
`check_frame_field_blob_premises` and `check_construction_shapes` were moved out
to fix, re-introduced by a new branch. The branch now *records* and
`check_frame_subscript_escapes` raises it from the entry points beside the other
two, and `closures.py` is back to its import diagnosis. **A new refusal channel
in this pass is a new responsibility for the ORDER of the checks, not just for
the set of them**, and the sweep is what showed it.

---

# Wave 8 (H1): the `len` row is a refusal for a reason that was not operating

The table at the top has a row reading

> a value-only builtin (`len`, `isinstance`, `String`, …) | refused, soundly |
> `len(x)` reads a length out of an object; a frame address is a pointer to slots

and it is the one row of the eight that this wave had to correct, for the reason
this file exists: the verdict is right about the CATEGORY and about the wrong
QUESTION. A frame is a block of 8-byte slots with no header, so there is no count
in it to read and the number a count-field load produces is the struct's FIRST
FIELD — that part is all true and is still what `model.frame_len_refusal` says.
What is not true is that this is why the program is stopped. For a user type,
Mojo's answer to "how long is this object" is the type's own `__len__`, and a
method of the receiver's **own** struct is row 1's hand-off — the one this file
measures to be sound, on the same evidence, for the same kind of callee.

`len` was in `FRAME_VALUE_ONLY_CALLS` because it is lowered as an operation on a
value. It still is — of a string or a blob. What changed is that a THIRD receiver
kind now reaches it: a frame address whose struct declares a `__len__`, and for
that one `len(x)` is `x.__len__()` and there is nothing to refuse.

## 14. What landed, and the two routes it takes

`len(h)` is rewritten to `Struct___len__(h)` — which is **not a new lowering**.
`h.__len__()` was already rewritten by `_rewrite_method_calls` to
`Struct___len__(h)`, the callee is compiled as an ordinary function taking its
receiver first, and that first parameter is a frame address on both sides of the
call. So the change is the knowledge of WHICH `__len__`, and it is decided once,
in `model.struct_dunder_len_candidates`, and read from two places:

| spelling of the frame address | who rewrites it | how the struct is settled |
|---|---|---|
| a bare name holding a frame | `build._rewrite_len_on_frame_receivers`, after the holder fixpoint and before `_check_frame_escapes` | the name's CANDIDATE list, agree-or-refuse |
| a nested frame `len(h.a)` | `build._rewrite_len_on_nested_frames`, beside the method-call rewrite | `_typed_nested_frame` — the SAME function, so `struct_nested_frame_fields`'s write-once placement list is what makes those bytes live |

Two spellings, one lowering, one decision — which is the point. The two
backends' private copies of the `len` decision is the bug wave 5's
`len_operand_lowering` was written to kill, and adding a third route to the
question would have started it again.

**Where each of them sits in the pass is load-bearing, in opposite directions,
and both are recorded at the call site.** The bare-name rewrite must run BEFORE
`_check_frame_escapes`, or the hand-off check refuses the `len` it is supposed to
stop seeing. The nested rewrite must run AFTER it, and for a different reason:
`h.a` is a FIELD READ, a 64-bit value rather than an address, so
`_refuse_holder_use` never fires on it and `len(h.a)` reaches the emitter either
way. `_typed_nested_frame` answering `_REASSIGNED` there is deliberately NOT
re-raised: the emitter's `model.len_refusal` is already what refuses those
programs, and a refusal raised from `_prepare_functions` is reported INSTEAD of
the import diagnosis — the defect `check_frame_field_blob_premises` and
`check_construction_shapes` were placed outside the wrapper to avoid, and which
cost `mojo/middle/closures.py` its import diagnosis once already (§13).

**One difference from `struct_frame_slot_candidates`, and it is about what the two
facts MEAN.** A field no candidate declares is a missing field and the caller
refuses it as one. A `__len__` no candidate declares is the answer "this type has
no length operator", which is what `len` on a list-free struct means — so
`have == 0` is `(None, (False, rows))` here and a DISAGREEMENT there, and the
test carries an `owners and` guard. Without it, the one-candidate holder whose
struct simply has no `__len__` is reported as two candidates disagreeing, which
is false and is a message about a program that does not have the problem. Caught
by the existing test `byref_refuse_receiver_to_a_builtin` before it was written
down here, which is the only reason it is written down now.

**And a receiverless `__len__` is not one.** `def __len__():` inside a class is a
function that happens to be spelled like a method, and the language gives it no
`self` — the rule `struct_receivers` applies to a field read and
`_receiverless_methods` applies to a call. There is nothing for a frame ADDRESS
to be handed to, so it is refused for the same reason a struct with no `__len__`
at all is, and the refusal says "declares no `__len__`", which is true.

**One dead arm, found by writing the message and then going looking for who
reaches it.** `frame_len_refusal` first took a `declares` flag so it could also
cover "the struct DOES declare a `__len__` and this call site is not a shape the
rewrite takes". There is such a shape — `return len(b, b)`, a wrong-arity `len`
whose operand is a `Bag` frame — and the arm was reachable, and it was **false
in its first clause**: it said "this operand is not a bare name", and the
operand IS the bare name `b`. The real fault is the arity, which the emitter
has its own message for. So the flag and the arm are gone, the hand-off branch
is gated on the rewrite's own condition (one positional argument, no keywords),
and `len(b, b)` falls through to the pre-existing value-only message. A refusal
whose stated reason is entirely false is the worst outcome on this path — §4 of
this file is three examples of it — and the shape is now a labelled case in
`test_formal_frame_len.py` so a future arm cannot be written for it silently.

## 15. The message, which is the half worth keeping

The refusal that remains — a frame address whose struct declares no `__len__` —
used to say "lowered as an operation on a VALUE … a wrong category of argument.
Give it a field (`len(self.n)`) or copy the value out first". Every clause about
the CATEGORY is true and the ADVICE is now wrong for a reader who is about to
add the `__len__`: they are told to change a program that is already correct.
`model.frame_len_refusal` says what the answer to the question is instead, and
names the `__len__` as the alternative. Two existing cases were re-pointed at it
(`byref_refuse_receiver_to_a_builtin`, `guard_len_on_a_frame_address`), and both
are refusals for the OPPOSITE reason to the case that now builds, which is what
makes the pair worth having.

`model.len_refusal`'s own `FRAME_KIND` arm — the emitter's, for an operand the
build pass could not settle to a struct — got the same paragraph, phrased for the
shapes that can still reach it rather than for the one that was the point.

## 16. What it moved, measured on both architectures

The terminal finding this closes was `std/collections/binary_heap.mojo`, whose
`len(self)` four times, and it is the whole `std/collections` subtree's blocker.
Per-file, over 599 files (repo + stdlib `std/`), on arm64 and again on x86-64:

| | arm64 before → after | x86-64 before → after |
|---|---|---|
| PASS | 108 → **108** | 105 → **105** |
| coverage | 108/418 = 25.8% → **108/418 = 25.8%** | 105/416 = 25.2% → **105/416 = 25.2%** |
| files whose reported refusal was the `len` value-only sentence | **42** | **42** |
| files whose CLASS moved | **1** (`_grapheme_break.mojo`, `codegen → codegen/dependency`) | the same one |
| repo scope, 221 non-pass files | — | **0 class moves, PASS 84 → 84, coverage 84/125 both** |

**Zero files gained a PASS and zero lost one, on all four axes**, and the
coverage rates are identical, so nothing here is denominator drift. The one class
move is in the GOOD direction and is the chain working: `_grapheme_break.mojo`'s
own finding WAS a `len` on a `Span` frame, it is now fixed, and the file's next
blocker is in a module it imports (`builtin_slice.mojo`'s `Slice(...)`
construction with arguments). The family tally moves accordingly, which is the
shape a fixed terminal finding is supposed to have:

| family | before | after |
|---|---|---|
| `frame address passed where a value is wanted` | 54 | **15** |
| `construction with arguments needs __init__` | 21 | **22** |
| `receiver passed as an argument` | 23 | **25** |
| `other refusal` | 201 | **237** |

The `+1`, `+2` and `+36` are next blockers becoming VISIBLE, which is the only
way a fixed refusal can move a number in this table.

**The new terminal cause is `List[Self.T]()`, and it is not a codegen gap** — it
is `List` being reported as a name with no home, which is a name-placement
question about a TYPE. Handed over as
`bugs/FORMAL_type_argument_call_base_name_has_no_home.md`, with a
three-line reproducer and the one set to add the subscript base to.

## 17. Where the code is

| what | where |
|---|---|
| which struct's `__len__`, agree-or-refuse | `formal/model.py` `struct_dunder_len_candidates`, with `dunder_len_method` |
| the refusal that remains | `formal/model.py` `frame_len_refusal` |
| the refusal when the candidates disagree | `formal/model.py` `frame_len_candidates_disagree` |
| the bare-name rewrite, and the hand-off check that must stop seeing it | `formal/build.py` `_rewrite_len_on_frame_receivers`, `_check_frame_escapes` |
| the nested rewrite | `formal/build.py` `_rewrite_len_on_nested_frames` |
| the cases | `test_formal_frame_len.py` — 10 differential cases, each compared against CPython running the same program, both architectures built and executed |

The cases are differential rather than a hand-written expected value, which is
the discipline `test_interp_oracle.py` set for the other engine: eight of them
fail on the pre-change tree and two are labelled GUARDs because they are correct
before and after. The four refusals additionally require CPython to raise
`TypeError` on the same program, so what is pinned is that the decision is
RIGHT, not merely that this compiler makes it.
