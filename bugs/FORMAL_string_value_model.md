# FORMAL_string_value_model: what a string IS on the formal path, and the two things that want to be one

**Status:** the representation question is DECIDED and the decision is landed.
The string stays a bare `char *`; the length and the content equality are
recovered as *computations* over that one word rather than as fields, and the
two wrong answers that followed from not doing so are fixed on both backends.
Wave 5 then closed the two items this document left named (`in` and `+=`) and
found the same defect class in **eleven more operators** — every one measured,
every one refused. Wave 6 closed the three it left (`~`, the truthiness
conversion, and a slice of a string) and found **three more** in the same family
that no list had recorded: `if []:`, a short-circuit chain used as a condition,
and an x86-64 `assert` that always failed. What is still NOT fixed, and is the
larger thing, is the collision between that representation and the stdlib's own
`String` struct — which is what all 16 of the "a String receiver is
returned/passed" refusals in the stdlib sweep actually are, and which is not a
string-value-model problem at all. Two regressions that arrived from outside
this work, with a merge, are at the bottom.

## The decision, and the reasoning that decides it

A formal value is one 64-bit word. A string on this path is a bare `char *`.

The task this document answers is whether that has to change, and the shape of
the question is wave 3's: wave 3 asked the same thing of a multi-field struct
and answered it *by reference* — a pointer is one word, so a struct that does
not fit in a word is reached through a pointer rather than widened. Is there an
analogous move for a string?

**Yes, and it is already made.** Three facts, each measured on this tree rather
than assumed:

1. **A string is already a reference, and what it refers to is not a frame.**
   String bytes are interned by content (`_intern_string` in either backend) and
   emitted into `__TEXT,__text`. Measured on a built image:

   ```
   SEG __TEXT  maxprot=0x5 initprot=0x5
      __TEXT,__text addr=0x100000320 size=139
   ...the last bytes of __text: b'hello\x00len=%d\\n\x00'
   ```

   `initprot 0x5` is read+execute with **no write bit**, and the bytes are
   NUL-terminated. Note both halves: the terminator is what makes point 2
   possible, and the missing write bit is why `strip`/`rstrip`/`upper`/`replace`
   are refused rather than approximated.

2. **Because the representation is NUL-terminated, a string's length is a
   COMPUTATION, not a field.** `strlen(s)` *is* the length of a NUL-terminated
   `char *`, by definition. So the missing length costs one libc call and **no
   storage, no second word, and no lifetime** — nothing above the value model
   has to be re-derived by anything that reasons about word-sized values: not
   the struct refusal, not the frame slot tables, not the one-word field map,
   not the call ABI, and not the ~40 passing proofs. The same argument makes
   `==` a computation: `strncmp(a, b, strlen(b) + 1) == 0` is the content
   equality of two NUL-terminated `char *`s. Both symbols were **already being
   emitted by both backends** — `endswith`, `count` and `f.write(s)` all call
   `strlen`, and `startswith` calls `strncmp`. This change adds no new
   machinery; it points existing machinery at a case it already answered.

3. **A string is the ONE pointer on this path with no lifetime problem.** Every
   string value is either a literal's bytes or an interior pointer into them
   (`lstrip` is the only method that yields a string, and it yields
   `s + strspn(s, STRIP_CHARS)`), so every string value has **static** storage
   duration. It is as safe to return from the function that made it as any
   other pointer is not. Measured, both backends:

   ```python
   def make():
       s = "  hi".lstrip()
       return s
   def main(n):
       printf("[%s]\n", make())        # -> [hi]
   ```

Point 3 is the load-bearing one, and it cuts *against* the descriptor. A
`{ptr, len}` descriptor puts the length in a field, so the descriptor has to
live somewhere: a frame (and then it inherits the frame's lifetime, so every
`lstrip` result would have to be refused for exactly the reason a struct frame
address is — **losing the one string method that works today**) or a heap
(and there is none). It would also not survive `lstrip`, which produces an
interior pointer with no descriptor of its own. On this path a descriptor is not
a cheaper answer; it is strictly more expensive, and it buys back nothing
`strlen` was not already giving.

## The cost, stated rather than hidden

- **`len(s)` and `s == t` are O(n)**, where interning made `==` O(1) between two
  literals. On a backend whose job is to be trustworthy rather than fast, that
  is the right trade, and it is still a trade.
- **A string value here cannot contain a NUL**, because the NUL ends it. A real
  Mojo `String` can, and `len` of a string with an embedded NUL would be wrong.
  Nothing lowered today can produce one — every string is a literal or an
  interior pointer into a literal — so this is a **latent** gap, not a live
  wrong answer. It is recorded here so that whoever adds the first method which
  can build a string at run time inherits the obligation.
