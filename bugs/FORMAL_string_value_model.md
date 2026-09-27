# FORMAL_string_value_model: what a string IS on the formal path, and the two things that want to be one

**Status:** the representation question is DECIDED and the decision is landed.
The string stays a bare `char *`; the length and the content equality are
recovered as *computations* over that one word rather than as fields, and the
two wrong answers that followed from not doing so are fixed on both backends.
Wave 5 then closed the two items this document left named (`in` and `+=`) and
found the same defect class in **eleven more operators** — every one measured,
every one refused, and the residue written down at the bottom with a next step
for each. What is still NOT fixed, and is the larger thing, is the collision
between that representation and the stdlib's own `String` struct — which is
what all 16 of the "a String receiver is returned/passed" refusals in the stdlib
sweep actually are, and which is not a string-value-model problem at all.

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

## Also found, and NOT fixed — the residue, with the next step for each

These are the ones wave 5 found and did **not** close. Each says what it would
take.

- **`~` never reaches the parser, so `~s` silently means `s`.** This is the
  only one of the twelve operators above that is still lowered, and the reason
  is not in `formal/`: `fire_compiler.py`'s `_TOKEN_RE` has no `~` in its `OP`
  alternation, and `py_tokenize` drops `UNK` tokens without a word
  (`if kind in ("WS", "UNK", "XFER"): continue`). So the `~` is gone before
  `Parser._parse_unary` — whose `t.value in ("-", "+", "~")` branch is correct
  and unreachable — ever sees it. Measured: `r = ~s; printf("%d", r)` prints
  **77693904** on arm64 and **74486761** on x86-64, and the AST contains
  `AssignStmt(target=r, value=IdentExpr(s))` with no `UnaryOp` in it at all.
  **Next step:** add `~` to the `OP` group in `_TOKEN_RE` (it is unambiguous, so
  its position in the alternation does not matter). Nothing else is needed:
  `model.string_unary_refusal` already refuses `~` on a string and both
  backends already ask for it, and x86-64's `_emit_unary` already has a
  `~` branch. `fire_compiler.py` was read-only for wave 5 and this is why.
- **`if s:` and `while s:` are still a fabricated falsity, and `not s` is now a
  refusal instead.** A string is a pointer and a pointer is never zero, so
  every string is truthy here INCLUDING THE EMPTY ONE. Measured, both
  backends: `s = "abc"; e = ""; if s: …; if e: …` prints `S-truthy` and
  `E-truthy`. `not s` was the same defect in an expression position and IS now
  refused (`str_not_refused_because_empty_string_is_falsy`), because at a
  `UnaryOp` site the emitter can see the operand's kind.
  **Next step:** the condition sites are the remaining half, and they are a
  *helper*, not a check: one `_emit_truthy(expr, reg)` on each backend that,
  when `expr`'s kind is `STR_KIND`, emits the `strlen` and tests THAT, and
  otherwise emits the CBZ/TEST it emits today. The honest test is
  `strlen(s) != 0`, which is the same computation `len` already makes with a
  symbol both backends already call. Every truthiness site has to go through
  the helper or the two spellings disagree again, which is the lesson of the
  `_emit_binop` / `_emit_branch_unless` pair above. Until then `len(s) == 0`
  is the spelling to write, and the refusal says so.
- **`s[i]` gives the BYTE, not a one-character String.** `s[0]` is 97 on both
  backends, which is a true fact about the representation rather than a
  fabricated value, so it is left alone. **Next step:** a one-character String
  is a two-byte object and this representation has nowhere to put it — the same
  missing buffer as `upper`. It belongs in `LENGTH_DEPENDENT_METHODS` with the
  rest of that family rather than in a refusal, and it is a consequence of the
  representation decision above, not a separate bug.
- **`s[1:]` — a SLICE of a string — segfaults on both backends** (exit 139).
  A crash rather than a wrong answer, and the same class: a slice is a blob
  operation and a string is not a blob. A suffix slice is in fact just
  `s + k`, an interior pointer this path can already make, so it is a
  *lowering* rather than a refusal. **Next step:** refuse it in
  `_emit_slice_parts` for a `STR_KIND` base until someone wants the lowering;
  nothing is currently wrong-but-quiet here, so it is lower priority than the
  truthiness helper above.
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
