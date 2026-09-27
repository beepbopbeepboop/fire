# PARTIAL — 5 of 6 items fixed, plus 3 found alongside; item 6's repr half is residue

**State: OPEN, one named residue.** Closed 2026-09-27: items 1-5 and 6b,
the `isprintable`/`isnumeric` decision, and three further wrong values found
while verifying them. Not closed: 6a, `partition`/`rpartition`'s container
TYPE (the repr is fixed; the type is not, and cannot be without a tuple
type — see the residue).

Every "before" below is real, not reconstructed: a throwaway copy of the
working tree at `/tmp/br/before_tree` with this task's hunks surgically
reverted and the two runtime files at `HEAD`, run through the same harness
(`/tmp/br/brrepro.py <tree> <file.mojo>`, which imports the compiler from
the tree it is given and asserts it). The "after" is the working tree.

## What was wrong, item by item, with the evidence

### 1. `ljust`/`rjust`/`center` with a bytes fill char — FIXED

The doc's root cause was right (`_opt_arg(..., 'int64_t', ...)` ran
`_to_int64` on a `MojoBytes *`, a pointer-to-integer cast), and the symptom
was as bad as described: the fill byte was the low byte of a heap address,
so the output changed from run to run.

    # BEFORE (item1.mojo)                    CPython
    b'a'.ljust(4, b'.')  ->  b'a\x80\x80\x80'   b'a...'
    b'a'.rjust(4, b'.')  ->  b'\x10\x10\x10a'   b'...a'
    b'a'.center(4, b'.') ->  b'\xb0a\xb0\xb0'   b'.a..'
    b'a'.ljust(5, 46)    ->  b'a....'           TypeError

    # AFTER
    b'a\x80\x80\x80'  ->  b'a...'      (and the other three match)

Fix: `_bytes_fill_char` in `mojo/backend_gimple/emit_methods.py` resolves
the fill in whichever domain it was spelled in — a `MojoBytes *` goes
through the new `mojo_bytes_fill_byte`, an int stays the int. The length
check is in the runtime because the fill is not a compile-time constant,
and it RAISES: `mojo_bytes_fill_byte` on a length != 1 raises TypeError
rather than silently padding with the first byte, which is what a
length-tolerant version would do.

**The int spelling is kept, deliberately.** `b'a'.ljust(5, 46)` is a
TypeError in CPython — the bytes spelling is the only one it accepts. The
int form is a fire extension the repo's own corpus uses, so removing it
would be a separate, larger decision than this bug; the fix here is that
the CPython spelling now works too, not that the extension went away.
**This is a divergence from CPython, recorded here so it is not rediscovered
as a bug.**

Two more wrong values in the same four lines, both found while fixing this
one and neither in the original report:

- **`center` put the odd pad byte on the wrong side.** `mojo_bytes_pad`
  used `floor(total/2)`, and its own comment claimed that is "what Python
  does" — it is not; CPython uses `marg // 2 + (marg & width & 1)`.
  `b'ab'.center(5, b'.')` printed `.ab..` where CPython prints `..ab.`.
  The same `floor` bug was in the `str` padders (`_str_pad`), so both are
  fixed through one shared helper (`_center_left`).
- **`width` as a keyword was read as the fill.** `width =
  _to_int64(*arg_pairs[0])` took the first POSITIONAL, so
  `b'a'.ljust(width=4, fillchar=b'.')` padded to the width of the FILL and
  printed `b'a'`.

### 2. Every empty-bytes predicate returns `True` — FIXED, and it was three bugs

`mojo_bytes_is` had `if (b->len == 0) return 1; /* every bytes.isX() is
True for b'' */` — the comment is false, and it was hiding two more wrong
answers in the non-empty case that the doc did not have:

| | CPython | before | after |
|---|---|---|---|
| `b''.isalpha()` | False | **True** | False |
| `b'ab1'.islower()` | True | **False** | True |
| `b'1'.istitle()` | False | **True** | False |

`islower`/`isupper` were clearing their all-cased flag on any UNCASED
character (a digit, `_`, a space, a non-ASCII byte) — Python ignores
uncased characters for those two, which is the whole difference between
`b'ab1'.islower()` and `b'ab'.isalpha()`. `istitle` returned true for any
string with no title-case violation, including one with no cased character
at all.