- **`is` / `is not` must stay pointer comparisons.** They are the one string
  comparison for which the pointer is the *answer* rather than an approximation
  of it: `a is b` asks whether two names hold one object, and with interning by
  content two equal literals already are one object. Routing them through the
  content compare would make `x is y` true whenever the *contents* match, which
  is a different question spelled the same way. `model.string_comparison_lowering`
  is the single decision that keeps `==` and `is` apart, and it is shared by
  both backends so they cannot come apart on one architecture.

## What was fixed, with the before and after

All three were wrong ANSWERS, not refusals, and all three were measured on both
architectures. Full transcripts are in the commits; the numbers are:

| construct | before (both backends) | after (both backends) |
|---|---|---|
| `len(m)`, `m = "hello"` | 1819043176 | 5 |
| `len("  hi".lstrip())` | 536897896 | 2 |
| `len("")`, `len("   ".lstrip())` | 538976256, 168370176 | 0, 0 |
| `m == "abc"` where `m = "  abc".lstrip()` | false — wrong branch | true |
| `"ab" + "cd"` | `[]` on arm64, SIGSEGV on x86-64 | refused, identically |

The `len` numbers are worth reading as hex, because that is what they were:
1819043176 is 0x6C6C6568, which is `hell` read little-endian, and 536897896 is
0x20006869, which is `hi` followed by the two spaces `lstrip` had just trimmed.
**The old lowering read the first eight CHARACTERS of the string and returned
them as a number**, because the refusal that was supposed to prevent it fired
only on a *syntactic* `StringLiteral` or an identity type-constructor, and every
other shape fell through to a count-field load.

`==` is the second-worst shape a wrong answer can have: a *correct program
taking the wrong branch*, with nothing downstream able to tell.

`+` was the third: one wrong answer on one architecture and a crash on the
other, from one line of source, so the two backends did not even agree on
whether the program worked.

## The x86-64 `strcmp` observation — what it does and does not establish

The content compare is spelled `strncmp(a, b, strlen(b) + 1) == 0` rather than
the more obvious `strcmp(a, b) == 0`. That is a measured choice, and the
measurement is worth recording because it is a loose end.

`strcmp` works on arm64. On x86-64, an image whose only `strcmp` call sites were
the ones this lowering emitted returned **false for `"abc" == "abc"`**, and the
pre-change tree had no x86-64 `strcmp` call site at all to compare against. What
was verified by hand, and is correct: the emitted instruction sequence (two LEAs
to the same interned address, `mov rdi`, `call rel32`, `cmp rax, 0`, `sete al`,
`movzx`, `test`, `je`); the interned addresses (both LEAs resolve to the same
`0x…55b`, which is where `abc\0` is in the data pool); the `__TEXT,__stubs`
entry (0x572, six bytes, the second of two); the `__DATA_CONST,__got`
displacement inside that stub (0x4008, the second of two slots); and
`compute_macho_got_addrs`' stub map (`{'printf': …, 'strcmp': …}`, correctly
sorted and correctly spaced).

What was **not** established, and is the open question: whether the `strcmp` GOT
slot was bound. `lldb` is useless on this host for an x86-64 process — a
breakpoint on an address that is certainly executed (`0x100000350`, the first
LEA) does not stop — so the return value could not be read. The `strncmp`
spelling sidesteps the question entirely, because `strncmp` and `strlen` are
the two symbols the x86-64 backend **already** calls for `startswith` and
`f.write(s)`, and both are demonstrably bound. So this is filed as an
observation for whoever owns the x86-64 extern path, not as a claim that the
linker is broken.

## NOT the string value model: the 16 "a String receiver" refusals

The stdlib sweep has three string refusal families, and the largest is not a
consequence of anything above:

```
8 files   a String receiver is passed to a call in a position whose meaning this path cannot see
6 files   a String receiver is returned from the function that created it on this path
2 files   a StringSlice receiver is passed to a call in a position whose meaning this path …
```

Their message says *"the receiver of a multi-field struct is the ADDRESS of a
frame of 8-byte slots that belongs to the function which created it"*, and for
a string that is a **false statement**: the bytes are in the image's read-only
text section and are still there after every function has returned (point 3
above, measured).

The cause is that the name `String` denotes TWO incompatible things.
`std/collections/string/string.mojo` declares

```mojo
struct String:
    var _ptr_or_data: Pointer[UInt8]
    var _len_or_data: Int
    var _capacity_or_data: Int
```

— three fields, so wave 3's by-reference receiver makes a `String` local the
**address of a three-slot frame** (verified: `struct_is_framed(String)` is True,
`struct_frame_slots` is 3), and the frame-lifetime analysis in
`formal/build.py` then refuses to let one escape. Twenty lines reproduce it on
both backends, and the contrast is the whole point:

```python
struct String:                       # three fields, exactly as the stdlib has it
    var _ptr_or_data: Pointer[UInt8]
    var _len_or_data: Int
    var _capacity_or_data: Int
    def size(self):
        return self._len_or_data
def make():
    s = String()
    s._len_or_data = 5
    return s                         # REFUSED: "a String receiver is returned
def main(n):                         # from the function that created it"
    return make().size()

def make():                          # the SAME program with the string kept as
    s = "  hi".lstrip()              # a char *:
    return s                         # BUILDS, and prints [hi]
def main(n):
    printf("[%s]\n", make())
```

**These 16 files do not have a length problem. They have a length — in slot 1 —
and cannot keep it.** So they are not a string-value-model blocker and fixing
the string representation does not touch them. The blocker is that a `String`
local must be *either* a three-slot frame *or* a `char *`, and today the two
representations are in force simultaneously: the string methods are lowered
under the `char *` reading while the lifetime analysis uses the frame reading.

`model.string_has_static_storage()` is landed: it is the string half of that
answer, stated in the one file both sides read, with the reproducer. **The next
step is D2's and D4's** — the frame/field derivation, and the analysis of which
argument positions a callee can be trusted with. The string half they need is
this: *a `char *` to `__TEXT,__text` has static storage duration, so the
frame-escape rule is sound for a struct whose fields live in a frame and unsound
as applied to it.*

## Wave 5 (E4): the two named items closed, and the class around them is wider

Both items D3 named are fixed, and both turned out to be two holes in one
table rather than two holes in two places. The table is
`model.string_binary_refusal` — the single entry point both backends ask, with
`model.string_membership_lowering` beside it for `in`. Before and after, on
both architectures:

| source | pre-change | after |
|---|---|---|
| `s = "hello"; if "ell" in s: …` | **SIGBUS, exit 138, both backends** | `r=3`, exit 0, both backends |
| `s = "ab"; t = "cd"; s += t; printf("[%s]", s)` | `[]`, exit 0, **arm64**; **SIGSEGV exit 139, x86-64** | refused identically on both |

The `in` fix is `strstr(haystack, needle) != NULL`, and the *argument order* is
the whole method — `strstr("bc", "abcabcabc")` is a well-defined NULL, so
getting it backwards does not crash and returns FALSE for every haystack that
contains its needle. The needle shape is the second decision and it is the
model's: a string needle is `strstr`, a **byte** needle is `strchr`. The byte
case is not optional — x86-64 had no string membership path *at all*, so
`98 in "abc"` scanned the interned bytes as a blob and returned FALSE where
Python says TRUE.

Three things about the byte case, each of which is a wrong answer if missed:

- **`strchr(s, 0)` is non-NULL.** It returns the TERMINATOR, so a bare
  `!= NULL` makes `0 in "abc"` TRUE. On this representation it is certainly
  false: the only NUL in a string is the one that ends it. The byte is tested
  against zero in front of the call on both backends.
- **The result is 0/1**, and that is not a formality: there is no BOOL kind
  distinct from INT (which is why `__mlir_bool__` is refused), so "0/1" and "a
  bool" are the same thing here.
- **An EMPTY needle is TRUE.** `strstr` agrees (it returns the haystack), and
  a membership test that says an empty needle is absent is wrong in the
  direction that *hides* bugs. The compile-time both-literals path had this
  backwards for one revision (`bool("") and ...`), which is exactly the kind
  of half-answer two paths for one question produce.

`strchr` was **measured to bind on both backends** before being relied on,
because of the x86-64 `strcmp` observation above: with the byte path pointed at
it, `98 in "abc"` returned TRUE on arm64 and on x86-64, and `strchr` used as a
`strstr` walked off the mapping on both — which is how a bound-but-misapplied
call is told from an unbound one.

### The class: eleven more operators, all measured, all refused

`string_concat_refusal` was ONE operator out of a table, and the reason it was
one is historical: it was the one whose failure had been measured. Every
operator below has the same cause — a string is a bare `char *`, so any
operator reaching the integer ALU or the flag-setting compare is operating on
an ADDRESS — and every one **built, ran and returned a number the source never
wrote**. For `s = "abc"`, `t = "bc"`, on BOTH backends, and the two columns
**disagree**:

```
s & t    69911496 /  45978594      s | t    68191180 /   2872318
s ^ t          4 /        28      s - t         -4 /        -4
s * 2    8062864 /   5302246      s // 2  -2147433998 / -2128240118
s >> 1  -2107760164 / -2147386903  ~s         8881076 /    3236815
-s      -36488120 /  -79725522     s % 2           0 /         2
```

`s % 2` is worth reading twice: it is the one that *looks* like it might work.
`"%d" % k` is printf-style formatting, and it was returning the address modulo
`k` — 0 on arm64 and 2 on x86-64 for `k = 3`, and `"%s-%d" % (t, k)` printed
the format string through unchanged. A program that formats a string was
computing an address modulo a number.

