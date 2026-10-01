# FORMAL_pointer_value_model: what a pointer IS on the formal path, and why the 54-file group was never about that

**Status:** the representation question is DECIDED and the decision is LANDED on
both backends. A pointer stays one 64-bit word; **its pointee is a computation
over its declared static type**, recovered under the same agree-or-refuse rule
wave 4's D2 landed for a struct field, and nothing is stored — no second word,
no header, no tag, no lifetime. With the pointee recovered, `value()` /
`unsafe_value()` on a pointer with a declared pointee is ANSWERED, at the
pointee's own width, and the one-byte `UInt8` load that D1 refused over is the
one this emits.

Two results in this document are worth more than the lowering, and both are
count corrections rather than features:

1. **The 54-file group was never gated on the pointer value model.** All 54 are
   one root module, one line, one method, one pointee type — and with the
   dereference answered they are blocked *one step earlier in the same file*, by
   `external_call['setenv', Int32]`'s tuple subscript at `std/os/env.mojo:42`.
   Zero of the 54 became buildable, and the reason is measured, not argued
   (§3). **Both halves of this are now superseded**: the tuple subscript itself
   was closed on 2026-09-29 (`4ad34f3`), and the 54-file group has moved on to
   `bugs/FORMAL_env_family_next_terminal.md`, which records where it lands.
2. **`DEREFERENCE_METHODS` was a FALSE refusal about 527 of the 528 `value` sites
   in the stdlib.** `value` is spelled the same for an enum's integral value, an
   iterator's current item, a `SIMD`'s scalar and a pointer's pointee; the table
   said "it is a load from the address the receiver holds" for all four. The
   tables are split and the message is now true of every receiver (§5).

---

## 1. The decision, and the reasoning that decides it

A formal value is one 64-bit word. A pointer is one word. So what does a
pointer need beyond that?

**Nothing is stored.** The pointee is a *computation* over the pointer's
declared static type, exactly as a string's length is a computation over a
NUL-terminated `char *`. This is `bugs/FORMAL_string_value_model.md`'s move and
it transfers — with one difference that is the whole of the answer, and it cuts
in the pointer's favour.

The string's argument was that a `{ptr, len}` descriptor has to live somewhere:
a frame (and then it inherits the frame's lifetime, so every `lstrip` result
would be refused for exactly the reason a struct frame address is — losing the
one string method that works today) or a heap (and there is none). **A pointer
value model has no version of that problem, because it stores nothing.** The
pointee is read out of a type the program already wrote, at the point of use.
There is no slot to give a lifetime, so the frame-lifetime trap that
`formal/build.py` spends waves 3–5 on does not arise for a scalar pointee at
all — and §4 is about the one case where it does.

### 1.1 Is there a header to read? No — and this is the difference

The brief asked whether the string outcome transfers, and it asked the right
question: *is there a header?* **Measured: no.** A word on this path can point
at four things, and the four have incompatible layouts with no common header:

| what the word points at | the layout | is there a header |
|---|---|---|
| interned string bytes | `__TEXT,__text`, NUL-terminated, `initprot 0x5` (no write bit) | a NUL — but that gives a LENGTH, not a pointee type |
| a blob (a list) | a frame whose FIRST word is its count | a count — a length, not a type |
| a struct frame | 8-byte slots, layout from the field list | none; the layout IS the header, and it names fields, not a type |
| an extern C object | nothing this path knows | none |

