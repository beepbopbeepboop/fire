# FORMAL_frame_receiver_handoff: who can take a frame address, measured rather than asserted

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