**The relational half is worse than a wrong number, because it is a wrong
BRANCH.** `s < t` was TRUE and `s > t` FALSE on both backends, decided by the
order the two literals happen to be interned in `__TEXT,__text`. Reordering the
two lines of source reverses every one of them. Lexicographic order needs a
three-way compare and this path has no symbol that provides one, so `<`, `>`,
`<=`, `>=` are refused rather than approximated.

Also refused, for the same reason and by the same call: every **augmented**
spelling (`+=`, `-=`, `*=`, `//=`, `%=`, `&=`, `|=`, `^=`, `<<=`, `>>=`, `**=`),
which is the whole of the second named item — one augmented emitter had simply
never asked the question — and **unary** `-` and `~`.

One operator is deliberately NOT in the table: `ptr + int` and `ptr - int` with
exactly **one** string operand stays allowed, which is D3's decision and a real
C reading (`str_plus_int_still_arithmetic` is its guard). Every other operator
above has no such reading: `%` and `&` on a pointer are not C at all, `|` and
`^` are bit operations on an address, and `*` would have to scale a pointer,
which is a GNU extension rather than the C this path emits.

### Two gaps that only RUNNING programs found

Both are cases where the SAME construct is a diagnostic in one context and a
wrong answer in another, which no amount of reading `_emit_binop` would show:

- **`if s < t:` did not go through `_emit_binop` at all.** A comparison in a
  *condition* is lowered as CMP + B.cond so the boolean never round-trips
  through a register, and that fast path bypassed the refusal entirely. So
  `r = s < t` was refused while `if s < t:` branched on the address order. The
  refusal is now asked in arm64's `_emit_branch_unless` as well.
- **A string INDEX, `s[t]`, is `s + i` with two addresses.** It printed **67** on
  arm64 — the low byte of a text-section address, which is the most believable
  fabricated number in this whole group because it is small and printable and
  reads like a character code — and segfaulted on x86-64. Refused at
  `_emit_subscript_addr`, the single choke point a read, a store and an
  augmented assignment all pass through.

## Wave 6 (F3): the three residue items closed, and the class was wider than three

All three items wave 5 left named are closed, and all three were **wrong answers
or a crash measured before and after on both architectures**. Two of them turned
out to be more than one bug each, and finding the extra ones is the more useful
half of the result — see "what was found while looking" below.

| source | pre-change (both backends) | after (both backends) |
|---|---|---|
| `s = "abc"; r = ~s; printf("%d", r)` | **46007208 / 38761401** — the ADDRESS of the string, because `~` was dropped by the tokenizer and the statement was `r = s` | refused, identically worded |
| `r = ~5` | **5** — same tokenizer drop, and the overwhelmingly common use of `~` was wrong the same way | `-6` |
| `printf("%d %d %d %d", ~0, ~1, ~-1, ~~7)` | **`0 1 -1 7`** — the operands themselves, printed back | `-1 -2 0 7` |
| `e = ""; if e:` | **`E-truthy`** | `E-falsy` |
| `e = ""; while e: i = i + 1` | **never terminates** (60 s timeout) — the condition is an address, and the body is unreachable so it can never change it | `i=0`, terminates |
| `a = []; if a:` | **`L-truthy`** — a list blob's truthiness is its COUNT, and this was not in wave 5's list at all | `L-falsy` |
| `f = [1]; e = []; 1 if (f and e) else 0` | **1** | 0 |
| `1 if "" else 0` | **1** | 0 |
| `e = ""; assert e` | **exit 0 on arm64, exit 1 on x86-64** | exit 1 on both |
| `assert 1` | **exit 0 on arm64, exit 1 on x86-64** | exit 0 on both |
| `s = "abcde"; printf("[%s]", s[1:])` | **SIGSEGV, exit 139** | refused, identically worded |

### 1. `~` never reached the parser. One line, and it was a lexer bug

`fire_compiler.py`'s `_TOKEN_RE` had no `~` in its `OP` alternation, and
`py_tokenize` drops `UNK` tokens without a word
(`if kind in ("WS", "UNK", "XFER"): continue`). The `~` was therefore gone
before `Parser._parse_unary` — whose `t.value in ("-", "+", "~")` branch is
correct and was unreachable — ever saw it.

**The AST already had the node.** `UnaryOp` (`fire_compiler.py:302`) is a
dataclass with `op`/`operand`, `_parse_unary` builds one for `~`, the
interpreter evaluates one (`myinterpreter.py:4971`, `elif op == '~': return
self._wrap_int(~operand)`), and the compiled path lowers one
(`mojo/backend_gimple/emit_exprs.py:_lower_UnaryOp`, `c_op = {'-': '-', '~':
'~'}`). So the fix is the alternation and nothing else: **no new node, and no
second unary representation.** Measured after: `r = ~5` builds
`AssignStmt(target=r, value=UnaryOp(op='~', operand=IntLiteral(5)))`.