So the string's recovery mechanism — *a runtime invariant every value obeys, so
`strlen` works however the program produced the string* — **has no analogue
here.** The pointee is a STATIC fact about ONE spelling. The answer exists
exactly where a declaration in the same function names it, and D2's own rule
("use a declared type only when EVERY binding of the name agrees; an absent
answer IS the answer") says the refusal is *correct* everywhere else.

**That is the cost, and it is coverage rather than speed or storage.** A pointer
that arrives as a callee argument, out of a frame field through a type the field
does not declare, or out of a container has no recorded pointee, and
`p.value()` on it stays refused. Fourteen of the stdlib's 47 `unsafe_value`
sites are exactly that, and they stay refused. What is bought is that a load is
never emitted at a width the model has not established.

### 1.2 The one place the reasoning does *not* transfer, and it is the load-bearing one

A pointer's pointee **width** is not a style question. D1's second reason for
the refusal was concrete: an 8-byte load over-reads a `UInt8` pointee by seven
bytes, returns a plausible number assembled from adjacent bytes, and can SIGBUS
on a page edge — and `std/os/env.mojo`'s pointer is `_CPointer[UInt8]`, so it is
not hypothetical. With the pointee recovered there is no approximation left to
make: the load is one byte, and one byte is the answer.

### 1.3 What the decision is in the model

`formal/model.py`, read by both backends so the two architectures cannot
disagree about a load's width — which is the failure mode that matters here,
because a disagreement is not a diagnostic that differs but a `movzbl` on one
side and a `movq` on the other over the same bytes:

| name | what it is |
|---|---|
| `POINTER_TYPE_CTORS` | `Pointer`, `UnsafePointer`, `_CPointer`, `CPointer`, `DTypePointer`, `Reference` |
| `POINTEE_WIDTHS` | pointee base name → `(bytes, signed)`. One table, both backends |
| `POINTEES_REFUSED` | float, `SIMD[n>1]`, `List`, `Dict`, `String`, `StringSlice` — refused BY NAME with the reason |
| `pointee_args` | the type arguments of a declared type, keyword arguments dropped |
| `pointee_of_type_text` | `(pointee, why)` for a declared pointer type — the ONE reader |
| `type_expr_text` | renders a type EXPRESSION into the string a declaration spells, so `external_call["getenv", _CPointer[UInt8, …]]` and `var p: Pointer[UInt8]` have one reader |
| `pointer_pointee` | the pointee of a receiver: a name (its bindings), `recv.field` (D2's table), a construction, a `bitcast`, a callee's return annotation |
| `dereference_lowering` | `("load", width, signed)` or `None` + the refusal. The one decision |
| `_offset_scale` | whether every integer offset in the address is scaled by the width (§6) |
| `receiver_declared_is_pointer` | three-valued: is this receiver's declared type a pointer, another type, or undeclared — which message is true |
| `dereference_refusal` | the refusal text, chosen by which question the receiver is |

---

## 2. The distribution, re-derived

Wave 4's D1 counted the sweep. That is the wrong census — the sweep reports
what a *file* is blocked by, not what a construct is. This one walks every
`.mojo` under the stdlib, parses it, and counts `value()` / `unsafe_value()`
call sites by what their receiver is.

**528 sites: 470 `value`, 58 `unsafe_value`** (a site is a `CallExpr` whose
`func` is a `MemberExpr` naming one of the two).

### `value` — 470 sites, ONE of them a dereference

| receiver shape | sites | what `value()` is | example |
|---|---:|---|---|
| a call result | ~90 | the callee's own answer | `gettempdir().value()`, `Codepoint.from_u32(c).value()` |
| a `SIMD` subscript | ~140 | `Scalar[Self.dtype]` — an identity | `v[i].value()` in `test/utils/test_coord.mojo` (×140) |
| a name bound to an enum | ~120 | the enum's integral value | `func_attribute.value()`, `upper.value()` in `test/iter/test_peek.mojo` |
| a name bound to an iterator / interval node | ~80 | the item the iterator holds | `next_back().value()`, `left().value()`, `peek_back().value()` |
| `self` / a frame slot | ~40 | a field | `self.value()`, `self._tail.value()` |
| **a pointer** | **1** | **a load** | **`std/os/env.mojo:85`** |

`simd.mojo:3439` is the citation for the SIMD half: `def value(self) -> Scalar[Self.dtype]`.
`interval.mojo` / `linked_list.mojo` / `string/iterators.mojo` are the iterator
half. Neither is a load from an address.

### `unsafe_value` — 58 sites, two questions under one name

| receiver | sites | what it is |
|---|---:|---|
| `Optional[…]` — `self`, `rhs`, `optional`, `*_opt`, `g`, `loc`, `index`, `ub`, `final_ub`, `a_bounds` | ~33 | an **unwrap** (`UNWRAP_METHODS`' subject), not a dereference |
| a pointer — `ptr`, `pointer`, `ep`, `maybe_ptr`, `self._unsized_obj_ptr`, `copy._inner`, `CurrentPlugin.print_emit_fn` | ~14 | a **load** |
| mixed / other | ~11 | |

So the old table grouped by SPELLING across two opposite questions, which is
precisely what the comment above the receiver-kind list warned against ("a model
that grouped them by spelling would implement one of them as the other"), and
called the union "a dereference". §5 is the split.

---

## 3. The per-file table: 54 files, one sub-shape, and why none of them moved

`/tmp/s7_stdlib.txt` (wave-6 baseline, arm64, default scope) reported **54
sweep lines = 54 distinct paths = 39 distinct basenames** (`__init__.mojo`
appears 13 times, `elementwise.mojo` / `reduction.mojo` / `stencil.mojo` twice
each). Every one:

- class `CODEGEN/DEPENDENCY`;
- terminal module **`std/os/env.mojo`**, all 54;
- the same line, `std/os/env.mojo:85`: `return String(unsafe_from_utf8_ptr=ptr.value())`;
- the same construct, `_CPointer[UInt8, UntrackedOrigin[mut=False]]` declared
  four lines above at `env.mojo:80-82`;
- so exactly one sub-shape: **pointee width KNOWN** (`UInt8`, 1 byte, unsigned).

There are no files in the group with an unknown width, a struct pointee, a blob
pointee or a null pointee. The distribution the brief asked to be re-derived
collapsed to a single row, and that is the finding.

### Why answering it moved zero files

**Measured, not argued.** The dereference was not `env.mojo`'s only problem:

```
$ sed 's/^    return String(unsafe_from_utf8_ptr=ptr.value())/    return default/' \
      std/os/env.mojo > /tmp/env_noderef.mojo     # the dereference DELETED
$ python3 tools/formal_sweep.py -t 300 -j 2 /tmp/env_noderef.mojo
CODEGEN/DEPENDENCY: /tmp/env_noderef.mojo  (build: env_noderef.mojo imports 'std.ffi',
  which cannot be built either: info.mojo: the module-level comptime binding '_TargetType'
  is initialized from an MLIR attribute template …)
```

`env.mojo` imports `std.ffi` → `std.sys` → `info.mojo`, and `info.mojo` is
refused by wave 5's `__mlir_type` template — **family 2 of
`bugs/FORMAL_known_limits.md`, "there is no MLIR in a freestanding image for the
template to become", permanent by construction.** With `ptr.value()` deleted
from the file outright it still fails.

**After the change**, all 54 are still `CODEGEN/DEPENDENCY` and still terminal
at `env.mojo`, one step earlier in the same file:

```
CODEGEN/DEPENDENCY: std/algorithm/backend/cpu/elementwise.mojo  (build: elementwise.mojo
  imports 'std.math', which cannot be built either: env.mojo: external_call['setenv',
  Int32] is a subscript whose index is a tuple. …)
```

That is `env.mojo:42`, not `:85` — a different construct, in the
`is_multi_index` family, and **not** the pointer value model. `grep -c
DEREFERENCE` over the whole stdlib sweep is **0** on both architectures.

> **Superseded 2026-09-29.** `env.mojo:42` is closed (`4ad34f3`; see
> `bugs/FORMAL_known_limits.md` §6.2.1 for why it was never a monomorphization
> problem) and the group has moved on — see
> `bugs/FORMAL_env_family_next_terminal.md` for where. This block is left as
> the record of what the measurement said at the time, which is the only reason
> it is still worth reading.

| | baseline | after |
|---|---:|---:|
| sweep lines reporting the dereference | 54 | **0** |
| of the 54, buildable | 0 | **0** |
| terminal module of the 54 | `env.mojo:85` (the dereference) | `env.mojo:42` (a tuple subscript) |
| a permanent blocker behind `env.mojo` regardless | `info.mojo`'s MLIR template | the same |

**So the group is a COUNT CORRECTION, not 54 files of pointer work, and the
cost of the pointer value model in coverage is zero on this tree.** That is the
honest result and it is recorded here so the next reader does not re-derive it.

### The shape that the model does answer, and the two that break the build

`env.mojo:85` in isolation, with the pointee derived from the declaration four
lines above it — the decision, from the model's own words:

```
>>> M.dereference_lowering(fn, ptr.value_receiver, {}, {}, {})
(('load', 1, False), 'UInt8')
```

A one-byte unsigned load, which is the correct answer and not an approximation
of it. What then stops the *file* is `String(unsafe_from_utf8_ptr=…)`: a
`String` is a three-field struct whose value on this path is a frame address,
and constructing one here is refused. That is
`bugs/FORMAL_string_value_model.md`'s §"NOT the string value model" — the same
16-file family — and it is **not** a pointer question.

---

## 4. The frame-lifetime trap: a pointer to a struct IS a frame address

The brief's third item, checked explicitly. There are two shapes and they come
out opposite ways.

**A `Pointer[scalar]` in a field is SAFE, and it is answerable.** The word is an
address to bytes with static storage duration; it is not a frame address and it
cannot outlive anything. Answered, on both architectures:

```
struct Two:
    var tag: Int64
    var p: Pointer[UInt8]
def read_field(h: Two) -> Int:
    return Int(h.p.value())          # h.p is slot 1
main:  h.p = s;  read_field(h) → 65     ('A', from "ABCDEFGH")
```
pinned by `deref_pointer_in_a_frame_field`.

**A `Pointer[SomeStruct]` is REFUSED, and the derivation says it should not
be.** The derivation is right: a struct's value on this path is a frame
ADDRESS, so the word in the receiver already IS the pointee, exactly as
`Pointer()` is (wave 4's D4) and exactly as a string's length is a computation.
The answer is the identity — no load, no width, no fault. It is refused anyway,
because emitting it **produces a wrong answer today**:

```
struct P3:  var a: Int64 / var b: Int64 / var c: Int64
def f(p: Pointer[P3]) -> Int:  return Int(p.value().b)
main:  t = P3(); t.b = 22;  printf(…, f(t))
     →  0  on arm64 and on x86-64, where the source says 22
```

Reading fields off a frame address is `formal/build.py`'s `_frame_receivers`
job, and it recognises a frame by a CONSTRUCTOR BINDING (`x = A()`) or by being
a callee's first parameter. A name bound from `p.value()` is neither, so the
analysis does not see it and `q.b` falls to the value-member path and reads a
word of nothing.

**So the trap is refused by naming it, and the refusal is the frame-lifetime
one.** A `Pointer[SomeStruct]` *is* a frame address wearing a pointer's clothes:
storing one in a field or returning it hands the caller a pointer into a frame
whose lifetime this pass cannot follow — the same use-after-free
`formal/build.py` already refuses for a struct receiver returned from the
function that created it, and the same one D2 made an enforced invariant for a
blob in a field. **No slot was created that can hold a pointer to a callee's
scratch**; the one case that could have become one is a refusal. Pinned by
`deref_refuse_struct_pointee`, whose message says all of this and names the next
step.

**The next step is one line of recognition, not a value-model change:** teach
the holder fixpoint that a name bound from `p.value()` where `p` is declared
`Pointer[SomeStruct]` of this unit is a holder, with the pointee's struct as its
candidate. Everything downstream — the frame layout, the escape analysis, the
field reads — already exists and already works for a directly constructed
struct. `formal/build.py` is not this change's lane.

---

## 5. The false refusal: `DEREFERENCE_METHODS` split

Before:

```
DEREFERENCE_METHODS = {
  "value": "is a DEREFERENCE on this path, not an identity: it is a load from the
             address the receiver holds, …",
  "unsafe_value": "is the same dereference under a second name … so see value",
}
```

That is **false about 469 of the 470 `value` sites** and conflates an unwrap
with a load for `unsafe_value`. `bugs/FORMAL_known_limits.md` opens with the
rule this breaks: "a claim that is false about a file is worse than no claim".

After, three tables and a three-valued guard:

- **`DEREFERENCE_METHODS`** now holds `unsafe_value` alone, and its message says
  what is true of it — *spelled like two different questions, and this path
  cannot tell them apart*, which is exactly the case for all 58 of its sites.
- **`IDENTITY_VALUE_METHODS`** holds `value`, and its message names the four
  questions behind the one spelling, with the census in it so the count cannot
  rot silently.
- **`DEREFERENCE_TRY_NAMES`** is what a backend intercepts: `DEREFERENCE_METHODS`
  plus `value`. One intercept, one model decision, and the model's answer is
  right for all four receivers — which is what stops a backend from having to
  know in advance which of the four a given `.value()` is. A backend that routed
  `value` straight to a refusal would leave `env.mojo:85` refused; one that
  routed it straight to a load would turn 469 enum, iterator and SIMD sites into
  loads of whatever word the receiver holds.
- **`receiver_declared_is_pointer`** picks the message: a declaration saying a
  pointer gets the dereference text, a declaration saying something else
  (`var status: ProcessState`) or nothing at all gets the four-questions text.
  Three-valued, and all three answers are needed — `False` and `None` are both
  the untyped direction and neither is the pointer one.

Three existing cases in `test_formal_run.py` pinned the old text
(`str_method_unknown_receiver`, `recvkind_value_on_name`,
`recvkind_value_on_frame_slot`); their expectations were changed to
`is spelled the same for four different questions`, which is what the change is.

---

## 6. The `UInt8`-at-a-page-edge demonstration, before and after

The test that matters, and the one D1 named: a `UInt8` pointee at the last byte
of a mapped region. A load that does not fault is not evidence; a load that is
too wide faults, and that is the "before".

**Where the edge is.** A single-page `mmap` is mapped at a granularity LARGER
than a page on this host, so the mapping's true last readable byte is not at
`base+4095`. Measured on arm64, 16 KiB. The C probe below therefore does not
assume a granularity — it scans forward a page at a time until a one-byte read
faults, which locates the edge exactly on either architecture.

### BEFORE — the 8-byte load D1's reasoning had available

```c
/* /tmp/edgeA.c — the control.  clang -O0 -o eAa edgeA.c
 *                                     clang -O0 -arch x86_64 -o eAx edgeA.c */
signal(SIGBUS, h); signal(SIGSEGV, h);
for (off = 0; probe(base + off) >= 0; off += 4096) ;     /* find the real edge */
edge = base + off - 1;
printf("mapping ends at base+%ld  edge=%p\n", off, edge);
sigsetjmp(jb,1)==0 ? printf("ONE-byte  load at the edge = %u   NO FAULT\n", *edge)
                   : printf("ONE-byte  load at the edge   FAULTED\n");
sigsetjmp(jb,1)==0 ? printf("EIGHT-byte load at the edge = %lu  NO FAULT\n",
                            *(unsigned long*)edge)
                   : printf("EIGHT-byte load at the edge   FAULTED (SIGBUS/SIGSEGV)\n");
```

```
$ ./eAa                                    # arm64
arm64  base=0x1023f4000  mapping ends at base+16384  edge=0x1023f7fff  edge is page-aligned=1
ONE-byte  load at the edge = 0   NO FAULT
EIGHT-byte load at the edge   FAULTED (SIGBUS/SIGSEGV caught)  <-- the hazard
exit=0

$ ./eAx                                    # x86-64
x86-64 base=0x10c733000  mapping ends at base+4096  edge=0x10c733fff  edge is page-aligned=1
ONE-byte  load at the edge = 0   NO FAULT
EIGHT-byte load at the edge = 0   NO FAULT          <-- the next page happened to be mapped
```

**arm64: the SIGBUS D1 identified, measured, at a self-located edge, with the
one-byte load at the SAME address succeeding.** x86-64's page after the
mapping was readable that run, so the same program's 8-byte load did not fault;
the x86-64 hazard is measured separately, with a guard page (§6.1).

### AFTER — the one-byte load this change emits, built and run through the compiler

```mojo
/* /tmp/edge_mojo.mojo */
def last_byte(p: Pointer[UInt8], k: Int) -> Int:
    var q = p + k
    return Int(q.value())
def main(n: Int) -> Int:
    var page: Pointer[UInt8] = mmap(0, 4096, 3, 0x1002, -1, 0)
    var k = 16383          # the last readable byte of a 16 KiB mapping (arm64)
    var v = last_byte(page, k)
    printf("edge_byte=%d page=%d\n", v, page)
    return 0
```

```
$ python3 fire.py build --formal --no-prove --backend=arm64 -o /tmp/em_a /tmp/edge_mojo.mojo
Built: /tmp/em_a  [arm64/macho]
$ /tmp/em_a
edge_byte=0 page=16777216
exit=0
```

`mmap` returns a page-aligned address, `p + 16383` is the last readable byte of
the mapping, and a ONE-byte load there returns 0 and **exits 0**. Had the model
chosen the 8-byte width — the only width the pre-change tree could have emitted
— this program would have taken SIGBUS/SIGSEGV at the `LDR X0, [X0]`, because
the C control above faults at exactly that address with exactly that width.

### 6.1 The x86-64 hazard, measured with a guard page

`mprotect` and `MAP_FIXED` are both refused (EINVAL) from an **arm64** process
on this host, and so is `munmap` of the middle of a mapping — which is why the
x86-64 arm of the demonstration needs a different construction:

```
$ ./e8x                                    # x86-64, two pages, second PROT_NONE
x86-64 base=0x108680000 guard=0x108681000
ONE-byte  load at base+4095 = 0   NO FAULT
EIGHT-byte load at base+4095   FAULTED (SIGBUS/SIGSEGV caught)  <-- the hazard

$ ./e6x                                    # and with the middle page unmapped instead
base=0x10abd8000 aligned=1
one-byte  load at base+4095 = 0   NO FAULT
Segmentation fault: 11                   # exit 139
```

**The host restriction is recorded rather than worked around**: the arm64 fault
could not be reproduced through `mprotect`/`MAP_FIXED`/`munmap`, and the arm64
evidence is the self-locating scan above, which needs none of them.

### 6.2 The widths, one address, four reads

The stronger statement, because it reads the SAME address four ways in one
program and asks the four reads to disagree — which a formal value cannot do
unless the width really comes from the pointee's declared type:

```
main:  s = "ABCDEFGH"
       Pointer[UInt8]  →  r1(s) == 65                  struct.unpack('B', …)[0]
       Pointer[UInt16] →  r2(s) == 16961               struct.unpack('<H', …)[0]
       Pointer[Int32]  →  r4(s) == 1145258561          struct.unpack('<i', …)[0]
       Pointer[Int64]  →  r8(s) == 5208208757389214273 struct.unpack('<q', …)[0]
       → return 1        exit 1, on BOTH architectures
```
pinned by `deref_four_widths_at_one_address`.

**One program, every width, both architectures, byte-identical output** — the
`edge` column is the mapping's last readable byte (16 KiB granularity on arm64,
one page on x86-64, both measured), and the 8-byte read is COMPARED rather than
printed for the reason the next item gives:

```mojo
struct Two:
    var tag: Int64
    var p: Pointer[UInt8]
def r1(p: Pointer[UInt8])   -> Int:  return Int(p.value())
def r2(p: Pointer[UInt16])  -> Int:  return Int(p.value())
def r4(p: Pointer[Int32])   -> Int:  return Int(p.unsafe_value())
def r8(p: Pointer[Int64])   -> Int:  return Int(p.value())
def rs(p: Pointer[Int8])    -> Int:  return Int(p.value())
def rat(p: Pointer[UInt8], k: Int) -> Int:
    var q = p + k
    return Int(q.value())
def rfield(h: Two)          -> Int:  return Int(h.p.value())
def redge(p: Pointer[UInt8], k: Int) -> Int:
    var q = p + k
    return Int(q.value())
def main(n: Int) -> Int:
    var s = "ABCDEFGH"
    var k = 16383
#if defined(__x86_64__)
    k = 4095
#endif
    var page: Pointer[UInt8] = mmap(0, 4096, 3, 0x1002, -1, 0)
    var h = Two()
    h.tag = 1
    h.p = s
    printf("u8=%d u16=%d i32=%d\n", r1(s), r2(s), r4(s))
    printf("i8=%d at3=%d field=%d edge=%d\n", rs(s), rat(s, 3), rfield(h),
           redge(page, k))
    if r8(s) != 5208208757389214273:
        return 90
    printf("i64 compared OK (printf %%d narrows a word to 32 bits; pre-existing)\n")
    return 1
```

```
$ python3 fire.py build --formal --no-prove --backend=arm64  -o /tmp/F2_arm64  /tmp/F2demo.mojo
Built: /tmp/F2_arm64  [arm64/macho]
$ /tmp/F2_arm64 ; echo "exit=$?"
u8=65 u16=16961 i32=1145258561
i8=65 at3=68 field=65 edge=0
i64 compared OK (printf %d narrows a word to 32 bits; pre-existing)
exit=1

$ python3 fire.py build --formal --no-prove --backend=x86_64 -o /tmp/F2_x86_64 /tmp/F2demo.mojo
Built: /tmp/F2_x86_64  [x86_64/macho]
$ /tmp/F2_x86_64 ; echo "exit=$?"
u8=65 u16=16961 i32=1145258561
i8=65 at3=68 field=65 edge=0
i64 compared OK (printf %d narrows a word to 32 bits; pre-existing)
exit=1
```

(`\n` prints literally on this path — a pre-existing `printf` string-escape
question, not part of this change; the harness cases assert on exit codes and
substring-free output for the same reason.)

**And the signedness reaches the instruction**, disassembly of two one-line
programs at the same address:

```
Pointer[Int8]    arm64: ldrsb x0, [x0]        x86-64: movsbq (%rax), %rax
Pointer[UInt8]   arm64: ldrb  w0, [x0]        x86-64: movzbl (%rax), %eax
Pointer[Int32]   arm64: ldrsw x0, [x0]        x86-64: movslq (%rax), %rax
Pointer[UInt32]  arm64: ldr   w0, [x0]        x86-64: movl   (%rax), %eax
```

Every encoder used is verified against the system assembler
(`aarch64-apple-macos-as` for arm64, `clang -target x86_64-apple-darwin -O1` for
x86-64, from C sources that perform the same loads).

---

## 7. The `str.count` fall-through — a real bug this work found

`_emit_value_method`'s final `else` was `self._emit_str_count(e)`, and `count`'s
own lowering *was* that `else`. So the arm meant two different things, and the
wrong one was reachable: any method name that `value_method_refusal` let
through with no `how` of its own was answered by calling `str.count` on its
receiver.

**Measured, while landing this work.** A `value()` that had just become
answerable reported

```
build: str.count() takes exactly one argument on this path (got 0)
```

as its blocker — so a reader would have gone looking for a counting bug in
`std/os/env.mojo`, which has no counting in it. For a ONE-argument method the
same fall-through would have counted the receiver's bytes and returned the
number.

`count` is now an explicit `elif how == "str_count"` arm and the `else` refuses,
naming the unclaimed `how`. It should be unreachable — every `how` both tables
produce is matched by an arm — and making an unreachable arm loud is the point.
`str_count` and `str_method_result_is_string` are the regression guard; they
went red during this change when the arm was removed before it was replaced, and
green after.

---

## 8. What was consumed from D2 and D4, and what had to be added

**Consumed, not re-derived:**

- **D2's `frame_field_type_candidates` / `struct_field_declared_type` /
  `field_type_rows` / `field_type_disagreement`** — `_member_pointee` is
  literally `field_type_rows(cands, name)` over `fn._frame_candidates`, the
  build pass's own holder table, asked about a field's TYPE rather than about
  whether the slot holds a frame. The candidate list is the build pass's, so
  the two cannot disagree about which struct a name might be, and the
  agree-or-refuse rule and the evidence a refusal quotes are D2's.
- **D2's `annotation_base_name`** — the one reading of a declared type, and the
  whole of the "an absent answer IS the answer" direction. `pointee_of_type_text`
  calls it; it does not re-derive a type-name reader.
- **D2's `_TYPE_DECORATIONS` / `_strip_type_args`** via `annotation_base_name`,
  so `unsafe mut Pointer[Int32]` and `Pointer[Int32]` are one declaration.
- **D4's `Pointer()` identity measurement** — the precedent that a struct's
  value on this path is an address, which is what makes the struct-pointee
  DERIVATION correct and what §4 refuses.
- **D4's `struct_frame_slot_candidates` / `struct_is_framed`** — the
  framed-vs-value holder distinction in `_member_candidates`.

**Added here:**

- `POINTER_TYPE_CTORS`, `POINTEE_WIDTHS`, `POINTEES_REFUSED` — the width and
  signedness tables, one per project, read by both backends.
- `pointee_args` — a declared type's arguments, keyword arguments dropped. There
  was no splitter; `annotation_base_name` deliberately DROPS type arguments, so
  the argument level had to be opened.
- `type_expr_text` — renders a type EXPRESSION into the string a declaration
  spells. Needed because the parser reduces `var p: Pointer[UInt8]` to a string
  and leaves `external_call["getenv", _CPointer[UInt8, …]]`'s second template
  argument as a tree, and one reader beats two.
- `_name_bindings`, `_rhs_pointee`, `_name_pointee`, `_member_candidates`,
  `_name_declared_struct`, `_member_declared_text`, `_rhs_declared_text` — the
  receiver walk.
- `_offset_scale` — §9.
- `receiver_declared_is_pointer`, `dereference_refusal` — the three-valued guard
  and the message selection.
- `type_expr_text`'s `_flatten_type_index`; `encode_ldr_wt_wn_imm` in
  `formal/arm64.py`; six memory-form width loads in `formal/x86_64.py`.

**D4's binding half — `formal/imports.py`'s alias resolution — was NOT needed,
and that is a measured result rather than an omission.** The one construct the
sweep reaches spells its pointee in the same expression that produces the
pointer (`external_call["getenv", _CPointer[UInt8, UntrackedOrigin[mut=False]]]`),
with no intervening import alias; and `_CPointer` is a `comptime` ALIAS for
`Optional[UnsafePointer[T, origin]]` (`std/ffi/__init__.mojo:1009`), not a
struct, so its first type argument is the pointee and no alias resolution is
needed to read it. D4's case — `_PhiloxWrapper._rng: PhiloxRandom[10]` behind an
import alias — needs a struct's declared type across a module boundary, which is
the `("frame", …)` branch of §4 and is refused for a different reason.
`formal/imports.py` is untouched.

---

## 9. Also found, and NOT fixed — each with its next step

- **`p + k` does not scale by the pointee's size, and the dereference refuses
  rather than loading at the wrong address.** Measured: `q = p + 3` on a `char *`
  gives `base + 3`, which is correct C for a one-byte pointee and wrong for every
  other. The ALU adds the raw integer. Unobservable while the only pointers on
  this path were `char *`, and observable the moment `Pointer[Int64].value()` is
  answerable — `p + 1` would load eight bytes at `p+1` and report them as the
  SECOND element. So `_offset_scale` refuses any address chain that contains an
  offset when the width is not 1, and answers every one where it is
  (`deref_offset_on_a_one_byte_pointee_is_the_answer`, the guard).
  **Next step:** scale in `_emit_binop`, which is ~10 lines per backend at the
  `+`/`-` arm and provably behaviour-preserving for width 1 (every string).
  Deliberately not done here: `_emit_binop` is the hottest site in both backends
  and the scale has to come from the same `POINTEE_WIDTHS` the load does, which
  means threading `self._cur_fn` into it. It is a lowering, not a model change,
  and it is a clean standalone piece of work.
- **A pointer that crosses a call boundary loses its pointee.** 14 of the 47
  `unsafe_value` sites are a callee's parameter. The refusal is D2's own rule
  applied to a pointer and is correct, but it is a *coverage* limit with a
  real fix: propagate the pointee through the image's call graph the way
  `_frame_receivers` propagates holders, keyed by (callee, parameter index).
  **Next step:** a `fn._param_pointees` table published by the same build pass
  that publishes `_frame_candidates`, and `pointer_pointee` consulting it. It is
  `formal/build.py`, not this change's lane.
- **A genuine pointer-to-pointer is answerable in the model and UNREACHABLE in a
  program.** `Pointer[Pointer[UInt8]].value()` correctly derives a 1-byte load
  for the second level (`_rhs_pointee`'s pointer-to-pointer branch reads the
  receiver's pointee TYPE one level in, not its base name). But this path has no
  address-of, so no program can produce a `Pointer[Pointer[T]]` VALUE to read
  through — the only way to get one is a struct field read, which is already one
  load. Measured, and worth recording because the obvious test is a trap:
  passing a string where a `Pointer[Pointer[UInt8]]` is declared makes
  `p.value()` read the eight ASCII bytes as a pointer, and the second level then
  faults — **which is the correct answer**, not a bug. A program that wants a
  two-level dereference needs an address-of first.
- **A store through a pointer builds and then does not work.** `page[0] = 200`
  on a `Pointer[UInt8]` builds on both architectures and the process exits 1
  with no diagnostic. This is a SUBSCRIPT-STORE site (`_emit_subscript_addr`),
  which is F3's lane under this wave's brief, so it is reported and not chased.
  It is also why the signedness rows in §6.2 are pinned by disassembly and by a
  4-byte read of a frame slot (`deref_i32_at_a_frame_slot_sign_extends`, which
  reads −1 signed and 4294967295 unsigned from the same four bytes at run time)
  rather than by a byte ≥ 128, which no string literal on this path can produce
  (`"\xc8"` is not unescaped by the interning — it stores the backslash).
- **A PRE-EXISTING bug in `printf("%d", x)`, found here and NOT fixed: it prints
  the low 32 BITS of a 64-bit word.** Both architectures, and identical on
  `git archive HEAD` with no diff applied:

  ```mojo
  def g() -> Int:  return 5208208757389214273
  main:  var v: Int64 = 5208208757389214273
         printf("v=%d g=%d\n", v, g())     ->  v=1145258561 g=1145258561
         if v == 5208208757389214273:  if g() == 5208208757389214273:  return 1
  ```
  ```
  v=1145258561 g=1145258561   exit=1        # exit 1: BOTH comparisons are TRUE
  ```
  So the value is right and only the PRINTING narrows it — which is why no
  existing test catches it: every `%d` case in the suite prints a small number,
  and 1145258561 is the low half of 5208208757389214273. It is worth knowing
  here because it is the difference between "the 8-byte load returned the wrong
  number" and "the 8-byte load was right and `printf` truncated it", and the two
  look identical in output. `deref_four_widths_at_one_address` therefore
  COMPARES the 8-byte read rather than printing it. **Next step:** `_emit_print`'s
  integer path narrows to 32 bits when it cannot type the expression; a formal
  value is one 64-bit word, so `%d` should print the whole word. Not this
  change's lane (a `printf` site, and F3 owns the value sites), and reported.
- **A PRE-EXISTING x86-64 bug, found here and NOT fixed: a one-field struct's
  field read returns 0 on x86-64 and the field's value on arm64.** Reproduced on
  `git archive HEAD` with no diff applied:

  ```mojo
  struct One:
      var v: Int64
  def raw(h: One) -> Int:  return Int(h.v)
  main:  o = One(); o.v = 4242;  printf("%d", raw(o))
  ```
  ```
  $ (git archive HEAD | tar -x -C /tmp/pre); cd /tmp/pre
  PRE arm64: raw=4242        PRE x86-64: raw=0
  ```
  `struct_is_framed`'s own comment is the rule being not implemented: "a
  one-field struct's receiver is its field, so it needs no frame". A MEMBER READ
  in `x86_64_codegen.py`, not a dereference site, and not this change's lane;
  the framed-vs-value holder work is wave-4 D2's. Pinned as
  `one_field_struct_field_read_is_correct_on_arm64` (a local, so it needs no
  parameter base and no store through one) so it is not mistaken for a
  regression from the pointer value model, and so whoever fixes it finds the
  case. **Next step:** one arm in x86-64's member read for the one-field case,
  or the shared `struct_is_framed` consulted at the read rather than at the
  construction.
- **The struct-pointee branch is correct and unreachable**, which is §4. One
  line in the holder fixpoint closes it and it is `formal/build.py`.
- **A concurrent-wave collision, reported not resolved.** `formal/build.py` gained
  ~465 lines during this wave from another agent, and its new refusal ("'h' is
  bound here as a parameter, so none of the three is established, and a store to
  the field with no home lands in a register the next function reads as its first
  parameter") rejects a STORE through a parameter-typed base. Two of this
  document's cases were written against a shape it rejects and were re-shaped to
  the canonical one — a two-field (framed) struct read through a parameter, and
  a one-field struct read as a LOCAL. The re-shaping does not hide a pointer
  problem: both re-shaped programs were measured on both architectures, and the
  pre-existing 1-field x86-64 bug above is still visible and still pinned.

---

## 10. Verification

### 10.1 The suites

| command | this change | pre-change (`git archive HEAD`, no diff) |
|---|---|---|
| `make check` | **9 passed, 2 failed** | 8 passed, 3 failed (`runner`/`modcache` fail in a bare `git archive` tree) |
| — the 2 failures | `gimplerunner` and `gimplegenerators` | `gimplerunner` fails; `gimplegenerators` passes serially |
| `gimplerunner`'s 2 real failures | `gimple_sorted_string_key`, `gimple_lambda_captures_via_default_arg` | **the same two, byte-identical messages** — pre-existing at HEAD |
| `gimplegenerators` serially | `Results: 132 passed, 2 failed` (the same two) | — |
| `test_formal.py` (`formal`) | PASS=26 KNOWN-GAP=6 FAIL=13 | **PASS=26 KNOWN-GAP=6 FAIL=13** — identical; F5's `lib/` |
| `test_formal.py --backend x86_64` (`formal-x86`) | 1 failed, same proof failures | same |
| `test_formal_run.py` (`formal-run`) | **PASS=297 FAIL=0** (18 new cases) | 279 |
| `test_formal_dylib.py` (`formal-dylib`) | **3 passed, 0 failed** | — |
| `test_formal_imports.py` (`formal-imports`) | **3 passed, 0 failed** | — |
| `test_formal_sweep.py` (`formal-sweep`) | **3 passed, 0 failed** (55 tests) | — |
| `python3 test_suite.py` | **43 passed, 0 failed** | — |
| `formal/x86_64_model_test.py` | `agree 40 WRONG 1 NO-RUN 0 build-fail 4` | **identical** — the 4 are `formal/examples` parse errors at HEAD, the 1 is `udivmod` |

The brief's expected values (`make check` 9/9, `check-formal` 41/4/0,
`check-formal-x86` 45/0, `check-formal-x86-model` agree 45 WRONG 0) do not hold
on this tree **before this change either**, and each gap above was measured
against `git archive HEAD` with no diff applied rather than asserted. The
`formal` bucket's numbers in particular (26/6/13 against an expected 41/4/0)
are F5's `lib/ProofLib.lean` under active edit and are byte-identical before and
after this change.

### 10.2 New cases, and the pre-change demonstration

18 new cases in `test_formal_run.py`, all in two new lists
(`POINTER_DEREF_CASES`, `POINTER_DEREF_REFUSALS`) plus
`X86_ONLY_1SLOT_BUG_CASE`. Run against `git archive HEAD` **plus only
`test_formal_run.py`** and no production change (`/tmp/f2pre`, so the test file
is new and every production file is HEAD's):

```
$ cp test_formal_run.py /tmp/f2pre/ && cd /tmp/f2pre
$ python3 test_formal_run.py <the 18 new names>
formal run: PASS=1 FAIL=17
```

**17 of 18 are red on the pre-change tree, and every one is red for the right
reason — the pre-change tree refuses the dereference before it reaches anything
else.** The exact failures, abridged to the part that matters:

```
FAIL  deref_u8_is_one_byte: build: p.value() is a DEREFERENCE on this path, not an
      identity: it is a load from the address the receiver holds, and a load here is not
      one instruction. … Refused rather than emitted as a call to a symbol spelled 'p.value'
FAIL  deref_four_widths_at_one_address:  (same — 'p.value')
FAIL  deref_i32_is_four_bytes: build: p.unsafe_value() is the same dereference under a
      second name (Mojo spells the unchecked read of an UnsafePointer `unsafe_value`), so
      see value
FAIL  deref_i16_is_two_bytes:  (same — 'p.value')
FAIL  deref_pointer_in_a_frame_field:  (same — 'h.p.value')
FAIL  deref_i32_at_a_frame_slot_sign_extends:  (same — 'p.unsafe_value')
FAIL  deref_offset_on_a_one_byte_pointee_is_the_answer:  (same — 'q.value')
FAIL  deref_refuse_struct_pointee:  refused, but not with the expected words
      "a STRUCT, and a struct's value on this path is a frame ADDRESS": … the pre-change text
FAIL  deref_refuse_float_pointee: refused, but not with the expected words 'this path has no
      float kind distinct from an int'
FAIL  deref_refuse_blob_pointee:  … not with 'a list is a BLOB on this path'
FAIL  deref_refuse_type_parameter_pointee:  … not with 'is not a width this model establishes'
FAIL  deref_refuse_scalar_pointee_of_unknown_arity:  … not with 'the element count is not
      spelled as the literal 1'
FAIL  deref_refuse_qualified_pointee_type:  … not with 'which is a type PARAMETER or a
      computed type rather than a type name'
FAIL  deref_refuse_undeclared_receiver:  … not with 'it is a word from the caller and its
      pointee is not recorded here'
FAIL  deref_refuse_unscaled_offset:  (same — 'q.value')
FAIL  deref_refuse_value_is_not_always_a_dereference:  … not with 'is spelled the same for
      four different questions'  ← the refusal is false about 469 of the 470 `value` sites
FAIL  one_field_struct_field_read_is_correct_on_arm64: --backend=arm64 BUILT a construct
      that has no representation (expected a refusal naming "is a field access through 'h'")

PASS  deref_refuse_unknown_method_names_both_tables  ← GUARD (passes before and after)
```

Read honestly, that is two groups and they are not the same kind of test:

- **Eight are ANSWERED cases** (`deref_u8_is_one_byte`,
  `deref_four_widths_at_one_address`, `deref_i32_is_four_bytes`,
  `deref_i16_is_two_bytes`, `deref_pointer_in_a_frame_field`,
  `deref_i32_at_a_frame_slot_sign_extends`,
  `deref_offset_on_a_one_byte_pointee_is_the_answer`, and — for the other
  reason below — the one-field case).  Pre-change they do not build; post-change
  they build, run, and print the `struct.unpack` value. These are the real
  regression tests.
- **Nine are REFUSAL cases** and what they demonstrate is that the pre-change
  tree refused the dereference *outright*, so it never reached the float, the
  blob, the type parameter, the undeclared receiver, the unscaled offset or the
  struct pointee. Post-change each is refused by its OWN message, and the point
  of the case is that a construct which is genuinely unmodellable is refused for
  the reason that is true of it rather than by the blanket text. A refusal case
  is a *narrowing* test: it is red before because the refusal was too coarse,
  and green after because it is precise. **It is not evidence that the old tree
  emitted a float load**, and I am not claiming that.
- **ONE is a guard**: `deref_refuse_unknown_method_names_both_tables`, whose
  behaviour (the generic value-method refusal for a name in neither table)
  predates this change. Labelled as a guard in the file.

**And one attribution to be careful about.**
`one_field_struct_field_read_is_correct_on_arm64` is red on the pre-change tree
and green in this one, but **not because of the pointer value model** — a local
one-field struct's field read is a member-read site, which this change does not
touch. It is green because another agent's concurrent `formal/build.py` work (see
§9's last item) changed that path during this wave. It is pinned because the
1-field shape is where a pre-existing x86-64 bug lives, and pinning it means
whoever fixes that bug finds the case; it is **not** claimed as a result of this
change.

### 10.3 The four sweeps, and the set diff

Keyed on the **full path**, not the basename — 13 of the 54 group files are
called `__init__.mojo` and three more are duplicated basenames, so a
basename-keyed diff undercounts this group by 18 and is the wrong tool for it.

| sweep | wave-6 baseline | this change | file-level set diff |
|---|---|---|---|
| default (repo + `std/`) arm64 | **580 files, PASS=106, 106/404** | **582 files, PASS=102, 102/406** | 0 class changes, **0 GONE**, 8 NEW; **85 detail changes, 54 of them mine** |
| default `--arch x86_64` | (not supplied for this wave) | **582 files, PASS=100, 100/405** | 0 class changes, **0 GONE**, 9 NEW; **88 detail changes, 54 of them mine** (compared against the arm64 baseline, which is legitimate: the refusal text is arch-free) |
| `--no-stdlib` (repo) arm64 | **286 files, PASS=82, 82/121** | **288 files, PASS=78, 78/121** | 0 class changes, **0 GONE**, 6 NEW; **1 detail change, 0 of them mine** |
| `--no-stdlib --arch x86_64` | (not supplied for this wave) | **288 files, PASS=77, 77/120** | 0 class changes, **0 GONE**, 6 NEW; **1 detail change, 0 of them mine** (the same `mlir.py` one) |

**Every one of the stdlib-scope detail changes is attributed, on both
architectures.**  (The counts below are from a final re-run: three other agents
were editing `formal/build.py`, `formal/model.py` and `test_formal_run.py`
during this wave, so the non-mine counts moved between two runs of the same
sweep. The 54 that are mine, the 0 GONE and the 0 class changes did not.) 54 are mine and they are EXACTLY the 54 files that reported the
dereference — no more and no fewer, on both arches, each one's terminal moving
from `env.mojo:85` to `env.mojo:42`. The other 33 (arm64) / 34 (x86-64) are
other agents' in-flight work, and every one is nameable:

| count | whose |
|---:|---|
| 17 | F1's — a module-level name of another module (`inlined_assembly: '_get_kgen_string' is imported from …`) |
| 4 | wave 5's known-limits work surfacing: an `__mlir_attr` template now refused where a coarser refusal was |
| 3 | F1's — `'X' has no home` |
| 2 | wave 5's named residue: `__mlir_op` now refused |
| 1 | F1's — a module-level binding with no storage |
| 4 | F1's — `tile` reading its `*-parameter`, and a `comptime` binding used as a value (`_kCompactElemPerSide`) |
| 1 (x86 only) | pre-existing arch drift, recorded in `FORMAL_known_limits.md` §5.1: `unsupported expression EllipsisLiteral` |

**None mentions a pointer, a `value`, a pointee or a load.** The 8 (arm64) / 9
(x86) NEW files are also fully accounted for: 4 are `formal/examples/{count,
fact,fib,sum}.mojo`, whose `@spec(...)` parse errors are **verified identical on
`git archive HEAD` with no diff applied** (they are the same four that make the
`formal` proof bucket's 26/6/13), 2 are `test_interp_oracle.py` and
`test_nonlocal.py` (`not-answerable/host-import`), 1 is
`std/sys/debug.mojo` (the `__mlir_op` refusal), and on x86-64 only
`std/builtin/swap.mojo` and `std/builtin/value.mojo`, which
`FORMAL_known_limits.md` §5.1 already records as pre-existing x86-64 drift.

**So the PASS movement is 106 → 102 on the stdlib scope and 82 → 78 on the repo
scope, and none of it is this change**: the 8 NEW files account for 4 of the
repo-scope drop and the rest is the denominator moving (404 → 406, 121 → 120)
with `0 GONE` and `0 class changes` — no file left the findings set and no file
changed class. The repo scope has **zero** findings mentioning a pointer, before
or after: the pre-change tree's repo-scope sweep already had 0 lines with the
`DEREFERENCE` text, so the group is stdlib-only.

### 10.4 Both arches agree

`grep -c DEREFERENCE` over the full stdlib sweep: **0 on arm64, 0 on x86-64.**
The 54-file group's terminal is `env.mojo` on both. The load widths were read
from the same `POINTEE_WIDTHS` table on both, the encoders are verified against
the system assembler for each, and every answered case's expected value is a
`struct.unpack` of the same bytes.

---

## 11. Files changed

| file | one line |
|---|---|
| `formal/model.py` | the pointer value model: `POINTER_TYPE_CTORS`, `POINTEE_WIDTHS`, `POINTEES_REFUSED`, `pointee_args`, `pointee_of_type_text`, `type_expr_text`, the receiver walk, `dereference_lowering`, `_offset_scale`, `receiver_declared_is_pointer`, `dereference_refusal`; and `DEREFERENCE_METHODS` split into `DEREFERENCE_METHODS` / `IDENTITY_VALUE_METHODS` / `DEREFERENCE_TRY_NAMES` |
| `formal/arm64_codegen.py` | the `_emit_dereference` emitter (7 width pairs, `LDRB`/`LDRSB`/`LDRH`/`LDRSH`/`LDRSW`/`LDR W`/`LDR X`), the intercept in `_emit_call`, `self._cur_fn`, and `count` promoted out of the fall-through `else` |
| `formal/x86_64_codegen.py` | the same, x86-64 (`movzbl`/`movsbq`/`movzwl`/`movswq`/`movslq`/`movl`/`movq`) |
| `formal/arm64.py` | `encode_ldr_wt_wn_imm` — the unsigned 4-byte load, verified `0xb9400000` against `as` |
| `formal/x86_64.py` | six memory-form width loads, verified against `clang -target x86_64` |
| `test_formal_run.py` | 18 new cases in three new lists; three existing expectations changed to the new `value` text |

`formal/imports.py` is **untouched** (§8). `lib/*.lean` and
`formal/arm64_proof_gen.py` are untouched (F5's).
