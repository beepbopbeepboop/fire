# FORMAL_re_the_scoped_inline_flag_form_is_refused_and_the_global_one_too_was

**Area:** FORMAL (`formal/hostmods/re.mojo`, the parser's `(?` arm) · **Status:**
the GLOBAL form is FIXED; the SCOPED form is OPEN, measured 2026-10-04 on
`work/formal24-hostmods-conformance` · **Layer:** the matcher, not the model —
the flag word is one read and a scoped flag needs it to be a mutable one

Found by generating CPython's own `test_re.py` as a conformance table
(`test_formal_hostmods_conformance.py`, the `re` group), which is a different
axis from the one `test_re_formal.py` covers: that file's corpus is
DISCOVERED from this repository's own `re.compile(r"…")` call sites, so a
construct only CPython's own suite uses was never in it.

## 1. What was red, and it was half of a feature the module already had

`formal/hostmods/re.mojo` implements all four flags as an ARGUMENT —
`re.VERBOSE()`, `re.MULTILINE()`, `re.DOTALL()`, `re.IGNORECASE()` — and
refused the spelling inside the pattern, which is the same feature twice.
Measured, arm64, status 1 is `STATUS_OK` and 3 is `STATUS_UNSUPPORTED`:

| pattern | subject | flag argument | CPython | this module (before) |
|---|---|---|---|---|
| `" a"` | `"a"` | `re.VERBOSE()` | match | match |
| `"(?x) a"` | `"a"` | none | match | **3** |
| `"^b"` | `"a\nb"` | `re.MULTILINE()` | match | match |
| `"(?m)^b"` | `"a\nb"` | none | match | **3** |
| `"a.b"` | `"a\nb"` | `re.DOTALL()` | match | match |
| `"(?s)a.b"` | `"a\nb"` | none | match | **3** |
| `"AB"` | `"ab"` | `re.IGNORECASE()` | match | match |
| `"(?i)AB"` | `"ab"` | none | match | **3** |

So the module's own docstring — "`re.VERBOSE` is implemented", "`^` and `$`
with `re.MULTILINE`" — was true of one spelling and false of the other.
CPython's `test_re.py` has `(?m)abc$`, `(?x) a`, `(?x)#x\n(?x)#y\na` and
`(?x) a| b` among the 119 cases the engine refuses.

**THE FIX IS LANDED** (commit below). `_p_inline` reads `(?letters)` at the
head of a pattern and ORs the bits into `_P_FLAGS`; nothing in the matcher
changed, because the three consumers already read that word at the right time:
`_flg` during the parse (VERBOSE starts skipping whitespace at the NEXT atom,
and `^`/`$` capture MULTILINE) and `_vm` once at entry from the finished word
(DOTALL and IGNORECASE reach `_step`). `a` and `u` are accepted and set nothing,
because the engine matches bytes and is already what `(?a)` asks for; `L` is
refused, because CPython refuses it for a `str` pattern.

**"AT THE HEAD" IS CPYTHON'S RULE AND IT IS NOT "OFFSET ZERO".**
`(?i)(?m)a` compiles and `(?i)a(?m)b` does not ("global flags not at the start
of the expression"); `(a)(?i)b` does not either. `_p_at_head` scans the
pattern's own prefix, because a node count cannot express it — a flag group
compiles to nothing, but `_p_alt` and `_p_cat` each emit a JMP first, so the
count at the first flag group is 4 and at the second is 5 (measured; both of the
first two versions of the test, `== 1` and `== 2`, were wrong for exactly that
reason).

## 2. What is still open: the SCOPED form `(?x: … )`

`re.search("(?i:a)b", "Ab")` answers 3 here and matches in CPython, as do
`"(?x: a) c"` and `"(?-i:AB)"`. Three of CPython's `test_re.py` cases are this
shape (`(?x: b)`, `(?x:#y\nb)`, `(?s:(?>.*?\\.).*)`).

**The reason it cannot be added the way the global form was**, and it is a
property of how flags are stored rather than of the parser: `_vm` reads
`flags = _pa(a, _P_FLAGS)` ONCE at entry and passes that word down to `_step`,
which tests `& F_IGNORECASE` and `& F_DOTALL`. A scoped flag changes the word
part-way through a compiled program, so the VM would have to carry a mutable
word through `_step` and restore it when the group ends — which on this path
means threading a value through the hot matcher and giving it somewhere to
live, and `_step`'s own frame budget is why several shapes here are what they
are.

Three ways out, none cheap:

1. **Bake the flags into the nodes.** Emit the effective flag word per node (or
   a new `OP_FLAGS` node the VM applies when it steps onto it). The VM's hot
   loop grows one case; the compiler has to thread the effective flags through
   `_p_group0`/`_p_group1`/`_p_piece`, which is where the four per-piece words
   moved to frames for exactly this class of reason.
2. **A mutable arena word** for the VM's current flags, saved and restored by
   new `OP_SAVE_FLAGS`/`OP_RESTORE_FLAGS` opcodes at the group's boundaries.
   Same hot-loop cost, and it needs a save slot the arena may not have.
3. **Compile the scoped group twice**, once per flag combination, and pick the
   program at run time. No matcher change at all, and the program array is the
   thing that has to be big enough for it — `_MAXPAT`/`_NNODES` are the limits
   that would move.

**THE NEXT STEP, concretely:** (1), with `_p_group`'s `(?` arm taking the
flag letters, an effective-flag word in the piece frame (`_pf` already has the
frame mechanism), and the two new opcodes. The acceptance test already exists —
`test_re_formal.py`'s `test_the_scoped_flag_form_is_refused_and_named` asserts
the refusal, so the fix makes it red and the row turns over.

## 3. What is NOT part of this

The other 116 refusals out of CPython's 184 harvested cases are possessive
quantifiers (`*+`, `++`, `?+`, `{m,n}+`), atomic groups (`(?>…)`),
lookaround, backreferences, conditional groups (`(?(1)…)`), `\N{…}` and the
nested-quantifier recursion guard. Those are the module's documented subset
(`formal/hostmods/re.mojo`'s "THE SUBSET" and "WHAT IS NOT HERE" sections) and
each is a language feature rather than a spelling of one this module has, so
this document is about the ONE that was a spelling and not a feature.

## 4. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label re -- python3 test_re_formal.py
python3 tools/memslot.py --gb 8 --label conf -- \
    python3 test_formal_hostmods_conformance.py -v re
python3 tools/memslot.py --gb 8 --label cases -- \
    python3 test_formal_hostmods_conformance.py --cases re --limit 200

sed -n '/^def _p_inline/,/^def _p_at_head/p'      formal/hostmods/re.mojo
sed -n '/^def _p_at_head/,/^def _p_flagok/p'      formal/hostmods/re.mojo
grep -n "INLINE_FLAG_PAIRS\|SCOPED_NOT_YET"      test_re_formal.py
```