**`~` on an integer was wrong too, for the same reason, and that is the more
important half of this item.** `~` is overwhelmingly used on integers, and
`printf("%d %d %d %d", ~0, ~1, ~-1, ~~7)` printed `0 1 -1 7` — the four
OPERANDS, each one silently returned unchanged. Every value now matches Python
on a two's-complement 64-bit word, both architectures: `~5 = -6`, `~0 = -1`,
`~1 = -2`, `~-1 = 0`, `~~7 = 7`, `~1000000007 = -1000000008`,
`~4611686018427387904 = -4611686018427387905`, and `~(a+b)` / `~(a*b)` / `~(a<<2)`
on operands rather than on literals. (`printf("%d")` truncates to 32 bits, so a
64-bit answer has to be read with `%lld` — the `-1` a `%d` prints for
`~2**62` is the formatter, not the operator.)

arm64 needed a `~` branch it did not have: x86-64's `_emit_unary` has had one
for several waves, arm64's inline `UnaryOp` handling had `not`, `-`, `+` and the
ownership marker and then raised `unsupported unary operator`. Left alone, the
two backends would have answered `~5` differently — one `-6`, one a
`CodegenError` — for a construct with one meaning. `encode_mvn_xd_xn` is new in
`formal/arm64.py` and is spelled as `ORN Rd, ZR, Rn` through
`encode_orn_xd_xn_xm`, because `MVN` IS that instruction and a second copy of
the constant is a second thing to keep in step. Both encodings were verified
against the assembler (`mvn x0, x1` = `0xAA2103E0`).

### 2. Truthiness: one table, and every site routed through it

`model.truthy_lowering` is the table, and it is three rows because
`len_operand_lowering` already had the two that have a knowable answer:

| operand kind | lowering | why it is right |
|---|---|---|
| `str` | `strlen(s)` | a string is a NUL-terminated `char *`; the empty string is a NON-NULL pointer, so "is the word zero" says the empty string is truthy. `strlen("") == 0` |
| `list` / `tuple` / any counted blob | one load from offset 0 | a blob is `[count:i64][elem…]`, so its truthiness IS its count |
| everything else — an `int`, a **frame address**, an unclassified word | the word itself | 0 is the only falsy integer, and a frame is never mapped at 0, so pointer truthiness is the right answer for a struct receiver |

The third row is the one worth defending, and it is the reason there is no BOOL
kind distinct from INT (which is why `__mlir_bool__` is refused) that it needs
no new representation: the result is a word whose ZERONESS is the answer, so
`TRUTHY_FROM_STRLEN` and `TRUTHY_FROM_BLOB_FIELD` are literally the two
`len_operand_lowering` row names, reused rather than respelled, and
`TRUTHY_NONZERO` needs no instruction at all.

**The compiled path already had this table**, in
`mojo/backend_gimple/emit_stmts.py::_ensure_bool_cond`: a container's length for
a container, `mojo_truthy_cstr` (a `strlen != 0`) for a `char *`, a
pointer-nonzero for any other pointer, a nonzero for an integer. Four rows, the
same four, decided in one place. So this change brings the FORMAL path into
agreement with the compiled one rather than inventing an answer.

#### The site enumeration — every site found, and every one routed

`if`/`elif`, `while`, `a if c else b` in BOTH of its lowerings (the branch form
and the branchless CSEL, which are chosen by a purity predicate and so a fix in
one is invisible in the other), a comprehension guard, `s and k` / `s or k`,
`assert`, and the short-circuit chain **used as a condition**. Each is a
`_emit_truthy_word` call on both backends.

**One site was found by the enumeration and NOT by reading the two backends:
`a and b` as a CONDITION.** `_emit_and_or` was already converting the chain's
LEFT operand, and the chain's RESULT is an OPERAND — so when the operand that
survives is the empty string or the empty list, the outer site tests a returned
blob ADDRESS for zeroness and gets it wrong. Measured: `f = [1]; e = []; 1 if (f
and e) else 0` printed `1` where Python prints `0`. The rule needs no kind at
all — `truthy(a and b) = truthy(a) and truthy(b)`, symmetrically for `or` — so
`_emit_truthy_word` RECURSES into both operands and never materialises the chain
as a value. arm64's branchless `and`/`or` form is additionally gated on the left
needing no conversion, because that form is branchless precisely because the left
is a load, and a `strlen` is a call that clobbers both X0 and the flags the CSEL
reads.

**Sites deliberately NOT routed, and why:**

- **`not s`** is still a refusal (`str_not_refused_because_empty_string_is_falsy`).
  It is not a wrong answer, and it is now a CHOICE rather than a limit:
  `_emit_truthy_word` can produce the honest answer here too, so the only thing
  left holding it back is that the refusal is what a test asserts today. Whoever
  wants it should delete the marker and the message together.