The root cause of all three is that the character-class predicates existed
TWICE — a hand-written `mojo_str_isX` per predicate (correct, it mirrors
CPython's defs) and a separate `mojo_bytes_is` switch (wrong). They are now
ONE kernel, `mojo_is_kind` in `fire_runtime.c`, with every case
transcribed from CPython's own definitions; `mojo_bytes_is` and all ten
`mojo_str_isX` are thin wrappers over it. Verified by differential test,
not by inspection: **4192 (bytes-predicate, value) pairs — all 256 single
bytes, all 2-byte combinations over a 17-character representative alphabet,
and assorted multi-byte samples — 0 diffs**; **1690 `str` pairs, 4 diffs,
all pre-existing representation limits** (below).

### 3. `memoryview(...).readonly` is a constant `False` — FIXED

    # BEFORE                              CPython
    memoryview(b'abcd').readonly -> False    True
    memoryview(bytearray(b'ab')).readonly -> False  False   (right by luck)
    memoryview(bytes(ba)).readonly -> False  True

The fold's own reasoning was "this representation is always a writable 1-D
byte window" — a true statement about the WINDOW and an irrelevant one
about the ANSWER, which is the mutability of the object the view was taken
over. `MojoBytes` now carries a `readonly` flag (1 from the single
allocator, cleared by the bytearray constructors and by an explicit
`mojo_bytearray_mark` at the one call site that builds a bytearray out of a
SHARED bytes constructor), `MojoMemoryView` inherits it, and the descriptor
is a query.

Note there were TWO fold sites — the member read (`emit_exprs.py`) and the
call form (`emit_methods.py`) — and the member read is the one the test
exercises. Both now ask the runtime.

### 4. `dict.get` / `dict.pop` with a bytes key read the str domain — FIXED

    # BEFORE (item4.mojo)                 CPython
    d[b'a'] = 7; d.get(b'a')   -> 0            7
    d.pop(b'a'), len(d)        -> 0, 1         7, 0
    f[b'k'] = 3; f.get(b'k')   -> 0            3
    # AFTER: all four match CPython

The doc's diagnosis was exact: the runtime halves existed and were correct,
the call sites never named them. `get` and `pop` each called
`_char_to_cstr` unconditionally and then emitted the str-domain helper,
while `setdefault` guarded. Rather than add a third copy of that guard, all
three now go through one `_dict_key_probe`, which answers "which key domain
is this?" once — a question the next reader cannot forget, which is exactly
how `get`/`pop` forgot it.

Two things surfaced while routing `pop`:

- **`pop` had no default and no value domain.** `mojo_dict_pop_int` takes
  two arguments and answers 0 for a missing key, so Python's
  `pop(k, default)` could not be expressed on the str path at all; and a
  bytes-keyed dict holding STRINGS popped its value as a raw pointer
  decimal (`mojo_dict_pop_bytes_int` on a `char *` slot). Added
  `mojo_dict_pop_bytes_str` / `_double` over one shared body, mirroring
  `get`'s three.
- **`get`/`pop` were right about the key and wrong about the value domain
  together.** The fix pairs them (`_sfx` in `get`, `val_type` in `pop`)
  rather than fixing one and leaving the other able to drift again.

### 5. The bytes set domain is one-per-FUNCTION — FIXED, and it was never about bytes

The doc reports this as "the bytes set domain is one-per-FUNCTION" and
"a real limit that was not recorded anywhere". Both halves are wrong about
the cause:

- It is NOT the set domain. `for x in {1, 2}` followed by
  `for x in {'p', 'q'}` failed identically, with
  `assignment to 'int64_t' from incompatible pointer type 'char *'`.
- It is NOT a limit. It is `_declare_var`'s deliberate first-decl-wins rule
  (its docstring says "Load-bearing; do not change") applied to a loop
  TARGET, which is not a read of an existing name: `for x in <A>` then
  `for x in <B>` REBINDS x, and if A and B have different element domains
  the second loop wrote into the first loop's variable.

    # BEFORE: hard gcc -fgimple error, in every domain pair
    # AFTER:  all four loop correctly
    for x in {b'a', b'b'}: print(x)   ->  b'a'  b'b'
    for x in {'p', 'q'}:   print(x)   ->  p  q
    for x in {1, 2}:       print(x)   ->  1  2

Fixed by giving `_gen_for_set` the existing `force=True` path, which mints
a fresh C name and repoints `_c_names[var]` — which is also the correct
Python reading, since after the second loop `x` holds the second loop's
last element.

**Related, NOT fixed, and it is worse than the loud version:** the same
first-decl-wins rule on the LIST loop path does not error, it prints
pointer decimals.

    for x in [1, 2]:     print(x)   ->  1  2
    for x in ['p', 'q']: print(x)   ->  4332420456  4332420464   # addresses

That is a silent wrong value where item 5 was a loud one, it is in the same
helper family, and it is the next thing to pick up. Not attempted here: the
list path's element typing is read through `_elem_of` in several other
places, so the blast radius is much wider than the set path's, and nothing
in this doc's six items covers it.

### 6. Type-only residue

**6a. `partition`/`rpartition` return a `MojoList *`, not a tuple. NOT
FIXED — the repr is, the type is not.** The repr was the whole observable
difference and it is now right: the result carries
`mojo_mark_as_tuple`, the same marker a tuple LITERAL lowers to, so
`print(b'a=b'.partition(b'='))` is `(b'a', b'=', b'b')`. What is still
wrong is the container TYPE: `type(p)` prints a pointer decimal, and `p` is
genuinely a list — it can be appended to, where CPython's tuple cannot.

It is not fixable inside the bytes path, and that is the finding. **This
runtime has no tuple type at all**: a tuple literal lowers to a plain
`MojoList *` and is distinguished only by the `mojo_mark_as_tuple` marker,
exactly as `partition`'s result now is. So "return a tuple" means
introducing tuple-ness into the representation, which is a change to every
container lowering in the backend — not a bytes fix. Recorded here rather
than attempted.

**6b. `'a' in [b'a', b'b']` — FIXED.** The doc calls this "a pre-existing
mixed-domain query" and a hard type error; that is right, and it is also
answerable. A non-bytes needle against a list of bytes is not a comparison
the runtime can perform, and the two domains already imply the answer:
`b'a' == 'a'` is False for every pair, so `'a' in [b'a', b'b']` is False.
It used to cast the `char *` needle to `MojoBytes *` — a pointer cast gcc
rejects — so it now folds to the answer the domains imply, which is what
the dict branch a few lines below already did for the same shape.

## Found while verifying: three more wrong values, all fixed

None of these are in the original six. Each was found by running a
differential test over the surface being fixed, not by reading code.

- **`partition`/`rpartition`'s no-match arms were SWAPPED.**
  `b'abc'.partition(b'=')` returned `(b'', b'', b'abc')` and
  `b'abc'.rpartition(b'=')` returned `(b'abc', b'', b'')` — each gave the
  other the answer, on the common case of a separator that is not present.
- **An empty separator is a `ValueError` in CPython** and was answered
  `(b'', b'', b'a=b')`. Needed a real catchable `ValueError`, so
  `mojo_raise_value_error` was added next to its three existing siblings
  (same mechanism, same `crc32("ValueError")` tag derivation).
- **`str.isprintable`/`isnumeric`/`istitle`/`isascii` did not exist at
  all** on the compiled path and answered a raw int `0` from the generic
  unknown-method stub — printed as `0`, not `False`. `"1".isnumeric()`
  printed `0` where CPython prints `True`. See the decision below.

## The two tests that asserted the wrong answer

Both are now correct, and **both were wrong, not stale** — the values they
expected are values CPython does not produce.

| test | before | after | why the before was wrong |
|---|---|---|---|
| `gimple_bytes_predicates` | `True True True\nTrue True True\nTrue True True\nFalse False False\nTrue True\n` | `True True True\nTrue True True\nTrue True False\nFalse False False\nFalse False\nFalse False False False\nFalse True\nTrue True True True\nFalse False True False\nTrue False\n` | Line 3 asserted `b'a b'.isprintable() == True`; `isprintable` is a `str` method and `b'a b'.isprintable()` is an `AttributeError`. Line 5 asserted `b''.isalpha(), b''.isdigit() == True, True`. Rows for `islower`/`isupper`/`istitle` over non-cased characters are new. |
| `gimple_memoryview_descriptors` | `4 1 B\nb'abcd'\nFalse True\n4\n` | `4 1 B\nb'abcd'\nTrue True\n4\nFalse True\nTrue False\nTrue True\nFalse\n` | `readonly` over a `bytes`-backed view is `True` in CPython — the view is over an immutable object. The added rows pin the bytearray-backed case, which must stay `False`. |

**`gimple_str_predicates` is a new case** for the four `str` predicates that
did not exist before. It carries its limitation in a comment rather than
hiding it: the kernel works over a UTF-8 byte window with no Unicode
category table, so a non-ASCII char is "in no ASCII class" —
`'é'.isalpha()` and `'²'.isnumeric()` are False here and True in CPython.
That limit already applied to `isalpha`/`isalnum`/`isdigit`/`isspace`
before this change; `isprintable` is exact over ASCII and over the C1
control block.

## The `isprintable`/`isnumeric` decision: REMOVED from `bytes`, ADDED to `str`

The doc asked for a decision and recorded the reasoning to be checked:
"Python defines only the ASCII flavours of these on `bytes`", which is
factually wrong — CPython's `bytes` predicates are exactly `isalnum
isalpha isascii isdigit islower isspace istitle isupper`, and
`b'a'.isprintable()` is an `AttributeError`.

**Removed from `bytes`, because three sources agree it should not be
there and only one dissented:** CPython raises; this compiler's own
interpreter reference (`myinterpreter.py`) leaves it to Python's `bytes`,
so it raises there too; and the one dissenter was the code being fixed. An
implemented-but-not-in-the-language method can only ever produce a silently
wrong value, which is the entire class of bug this doc is about. The honest
answer is a real `AttributeError` naming CPython's message, and that is
what it now raises — pinned by `gimple_bytes_isprintable_raises` /
`..._isnumeric_raises`.

**Added to `str`, because there they DO exist and this path answered a
silent `0`.** `"1".isnumeric()` printing `0` is strictly worse than an
approximation. The approximation is the pre-existing ASCII-only one, stated
in the test's comment.

Also: the doc's claim that `b'a'.isnumeric()` returned `True` is **not
reproducible** — it returned `False` (the `MOJO_BYTES_IS_NUMERIC` arm is
the same test as `MOJO_BYTES_IS_DIGIT`, so `b'a'` was already correctly
`False` and `b'1'` was correctly `True`). The predicate existed with
roughly the right answers and the wrong type; what was wrong was its
EXISTENCE, not its value. The str-side `isnumeric` really was `0` for
everything.

## Known limitation, unchanged by this work

The `str` predicates (all ten, including the six that predate this change)
classify over a UTF-8 byte window with no Unicode category table, and a
`str` is a NUL-terminated `char *`, so a string containing an embedded NUL
is seen as ending there (`'\x00'.isprintable()` answers True, from the
empty-string vacuous case). Both are properties of the `char *`
representation, not of the kernel, and both are recorded in
`gimple_str_predicates`'s comment.

## Gate

`check` 7/7. `stdlib` 2/2, `skip <module>:` count 0 before and after.
`compile_stdlib.py` `PASSED: 664 / FAILED: 0 (0 expected, 0 unexpected)`
run against an EMPTY CAS (`GMOJO_HOME=/tmp/br/freshcas2`, `Codegen CAS:
0/664 hits`), so `U` did not increase — the 664/664-hit line a warm run
prints is not that evidence, and the CAS key folds in
`compiler_fingerprint()` precisely so a codegen edit cannot be served from
cache. `test_gimple_runner.py` 134/134, `test_gimple_generator_runner.py`
151/151, `test_gimple.py` 324/324, `test_no_new_container_casts.py` 34
casts (baseline, unchanged).

For the standard CLAUDE.md sets for a change that is *supposed* to be
behaviour-preserving, the emitted C is byte-identical before vs after on
ten large succeeding stdlib modules — `dict.mojo` (310 KB), `string.mojo`
(357 KB), `string_slice.mojo` (344 KB), `list.mojo`, `counter.mojo`,
`set.mojo`, `file.mojo`, `sort.mojo`, `math.mojo`,
`parsing_integers.mojo` — with the CAS bypassed, so the comparison is on
the compiler's work and not a cache hit. **This change is not
behaviour-preserving** (that is the point), so that check is here to bound
the blast radius, not to claim equivalence: the C for those ten is
unchanged, and every difference this work makes is on a bytes/memoryview/
dict-key path.

## Not exercised

- `native` and `bootstrap` were not run (exclusive, shared `fire.ci`), per
  the assignment. The human's `make gate` covers them.
- Nothing in `formal/`, `lib/*.lean`, `test_formal*.py` or `test_x86_64_*`
  was touched or run.
