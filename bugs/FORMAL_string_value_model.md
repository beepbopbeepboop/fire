# FORMAL_string_value_model: what a string IS on the formal path, and the two things that want to be one

**Status:** the representation question is DECIDED and the decision is landed.
The string stays a bare `char *`; the length and the content equality are
recovered as *computations* over that one word rather than as fields, and the
two wrong answers that followed from not doing so are fixed on both backends.
What is NOT fixed, and is written down at the bottom, is the collision between
that representation and the stdlib's own `String` struct — which is what all 16
of the "a String receiver is returned/passed" refusals in the stdlib sweep
actually are, and which is not a string-value-model problem at all.

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

## Also found, deliberately NOT fixed

- **`"x" in s` with a string on the right SIGBUSes** on both backends (a crash,
  not a wrong answer, and the two architectures agree). It belongs to whoever
  owns `_emit_membership`; the fix is the same shape as the rest of this
  document — `strstr(s, x) != NULL`, and `strstr` is already emitted by both
  backends for `find`.
- **`+=` on a string is not intercepted**, only `+` (the two `_emit_binop`
  entry points are covered; the augmented-assign path is not). Same wrong answer
  as `+` — an address added to an address — so it is a real gap in this change,
  and the fix is one call to `model.string_concat_refusal` in each backend's
  augmented-assign emitter.
- **The proving arm64 build cannot prove `len` or any string method.** Both
  pre-date this change and both are outside it: `formal/arm64_proof_gen.py`
  looks for a function called `len_go` when it sees `len(...)`
  (`Unknown identifier 'len_go'`), and it raises
  `unsupported: recursion argument bound` on a program containing
  `s.startswith(...)`. Nothing here made either worse and neither was made
  right; the codegen change is in the `--no-prove` path the sweep uses.
- **`lib/ProofLib.lean` still carries two `sorry`s**, at `InImage` and
  `Semantics` (line ~4510). Pre-existing, not this change's, and recorded here
  only so the next reader of the Lean side knows they are there.