- **Every `CBZ`/`CBNZ`/`TEST` that tests a compiler-generated invariant** — a
  division-by-zero guard, a list slice's clamped bound, a `strlen` result of
  zero inside `count`, a blob's count against a cap, a loop counter against an
  end bound. These are not user conditions and have no kind to convert. They were
  enumerated (about 60 sites per backend) and separated from the eight above by
  asking which ones take an expression the SURFACE wrote.
- **`for x in y:`** is not a truthiness test of `y`; it is a blob walk, and
  `range` is the one iterable whose emptiness matters, which `len` already
  handles through `lowers_to_counted_blob`.

#### The empty string is the case that separates a correct lowering from a null test

`e = ""; if e:` printed `E-truthy` before and prints `E-falsy` after, on both
backends, and `while e:` did not terminate at all before (the loop body is
unreachable when the condition is an address, so nothing inside can ever change
it) and terminates after. A null test cannot tell these two apart, which is
exactly why they are in the regression suite as separate cases.

### 3. `s[1:]` refused rather than segfaulting

Both `_emit_slice_parts` now refuse a `STR_KIND` base
(`model.string_slice_refusal`). The reason is the COUNT: the copy loop reads it
from offset 0 of the object, which for a `char *` is the first eight
CHARACTERS, so the walk starts inside the string with a length taken from its own
first two letters. A suffix slice is in fact just `s + k`, an interior pointer
this path already makes for `lstrip`, so this is a missing LOWERING rather than a
missing capability — but a BOUNDED slice has no representation at all here (a
string is NUL-terminated, so a slice of a string that contained a NUL would be
silently truncated; see the cost list above), so neither does. Lowering half the
family and not the other half is how two spellings of one question come to
disagree, which is the `_emit_binop` / `_emit_branch_unless` lesson twice over.

## What was found while looking, and is NOT fixed

- **A SHORT-CIRCUIT CHAIN in a condition was a second truthiness bug**, described
  above. It is fixed; it is listed here because it was not in wave 5's list and
  not in this document's residue, and the enumeration is what found it.
- **`if []:` was a fabricated truthiness that no list had recorded.** A blob's
  truthiness is its count, and the identity test said an empty blob in a frame at
  a non-zero address was truthy. Fixed as part of the same table.
- **x86-64's `assert` ALWAYS failed.** `_emit_jcc(COND_E, fail_label)` was
  immediately followed by `asm.label(fail_label)`, so the branch had nothing to
  skip and the FALL-THROUGH path went straight into `exit(1)`. Measured:
  `assert 1` exited 1 on x86-64 and 0 on arm64. Fixed by the `jmp ok` arm64
  already had. (Found while enumerating truthiness sites, not while looking for
  a string bug; the `_emit_mov_imm(Reg.R11, 1)` next to it was also dead — R11 is
  the divisor, the shift count and the alloc size on this path and an `assert`
  does none of those — and is gone.)
- **An UNANNOTATED `String` parameter is still a fabricated truthiness.**
  `def f(s): if s:` called with `f("")` prints `1`, because `ValueKinds` seeds an
  unannotated parameter as `INT_KIND` (a word) and nothing downstream can tell a
  word from a `char *`. A `String`-ANNOTATED parameter is classified correctly and
  now answers `0 1`. This is the same gap the `ValueKinds` docstring already
  records for `print` ("A `char *` reaching print through an unannotated
  parameter is the remaining gap, and it is the gap the annotation exists to
  close") — it is now a second site rather than a new gap, and the fix belongs
  in the kind table rather than in `truthy_lowering`. **Next step:** either
  propagate the CALL SITE's argument kind into the callee (the honest answer,
  and the same by-reference question as the frame table) or refuse `if <word>:`
  when the word is unclassified, which is a much larger diagnostic surface.
  `truthy_lowering` deliberately does NOT refuse the unclassified case: an
  unclassified operand is a case where the identity test is right for every kind
  except a string, and refusing would turn every `if <unannotated name>:` in a
  codebase that annotates almost nothing into a diagnostic.
- **A comprehension over a list of STRINGS does not filter on truthiness.**
  `[x for x in ["p", "", "q"] if x]` keeps all three, because the loop variable of
  a `list:str` is typed as a word by `types.function_var_types`. Same root cause
  and the same next step as the bullet above, in the `for`-target kind.
- **`s[i]` gives the BYTE, not a one-character String.** `s[0]` is 97 on both
  backends, which is a true fact about the representation rather than a
  fabricated value, so it is left alone. **Next step:** a one-character String
  is a two-byte object and this representation has nowhere to put it — the same
  missing buffer as `upper`. It belongs in `LENGTH_DEPENDENT_METHODS` with the
  rest of that family rather than in a refusal, and it is a consequence of the
  representation decision above, not a separate bug.
- **The proving arm64 build cannot prove `len` or any string method.** Both
  pre-date the representation decision and both are outside it:
  `formal/arm64_proof_gen.py` looks for a function called `len_go` when it
  sees `len(...)` (`Unknown identifier 'len_go'`), and it raises
  `unsupported: recursion argument bound` on a program containing
  `s.startswith(...)`. Nothing since has made either worse and neither has
  been made right; the codegen change is in the `--no-prove` path the sweep
  uses.
- **`lib/ProofLib.lean` still carries two `sorry`s**, at `InImage` and
  `Semantics` (line ~4510). Pre-existing, and recorded here only so the next
  reader of the Lean side knows they are there.

## Two regressions that arrived from OUTSIDE this work, during this wave

Neither is a string problem and neither is wave 6's; both are recorded because
they move the numbers a reader of this document will compare against, and
because whoever owns them needs to know they arrived with a merge rather than
with any of the string work.

- **`ae9877d` ("Merge origin/master into master") landed on this branch
  mid-wave and its `fire_compiler.py` cannot parse `@spec(name; …)`.** The `;`
  separator inside a `@spec(...)` argument list is a `SyntaxError`:
  `1:15: Unexpected SEMICOLON(';')` for `formal/examples/fact.mojo`, at `1824fa2`
  and at `ae9877d` respectively. It is 13 files' worth of `formal/examples` (so
  `test_formal.py` reports `PASS=26 KNOWN-GAP=6 FAIL=13` on arm64 and
  `PASS=40 KNOWN-GAP=0 FAIL=5` on x86-64, of which 4 are these) and 4 files' worth
  of the repo sweep (`count`, `fact`, `fib`, `sum`). **This is the entire
  difference between the repo-scope coverage number wave 5 recorded (82/121) and
  the one this wave measures (78/121)** — not one of the four is attributable to
  any string change, and each reproduces with the `~` lexer line reverted.
  **Next step:** the `@spec` argument-list parser in `fire_compiler.py`; the
  separator is unambiguous and the fix is in the attribute-argument reader, not
  in the tokenizer.
- **`gimplerunner` fails `gimple_sorted_string_key` and
  `gimple_lambda_captures_via_default_arg`.** `sorted()` over string keys returns
  `['bb', 'a', 'ccc']` where the source says `['a', 'bb', 'ccc']`, and a lambda
  captured through a default argument returns 0 where the source says 1. Both
  pass at `1824fa2` and both fail at `ae9877d`, and both fail with the `~` lexer
  line reverted. The merge commit `21f036e` ("Determinism: sorted() the
  boxed-capture decls") is the likely owner. This is the one job that makes
  `make check` 10/11 and `make gate` red.

### Both of the above are FIXED (wave 7, agent G1) — the two owner attributions in this section were both wrong

Recorded here because this is the document a reader of those numbers will open.
Nothing about this document's own string work changed; only the two entries
above, and the two attributions they guessed.

- **`@spec(name; …)` — owner is `19bc0dd`, not the merge, and not
  `fire_compiler.py`'s tokenizer.** `19bc0dd` ("Roadmap items 0-4 rounds 1-2")
  replaced the token-skipping decorator-argument reader with a real
  `_parse_paren_args()` call, which is the right fix (`@deco` and `@deco(x)`
  had become the same node) but imposes Mojo call-argument syntax on a
  decorator whose arguments are not call arguments. Fixed forward in
  `fire_compiler.py` by `Parser._parse_decorator_args`: a decorator region with
  a **top-level** `;` becomes a new `fire_compiler.DecoratorArgs` node holding
  the `;`-separated clauses verbatim; anything else still goes through
  `_parse_paren_args` unchanged. The `;` is a sound discriminator because a
  semicolon is not valid anywhere in a Mojo expression — the same file's
  `_split_on_separators` already delegates that case to the bracketed reader.
  All 45 `formal/examples/*.mojo` parse; `fact`/`fib`/`sum`/`count` are the
  four that were broken, not 13 files. `test_examples_parse.py` (registered as
  `examples-parse`, in the `check` bucket) is the new gate.
- **`gimplerunner` — owner is `e7fc3ec`, not `21f036e`, and it is ONE runtime
  predicate, not two bugs.** `21f036e`'s `sorted(ci.mut_names)` is a pure
  declaration-order change and is innocent. `e7fc3ec` rewrote
  `mojo_boxed_is_str` (the CRASH.md fix) to call `_mojo_tagged_addr_ok`, which
  is a **struct-tag-plausibility** predicate: it requires 8-byte alignment and
  a live ≥8-byte `malloc` allocation, both of which are properties of reading
  an `int64_t __mojo_type_id` at offset 0, not of being a `char *`. A
  codegen-emitted string **literal** is a `char[N]` in `__TEXT`: measured at
  `0x1003b3ce8` and `0x102fcbd00`, both 8-byte aligned, both with
  `malloc_size == 0`, so the allocation check alone demoted every string
  literal to "not a string" — a silent wrong answer, because
  `mojo_cstr_or_int_str` then falls through to `mojo_str_from_int` and the dict
  is keyed by the decimal of its own address. Fixed in
  `runtime/fire_runtime.c` by moving the `u & 7` alignment check DOWN out of
  `_mojo_tagged_addr_range_ok` and into `_mojo_tagged_addr_ok`, so the range
  predicate is range-only — 2 GiB floor (the CRASH.md fix, and the part that
  must not be given back) and the canonical-userspace ceiling — and the two
  struct-specific checks are left to the one caller that dereferences.
  `mojo_boxed_is_str` then uses the range predicate, as it must.
  The alignment half is the one that is LATENT rather than firing today: the
  two addresses measured above happened to be 8-byte aligned, and a runtime
  probe of the real `_slit_` pool found it aligned in all 20+ variants tried
  — but a `static char * s = "bb";` gets `&7` of 7, 1, 4, 0, 3 at -O0 and -O2
  in a standalone C file, so the string path must not depend on it. The
  allocation half is the one that actually broke the two cases above, and
  `e7fc3ec`'s own refactor had already moved it out.
  Generated C is byte-identical: 664/664 stdlib modules (1,388,193 lines) hash
  the same before and after, as do both affected cases.
- **Consequence for the numbers in this section.** `test_formal.py` on arm64 is
  now `PASS=29 KNOWN-GAP=6 FAIL=10` and on x86-64 `PASS=44 KNOWN-GAP=0
  FAIL=1` — the `@spec` files build and typecheck again, so the residual
  failures are a THIRD `19bc0dd` regression in `formal/`, not string work.
  See `bugs/FORMAL_default_int_type_typed_flag_collapse.md`.


---

# Wave 8: the RETURNED half of the 16 is landed, and the other half is now a
# named crash rather than a wrong answer

This document's closing section is the one a reader of a `String` finding opens,
so the two things that have changed since it was written go here rather than
into the text above it.

## 1. `return <frame>` no longer names a String, or anything else

The 16 "a String receiver is returned/passed" findings were one construct, and
the returned half of it is now lowered. A function that returns a multi-field
struct's receiver takes one hidden trailing argument — the address of a block
the CALLER reserved, per call site, in the prologue — and `return <frame>`
becomes "copy the block there and return that word". Full design, the three
properties that make it work, the refusals that remain and the measured sweep
numbers on both machines: `bugs/FORMAL_wide_receiver_by_reference.md`, wave 8.

Measured on this repository's own arm64 sweep: the family
`frame address escapes: returned by its creator` went from **11 files to 0** and
`frame address escapes: aliased out of a method` from **3 to 0**, with **zero
files gaining a PASS** and zero losing one. The six stdlib files the snapshot
named all moved as well, four of them to a construct in a DIFFERENT module —
which is what a terminal-construct fix is supposed to produce, and it is why
none of them passes yet.

**This does not touch the collision this document is about.** The convention is
keyed on `struct_is_framed` — a purely local question — and not on any table of
names, so it is name-independent and says nothing about whether a `String` local
is a frame. The next step is still D2's, and the two are independent: the
returned half was reachable because a frame's LIFETIME had an answer, not
because its REPRESENTATION did.

## 2. The remaining half now has a reproducer, a crash, and a doc

The representation collision named above — *"a `String` local must be either a
three-slot frame or a `char *`, and today the two representations are in force
simultaneously"* — is not reachable through a `return`. It is reachable through
a constructor and it is a **SIGBUS on both machines**:

```python
struct String:
    var _ptr_or_data: Pointer[UInt8]
    var _len_or_data: Int
    var _capacity_or_data: Int
    def size(self) -> Int:
        return self._len_or_data

def main(n: Int) -> Int:
    var a = String()
    a._len_or_data = 5
    return a.size()          # SIGBUS, exit 138; the source says 5
```

`type_constructor_prefers_local_struct` only fires for
`UNREPRESENTABLE_TYPE_CTORS`, so `String()` goes down the string-conversion path
and `a` holds a `char *`; `_constructor_bindings` sees a name in
`framed_struct_names` and makes `a` a three-slot-frame holder. The store is
then through a text-section address plus 8. Two answers to one question, in one
file, and the measurement is a crash rather than a wrong number.

Full reproducer, the two candidate fixes and their blast radii, and the
denominator warning that goes with either:
`bugs/FORMAL_string_constructor_collision.md`. It is the file to read before
trying to land a `String`-shaped frame on this path.
