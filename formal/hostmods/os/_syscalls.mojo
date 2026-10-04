"""The C library this module needs, and nothing else.

Every call into libSystem that `os`, `os.path`, `platform` and `shutil` make is
spelled here, once, and nowhere else. Three reasons, in the order they mattered while
writing it.

  `platform` is here for the same reason the other two are, and it is worth
  being explicit about why it is NOT a second copy. `formal/hostmods/
  platform.mojo` needs the string primitives below for its own reasons — a
  kernel string lives in a buffer the C library fills and a caller cannot keep
  — so it imports from here either way, and the moment it did, a second
  `str_alloc` in `platform.mojo` would be a second implementation of a routine
  whose whole value is being the same one everywhere. `uname(3)` and
  `sysctlbyname(3)` therefore joined the set below rather than appearing
  beside it.

1. A NAME COLLISION IS A SILENT RECURSION. A call is extern exactly when the
   name is not a function of the unit being compiled
   (`formal/arm64_codegen.py:_emit_call`, `name not in self._functions`), so a
   unit that both defines `getcwd` and calls the C library's `getcwd` emits a
   call to ITSELF with the wrong arity. `getcwd`, `chdir`, `chmod`, `remove`,
   `unlink`, `rename`, `getenv`, `mkdir` and `realpath` are all both libc
   functions and the names this module's API wants, so the wrappers live in
   their own unit and the API modules see a function call.

2. THE SET IS AUDITABLE. A formal image links libSystem and nothing else
   (FORMAL.md §1), so "what does this module ask of the operating system" is a
   question with a short, complete answer, and it is the answer in this file.
   Every name below was measured to bind on this target before it was relied
   on.
`shutil` is in the list because it is the one module in `formal/hostmods/`
  that COPIES BYTES, and the stdio calls are how: `fopen`/`fwrite`/`fread`/
  `fclose` rather than the three-argument `open`/`write`/`read`, because
  `fs_open_ro` below says in so many words that this path lowers `open` itself
  and refuses the C library's own spelling of it — there is no `open(p, flags,
  mode)` to call. A `FILE *` is a POINTER, so it is a word, and `fopen` takes a
  MODE STRING, which is the one thing this path does have a literal spelling
  for. `fs_read`'s docstring says "this path has no `FILE`", which is about the
  struct and not about the pointer and is worth keeping in mind when reading
  the two against each other: there is no `FILE` to declare a field on, and
  every `FILE *` is one word, which is all a descriptor needs to be.

  `signal` is in the list for the same reason and by the same rule, and it is
  the one case where the collision is not avoidable by renaming the WRAPPER:
  CPython spells its own wrapper `strsignal`, so the name this tree wants is
  the name the C library already has, and the two implementations have to live
  in different units. `fs_strsignal` below is the whole of it.


3. THE STRING PRIMITIVES ARE NOT STRING FEATURES. Concatenation, `strip`,
   `replace` and `split` are refused on this path because a string is a bare
   NUL-terminated `char *` in a read-only text section with no heap to grow
   into (bugs/FORMAL_string_value_model.md). That does NOT make a new string
   impossible: `malloc` is in libSystem, and a buffer it hands back IS
   writable. So a string this module returns is either an INTERIOR POINTER
   into its input (no allocation, and the caller's buffer outlives the call) or
   a `malloc`'d buffer that the caller owns for as long as it wants it. That
   is the whole of the string story, and it is why there is no `+` here: the
   concatenation is `str_build`, which is a `malloc` and three `memmove`s.

WHAT IS NOT HERE, AND WHY — each measured on this target before it was left
out rather than guessed at:

  * BOTH BACKENDS TODAY, and not because of anything in this source. This used
    to say a module dylib that makes a call into the C library is arm64-only on
    this backend, and it was false: every function below builds and RUNS under
    `--backend=x86_64`, which is what `test_formal_os_backing.py` measures on
    both architectures with CPython as the arbiter. The one thing the x86-64
    backend has to get right, and now does, is the SYMBOL each call binds:
    macOS exports `readdir`, `opendir`, `stat` and the rest of this file's
    entry points twice — once for a 32-bit `ino_t` and once for a 64-bit one —
    and on x86-64 the bare name is the 32-bit function, whose `struct dirent`
    and `struct stat` are laid out differently. `formal/model.py`'s
    `target_libc_symbol` is that table;
    `bugs/FORMAL_x86_64_byte_read_of_a_libc_returned_pointer_reads_the_wrong_bytes.md`
    records what reading the wrong one of the two costs. A host with no x86-64
    support at all still skips the x86-64 half of the suites.

  * BYTE READS. `p[0]` on a `Pointer[UInt8]` is a one-byte load now. It used to
    take the blob path in `_emit_subscript_addr`, which reads a COUNT from
    offset 0 and bounds-checks against it: `byteat("ab")` returned
    -1879048144, which is `ab` plus whatever follows it in the text section,
    read as a little-endian word. A subscript on a base with a DECLARED
    pointee is routed through the pointer value model now
    (`model.subscript_base_lowering`), so `p[i]` and `p.value()` are the same
    load at the same width. The `UInt8` ANNOTATION on the parameter is what
    makes it so, and it is why every reader below takes `b: Pointer[UInt8]`.
    (bugs/FORMAL_subscript_of_a_pointer_reads_a_blob_count.md.)

  * `len()`. It is a builtin whose kind comes from the call site, and a value
    that arrived from a call is classified as a word, so `len(p)` on a
    `char *` this module received is refused. `str_len` is `strlen`, which is
    the same computation with no kind to guess.

  * **`p + k` IS BYTE ARITHMETIC, AND THE ONLY THING THAT STOPS IT BEING A
    SILENT WRONG ANSWER IS THE SUBSCRIPT.** `p[i]` on a base with a declared
    pointee scales by that pointee's width — that is `p[i]` at the width, and
    `listdir`'s `b[1 + n]` depends on it — but `p + k` adds the RAW INTEGER, on
    every architecture, for every pointee width. Measured here, both
    architectures, over five spellings of the same arithmetic so that the shape
    of the expression is not what decides it:

        var b: Pointer[Int64] = malloc(8 * 64)      # base
        b + 1              -> base + 1     (not base + 8)
        b + n              -> base + n     (not base + 8n)
        b + 1 + 2 * n      -> base + 1 + 2n
        b + (1 + 2 * n)    -> base + 1 + 2n
        b + 8 * (1 + n)    -> base + 8 + 8n

    `bugs/FORMAL_pointer_value_model.md` §9 records this as open with the next
    step (`_emit_binop` is the hottest site in both backends and scaling there
    wants its own diff), and what is written there is about a DEREFERENCE: the
    guard refuses `q = p + k` when the pointee is wider than a byte AND
    something dereferences `q`. **Passing the same expression as an ARGUMENT is
    not a dereference, so nothing refuses it** — `memset(b + 1 + 2 * n, 0, 16)`
    on an `Int64` blob compiles, links, runs, and zeroes sixteen bytes at
    offset 107 of a blob whose pairs live at 8-byte offsets. That is not a
    second defect; it is this one with the guard out of the way, and it is worth
    a paragraph here because the trap is invisible: `formal/hostmods/os/
    __init__.mojo`'s `environ_set` had that memset for one build and the image
    corrupted a heap-allocated blob at a word that no line of the source
    mentions. **So: address a wider-than-byte blob with `b[i]`, never with
    `b + i`,** and every `memmove`/`memset`/`strchr` call below that offsets a
    `Pointer[UInt8]` is fine as it stands because byte is the scale there.

  * `ord`/`chr`/`str`. There is no builtin by those names here; a call to one
    is an unbound extern, and `str(65)` segfaults.

  * `errno`. The C library's accessor is `__error`, and a leading underscore in
    a callee name is not a symbol this path can bind — the image fails to load
    for a name nothing provides. Callers that need to distinguish "already
    there" from "could not be made" ask `isdir` instead, which is a fact rather
    than an error code.

  * `stat`'s STRUCT is not a blob and is not read as one. The out-parameter is
    a `malloc`'d byte buffer and the fields come out of it ONE BYTE AT A TIME at
    the offsets this target's own `struct stat` puts them at, which is a
    property of the ABI rather than of the source and is written down in full
    under `ST_DEV` below. The general half — a struct read for a struct the
    SOURCE declares — is still not possible, and nothing here pretends to do
    it: see `bugs/FORMAL_pointer_value_model.md`. What changed is that the
    buffer is readable at all, so `st_mode` is a value and `isfile` is
    CPython's answer rather than an approximation of it.
"""

# ── Memory: a buffer, and the only two ways a string is built here ──────────
#
# `malloc` is the heap this path does not otherwise have. A buffer it returns
# is ordinary writable memory, and `memmove`/`memset`/`strcat` write into it
# normally — that is the whole reason a new string can exist on a target whose
# string representation has no growable buffer of its own.

def str_alloc(n) -> str:
    """A writable, ZEROED buffer of at least `n` bytes plus a terminator.

    `n + 1` rather than `n`: every buffer here holds a NUL-terminated string,
    and a caller that asks for a copy of `n` bytes still needs somewhere to
    put the terminator. The result is a `Pointer[UInt8]` on purpose — that
    annotation is what tells the rest of the path this word is a string and
    not a number, and it is what `printf("%s", …)` reads.

    Zeroed, not just allocated. `malloc` returns whatever was there, and three
    of the four ways a string is built here start with a `memmove` or a
    `strcat` — a `strcat` onto an uninitialised buffer appends after the
    garbage, and the result is a string with someone else's bytes in the
    middle of it. Paying one `memset` to make every buffer's initial content
    defined is cheaper than finding that once per buffer.
    """
    var p: Pointer[UInt8] = malloc(n + 1)
    memset(p, 0, n + 1)
    return p


def str_copy(dst, src, n) -> str:
    """`n` bytes of `src` into `dst`, then a NUL. Returns `dst`.

    `memmove`, not `memcpy`: the two ranges may overlap, and a caller copying
    a prefix out of a string that starts at the same buffer is not a mistake
    worth a wrong answer.
    """
    memmove(dst, src, n)
    memset(dst + n, 0, 1)
    return dst


def str_trunc(dst, used) -> str:
    """Cut the NUL-terminated string in `dst` back to `used` bytes.

    The only way a string gets SHORTER on this path. There is no `rstrip` and
    no slice: a string is a bare `char *` into a read-only text section, so
    there is nowhere to write a terminator earlier except into a buffer this
    module allocated — which is why every function that trims copies first and
    why the result is a fresh string rather than the receiver.
    """
    memset(dst + used, 0, 1)
    return dst


def str_put(dst, used, src, n) -> int:
    """Append `n` bytes of `src` at `dst + used`, NUL-terminating. New `used`.

    The append form of `str_copy`, and it re-terminates because a scan over a
    partly built string has to stop at the end of what is written, not at
    whatever the buffer contained before.
    """
    memmove(dst + used, src, n)
    memset(dst + used + n, 0, 1)
    return used + n


def str_append(dst, src) -> str:
    """`src` onto the end of the NUL-terminated string in `dst`. Returns `dst`.

    `strcat` for the same reason `str_copy` is `memmove`: the C library's
    algorithm is the answer, and a second implementation of it is a second
    thing to be wrong.

    **IN PLACE, AND THE ROOM IS THE CALLER'S TO PROVIDE.** This writes
    `strlen(src) + 1` bytes at `dst + strlen(dst)` and nothing checks that they
    fit, so a `dst` sized for its own string alone is overrun by every byte of
    `src`. That is not hypothetical and it was in this tree until 2026-10-04:
    `os/path/__init__.mojo`'s `join` built `str_dup(a)` — a block of
    `strlen(a) + 1`, room for `a` and its terminator and nothing else — and
    handed it here to append `b`, so every byte of `b` and its terminator landed
    past the end of the allocation while `join`'s ANSWER stayed correct and every
    differential test of it passed. It showed up as a `SIGABRT` from a caller
    (`formal/hostmods/glob.mojo`'s `**` walk, 10 runs in 10) rather than as a
    wrong string, which is the usual way a heap overrun presents.

    So: `str_build(a, b)` when the answer is a NEW string, which is the shape
    almost every caller wants and is what sizes the allocation correctly; and
    this only when the destination is a buffer with room already reserved for
    the append.
    """
    strcat(dst, src)
    return dst


def str_dup(s) -> str:
    """A `malloc`'d copy of `s`. The caller owns it.

    This is the only allocation in the module that a caller has to think about.
    Everything else that returns a string either returns its argument or an
    interior pointer into it, and the notes on each say which.
    """
    return str_copy(str_alloc(str_len(s)), s, str_len(s))


def str_prefix(s, n) -> str:
    """The first `n` bytes of `s`, in a fresh buffer the caller owns.

    What a string SLICE would be. `s[0:n]` is refused on this path — the count
    would be read from offset 0 of a `char *`, which is the first eight
    CHARACTERS (bugs/FORMAL_string_value_model.md) — so every substring here is
    built with `memmove` and a terminator instead. `n` may exceed the length of
    `s`, which copies the whole string; every caller bounds it first.
    """
    return str_copy(str_alloc(n), s, n)


def str_build(a, sep, b) -> str:
    """`a + sep + b`, in a fresh buffer. The caller owns it.

    String `+` is refused on this path, so this is the spelling of
    concatenation everywhere above this line. Three fixed-arity calls, no
    format string, and nothing variadic — a variadic libc call cannot be
    forwarded through a wrapper with a fixed signature, which is one more
    reason the buffering lives beside the libc calls rather than one layer up.
    """
    d = str_alloc(str_len(a) + str_len(sep) + str_len(b))
    used = str_put(d, 0, a, str_len(a))
    used = str_put(d, used, sep, str_len(sep))
    used = str_put(d, used, b, str_len(b))
    return d


def str_repeat(s, k) -> str:
    """`s` written `k` times, in a fresh buffer. The caller owns it.

    `k <= 0` gives the empty string. Used for the `../` of a `relpath` and for
    nothing else, so it is not a general repeat.
    """
    d = str_alloc(str_len(s) * k)
    used = 0
    i = 0
    while i < k:
        used = str_put(d, used, s, str_len(s))
        i = i + 1
    return d


# ── Reading a string ───────────────────────────────────────────────────────
#
# Every one of these is a C library call that walks to the NUL, which is
# exactly the algorithm Python uses. A hand-written scan would be a second
# implementation of a routine that already exists, and the project has already
# paid for one of those (the `lstrip` loop that two backends got differently).

def str_len(s) -> int:
    """`strlen(s)`."""
    return strlen(s)


def str_eq_n(a, b, n) -> int:
    """1 if the first `n` bytes agree, else 0."""
    if memcmp(a, b, n) == 0:
        return 1
    return 0


def str_starts(s, p) -> int:
    """1 if `s` begins with `p`. An empty `p` is 1, as in Python."""
    if strncmp(s, p, str_len(p)) == 0:
        return 1
    return 0


def str_cmp(a, b) -> int:
    """`strcmp(a, b)`: <0, 0 or >0 — the lexicographic order of `a` and `b`.

    Python's `<` on `str` is a compare by CODE POINT and the C library's
    `strcmp` is a compare by UNSIGNED CHAR, and the two agree on every input a
    program can hand this: for UTF-8 the byte order IS the code point order,
    which is what makes UTF-8 self-synchronizing, so `a < b` in Python is
    `strcmp(a, b) < 0` here for every code point including everything above
    ASCII.

    This is the one way two strings are ORDERED on this path. `==` and `!=` on
    two `str` values are refused or wrong (see
    `bugs/FORMAL_string_equality_of_two_unclassified_words.md`), and `os.path`
    needed no ordering at all, so this arrived with `platform.system_alias`,
    which is nothing but two string comparisons and one rewrite.
    """
    return strcmp(a, b)



def str_at(s, i, chars) -> int:
    """1 if `s[i]` is one of the bytes of `chars`.

    A character test with no byte load, which is the only way to ask this
    question on this target (see the module docstring). `i` is assumed to be
    in range; every caller above has already bounded it.

    The test is `strspn(...) > 0` and NOT `== 1`. `strspn` returns the LENGTH
    of the run of set bytes from the pointer, so `== 1` asks whether that run
    is exactly one byte — which is false for the second of two adjacent
    separators, and answers "not a separator" for a character that is one. That
    is not a subtle difference: `str_at("//", 1, "/")` is 1 and the `== 1`
    spelling says 0, so a path of nothing but separators walks its components
    forever.
    """
    if strspn(s + i, chars) > 0:
        return 1
    return 0



def str_rfind(s, p) -> int:
    """Index of the LAST occurrence of `p` in `s`, or -1.

    A scan, not a library call, and the reason is measured: this target's C
    library does not provide `strrstr` (the link audit asks the library with
    `dlsym` and it is not there), so the obvious spelling of "last occurrence"
    emits a call to a symbol nothing defines. A bounded compare at each
    offset needs only `memcmp`, which does bind, and the answer is the
    question rather than an approximation of it. An empty needle is the length
    of the haystack, which is what the loop gives and what Python returns.
    """
    n = str_len(s)
    lp = str_len(p)
    last = 0 - 1
    i = 0
    while i + lp <= n:
        if str_eq_n(s + i, p, lp) == 1:
            last = i
        i = i + 1
    return last


def str_rindex_of(s, chars, m) -> int:
    """Index of the last byte of `s[0:m]` that is in `chars`, or -1.

    The bounded "last separator" question, and it is the one every path
    function above asks. The C library's `strrchr` has no bound, and the
    bounded question is what `dirname` asks of `"a/b/"` — where the answer
    must not be the trailing slash itself. Asking it through `strchr` would
    mean a length-limited copy of the string first, which is an allocation per
    call; asking it by index is a scan over at most `m` bytes, and a path is
    short.

    `chars` is a SET and is matched byte-wise, so this is `str_rchr` with a
    bound and with "/" written as a string rather than as the number 47 — see
    `str_at` for why the set is the right shape for the question.
    """
    i = m - 1
    while i >= 0:
        if str_at(s, i, chars) == 1:
            return i
        i = i - 1
    return 0 - 1


def str_lead(s, chars) -> int:
    """How many bytes of `s`, from the start, are in `chars`. `strspn`."""
    return strspn(s, chars)


def str_rstrip_len(s, m) -> int:
    """The length of `s[0:m]` with trailing `/` removed.

    Does not copy and does not allocate: it answers the LENGTH, and the caller
    copies once with it. A shorter result than the caller expects is its own
    business — this only removes separators.
    """
    while m > 0 and str_at(s, m - 1, "/") == 1:
        m = m - 1
    return m


def str_chr_from(s, i, c) -> str:
    """Pointer to the first `c` at or after `s[i]`, or 0.

    **`c` IS A CHARACTER CODE AND NOT A STRING**, which the signature does not
    say and which cost an afternoon the first time it was called from another
    module: `strchr`'s second parameter is an `int`, so `str_chr_from(s, 0, "/")`
    hands it a `char *` as a character and it finds nothing, EVER — every input
    answers 0. The one caller in this tree, `os/path/__init__.mojo`'s
    `normpath`, passes `SLASH = 47` for exactly this reason, and `47` next to
    `str_chr_from` in that file is the documentation. This docstring is here so
    that the next reader does not have to find it.

    So the whole of `shutil`'s `PATH` splitting spells `":"` as 58 and `"/"` as
    47, and `formal/hostmods/shutil.mojo`'s `_has_slash` says why at its own
    definition.
    """
    return strchr(s + i, c)


# The bytes CPython's `str.strip()` removes, as the SET `strspn` wants. Module
# level because `str_strip` is the only reader and the spelling is the part that
# has to be right: it is CPython's whitespace set restricted to characters a
# single byte can hold. `\x1c`-`\x1f` are in it because `Py_UNICODE_ISSPACE`
# says they are, and `str.isspace()` says so on this host's CPython — measured,
# `' \t\n\r\v\f\x1c\x1d\x1e\x1f\x85a\x85 \t'.strip()` is `'a'`. `\x85` (U+0085
# NEL) is deliberately NOT here: in UTF-8 it is the two bytes `\xc2\x85`, and a
# byte-wise `strspn` cannot see it. That is a RECORDED DIVERGENCE rather than an
# omission, and no caller in this tree strips a string that can hold one — the
# only `strip` is `platform`'s, over `uname(3)` fields.
_STR_WS = " \t\n\r\v\f\x1c\x1d\x1e\x1f"


def str_strip(s) -> str:
    """A fresh copy of `s` with leading and trailing whitespace removed.

    The caller owns the result, as it does for every allocating function in
    this module — `str.strip()` returns a NEW string in CPython and this is the
    same contract, not an interior pointer into `s`.

    Why it is written out rather than taken from the C library: `strspn` is
    already here for `str_at`/`str_lead`, so the two ends are two scans over a
    set the caller cannot index (`str_at` takes a SET because `strspn` takes a
    NUL-terminated one), and the alternative — `strcspn` against a negated set,
    which libc has — is a second spelling of the same question in the same file.
    The whitespace SET is `str_strip`'s own `_STR_WS`, stated there.
    """
    n = str_len(s)
    i = 0
    while i < n and str_at(s, i, _STR_WS) == 1:
        i = i + 1
    j = n
    while j > i and str_at(s, j - 1, _STR_WS) == 1:
        j = j - 1
    return str_copy(str_alloc(j - i), s + i, j - i)


def str_find(s, pat, from_i) -> int:
    """Index of the first occurrence of `pat` at or after `s[from_i]`, or -1.

    A scan, for the same reason `str_rfind` is one, and the second reason is
    this path's own: `strstr` returns a POINTER and every caller here wants an
    OFFSET, and turning one into the other is `p - s` on a bare `char *` — a
    difference of two words this value model has no shape for. The trap is
    easy to fall into and was: `str_len(p)` is not the offset, it is the length
    of the SUFFIX from `p` to the NUL, so `str_len(strstr(s, "bc"))` for
    `"abcabc"` is 5 and the difference from `str_len(s)` is -1. Measured, on an
    image built before this docstring said it.

    `strrstr` is absent on this target either (`str_rfind`'s docstring), so one
    bounded compare at each offset answers both questions, and `memcmp` does
    bind.

    **An EMPTY `pat` answers `from_i`, which is CPython's `str.find` and not
    what the scan above would give by accident.** A zero-length compare matches
    at every offset, so the first one IS `from_i`; saying so is better than
    leaving it to be rediscovered. `str_count` and `str_replace_all` are the
    two callers and both refuse an empty needle explicitly, because for THEM
    CPython's empty-needle rules differ and neither is a scan (see
    `str_replace_all`)."""
    n = str_len(s)
    m = str_len(pat)
    if m == 0:
        return from_i
    i = from_i
    if i < 0:
        i = 0
    while i + m <= n:
        if str_eq_n(s + i, pat, m) == 1:
            return i
        i = i + 1
    return 0 - 1


def str_count(s, pat) -> int:
    """How many non-overlapping occurrences of `pat` are in `s`.

    Its own pass rather than a `realloc` loop in `str_replace_all`, and the
    reason is the same one `platform.mojo`'s `_int_value`/`_int_ok` pair gives:
    a number that cannot be a sentinel and a buffer that has to be sized before
    it is written are two questions, and one function that answers both has to
    carry the reallocation with it. This target has `malloc` and no `realloc`
    worth using through this path, so "count, then allocate once, then fill" is
    the shape that needs no allocator at all.
    """
    n = str_len(s)
    m = str_len(pat)
    if m == 0:
        return 0
    hits = 0
    i = 0
    while i + m <= n:
        at = str_find(s, pat, i)
        if at < 0:
            break
        hits = hits + 1
        i = at + m
    return hits


def str_replace_all(s, frm, to) -> str:
    """A fresh copy of `s` with EVERY occurrence of `frm` replaced by `to`.

    The caller owns the result. EVERY occurrence and not the first: CPython's
    `str.replace` has no count argument, and the one caller
    (`platform._platform`) replaces a SINGLE CHARACTER, so a first-only version
    would be indistinguishable from this one there and wrong everywhere else.
    That is also why it is a substring replace and not a word-boundary test —
    `platform` drops the word `unknown` from the MIDDLE of a component as
    readily as from the whole of one, which is CPython's own behaviour
    (`platform._platform('unknown-x')` is `'-x'`).

    Occurrences are NON-OVERLAPPING and counted left to right, which is
    `str.replace`'s rule: `str_replace_all('aaa', 'aa', 'b')` is `'ba'`, and a
    scan that restarted one byte after a match would say `'ab'`.

    **A RECORDED DIVERGENCE, and it is CPython's `str.replace` that is odd
    here**: `s.replace("", "x")` in CPython inserts `x` at every position
    INCLUDING both ends, because an empty needle matches at every offset. That
    rule is not implemented — an empty `frm` returns `s` unchanged, and
    `str_find`/`str_count` say so rather than reporting a match at every index.
    No caller passes one (every needle in this tree is a non-empty literal), and
    the rule is not expressible as a left-to-right scan of non-overlapping
    matches at all: at offset 0 the empty match would have to be taken and the
    scan then restarted one byte later, forever."""
    n = str_len(s)
    if str_len(frm) == 0:
        return str_dup(s)
    hits = str_count(s, frm)
    if hits == 0:
        return str_dup(s)
    out = str_alloc(n - hits * str_len(frm) + hits * str_len(to) + 1)
    used = 0
    i = 0
    while 1:
        at = str_find(s, frm, i)
        if at < 0:
            used = str_put(out, used, s + i, n - i)
            break
        used = str_put(out, used, s + i, at - i)
        used = str_put(out, used, to, str_len(to))
        i = at + str_len(frm)
    return out


def fs_cwd() -> str:
    """The current working directory, in a fresh buffer the caller owns.

    A `malloc`'d copy rather than the descriptor's own buffer, so the caller
    can hold it past the next `chdir`. `PATH_MAX` is the buffer, because that
    is the length the C library refuses to exceed; a longer path cannot be
    reported by `getcwd` at all, and the empty string is what comes back
    rather than an error nobody on this path can catch.
    """
    var b: Pointer[UInt8] = str_alloc(4096)
    if getcwd(b, 4096) == 0:
        memset(b, 0, 1)
    return b


# ── The filesystem and the process ─────────────────────────────────────────
#
# Each of these was built and RUN on this target before it was written down
# here, and each returns what the C library returns: 0 or -1 for a call that
# reports failure, 0 for a POINTER that is not there. A negative status is
# not Python's exception, and there is no exception on this path (FORMAL.md
# phase 7); `os.remove` below says what it does instead.

def fs_access(p, mode) -> int:
    """`access(p, mode)`. `mode` 0 is F_OK: does the path resolve at all."""
    return access(p, mode)


def fs_arc4random(buf, n) -> int:
    """`arc4random_buf(buf, n)`: `n` random bytes into `buf`. Always 0.

    The C library's own CSPRNG, and the only randomness a formal image has:
    `arc4random(3)` is in libSystem, so this needs no library outside the one
    this target links (`FORMAL.md` §1) and no `/dev/urandom` descriptor.

    Here for `formal/hostmods/tempfile.mojo`, which is the one name in this
    tree that needs a name nothing else has taken — `mkdtemp`'s eight
    characters. The alternative that was measured and rejected is
    `arc4random()`, which takes no arguments and returns the value directly: it
    binds, and every one of five draws on this target came back under 2**32,
    which is the signature of a 64-bit return read as 32 bits rather than of a
    53-bit generator. Reading the bytes out of a buffer sidesteps the question
    entirely, and `n` is a byte count this path can pass.

    **0 rather than the call's own return value**, and that is deliberate: the C
    function returns `void`, so there is nothing to hand back, and a wrapper
    that returned whatever happened to be in the result register would be
    reporting a number this tree cannot vouch for. Callers read the bytes.
    """
    arc4random_buf(buf, n)
    return 0


def fs_chdir(p) -> int:
    """`chdir(p)`: 0 on success, -1 on failure."""
    return chdir(p)


def fs_chmod(p, mode) -> int:
    """`chmod(p, mode)`: 0 on success, -1 on failure."""
    return chmod(p, mode)


def fs_close(fd) -> int:
    """`close(fd)`."""
    return close(fd)


def fs_closedir(d) -> int:
    """`closedir(d)` on a descriptor from `fs_opendir`."""
    return closedir(d)


def fs_getcwd(buf, n) -> str:
    """`getcwd(buf, n)`: `buf`, or 0 if the path does not fit in `n`."""
    return getcwd(buf, n)


def fs_getenv(name) -> str:
    """`getenv(name)`: the value, or 0 when the variable is not set."""
    return getenv(name)


def fs_setenv(name, value, overwrite) -> int:
    """`setenv(name, value, overwrite)`: 0 on success, -1 on failure."""
    return setenv(name, value, overwrite)


def fs_unsetenv(name) -> int:
    """`unsetenv(name)`: 0 on success, -1 on failure."""
    return unsetenv(name)


def fs_environ_vec() -> Pointer[Pointer[UInt8]]:
    """The process's `char **environ`, or 0 when the host will not say.

    THE ONE WAY THIS PATH REACHES THE ENVIRONMENT AS A LIST OF NAMES, and it is
    here rather than in `os/__init__.mojo` because it is the only place in this
    file that is not a direct libc call: everything above it is `return f(...)`,
    and this one computes.  `getenv` answers ONE key and the question "what
    keys are there" needs the array, so this is where the two halves meet.

    **WHY `dlsym` AND NOT `_NSGetEnviron`.** libSystem has a function that
    returns this array — `_NSGetEnviron()` — and it is the obvious spelling,
    and it does not lower on this path: a callee whose name begins with `_`
    cannot be bound.  `model.libc_source_name` strips the leading underscore
    before asking the C library whether it provides the name, and macOS's
    `dlsym` does NOT add the underscore back — measured:

        >>> ctypes.CDLL('/usr/lib/libSystem.B.dylib')._NSGetEnviron   # OK
        >>> ctypes.CDLL('/usr/lib/libSystem.B.dylib').NSGetEnviron    # dlsym: not found

    so the audit asks about a name that does not exist and refuses the build
    with "the image would bind 1 symbol(s) that nothing provides:
    _NSGetEnviron".  The defect is real and it is written down, with its two
    one-line repairs, in
    `bugs/FORMAL_libc_call_whose_name_starts_with_an_underscore.md`; this is
    not that fix and does not touch the linker, because a light change to
    `_bind_info` on both architectures is not a light change.

    So the array is reached the way every other program reaches a DATA symbol
    it was not linked against — by asking the dynamic loader for it at RUN
    time.  `dlopen(0, 0)` is a handle to this very image (`NULL` is the main
    program, and `0` is the flags), and `dlsym` on that handle searches it and
    the libraries it was linked against, which includes libSystem; `environ` is
    a global data symbol libSystem exports.  Measured on both architectures:

        $ python3 fire.py build --formal --no-prove -o p .tmp/probe.mojo
        $ ./p
        E0 [MANPATH=…] len=372@@E1 [TERM_PROGRAM=Apple_Terminal] len=27@@

    The alternative spelling `dlsym(-2, name)` — `RTLD_DEFAULT`, a Darwin
    extension whose value is literally `(void *) -2` — binds too and is one
    call shorter, and it is not used: a magic negative pointer is a fact about
    one library's header rather than about the loader, and the handle form says
    the same thing in a way both platforms spell the same way.

    **THE THREE POINTER TYPES ARE THE WHOLE OF THIS FUNCTION.** `environ` is
    declared `char **`, so the address of it is `char ***`, and the value is
    `char **`:

        char ***at_environ = dlsym(handle, "environ");   # the slot
        char **envp      = *at_environ;                  # the array

    and this path's subscript reads at the width the ANNOTATION says, so the
    annotation on the local is not documentation: `var q: Pointer[UInt8] =
    dlsym(…)` then `q[0]` is a ONE-BYTE load and the program dies of SIGSEGV
    on the first `envp[i]` — measured, arm64, and the image built and ran to
    get there.  `Pointer[Pointer[Pointer[UInt8]]]` is what says "this word
    points at a word which points at a word".

    0 rather than a crash when the loader will not name it, which is the same
    answer `fs_opendir` gives for a directory that is not there, and for the
    same reason: there is no exception to raise (the note at the top of
    `formal/hostmods/os/__init__.mojo`).
    """
    var h: Pointer[UInt8] = dlopen(0, 0)
    if h == 0:
        return 0
    var at_environ: Pointer[Pointer[Pointer[UInt8]]] = dlsym(h, "environ")
    if at_environ == 0:
        return 0
    return at_environ[0]


def fs_lseek(fd, off, whence) -> int:
    """`lseek(fd, off, whence)`."""
    return lseek(fd, off, whence)


def fs_read(fd, buf, n) -> int:
    """`read(fd, buf, n)`: bytes read, 0 at end of file, -1 on failure.

    THE MISSING THIRD of the descriptor calls, and the one every other
    descriptor function above is waiting for: `fs_open_ro`, `fs_lseek` and
    `fs_close` can open a file and find its size and cannot read a byte of it,
    which is why `io`'s streams, `platform.architecture` and `libc_ver` are all
    absent (the first and last two are named at the definitions that want them,
    and the stream argument is `bugs/FORMAL_glob_copy_collections_io_not_
    attempted.md`). Three fixed arguments and no fourth, which is `read(2)`'s
    own signature: the C library's `fread` takes a `FILE *` and this path has no
    `FILE`, and `read` is the call that works on a bare descriptor.

    A short read is not an error and is not retried: `n` bytes is what the
    caller asked for and this is what arrived, which is the same contract C has.
    The caller loops.
    """
    return read(fd, buf, n)


def fs_fopen(p, mode) -> int:
    """`fopen(p, mode)`: a `FILE *`, or 0.

    THE WRITING PATH, and it goes through the stdio calls rather than through
    `open(2)` for the reason this file's header gives: `open` on this path is a
    LOWERED BUILTIN that takes a mode string and refuses any other spelling, so
    `O_WRONLY | O_CREAT | O_TRUNC` is not available even though libSystem has
    the function that takes it. `fopen` takes the same information as the
    spelling this path has, so "wb" here means exactly what `O_WRONLY |
    O_CREAT | O_TRUNC, 0666` means — with the one difference that matters and is
    CPython's own: `fopen`'s mode gives NO PERMISSIONS argument, so the file is
    created with the umask's default (0644 with the usual umask 022), and
    `shutil.copyfile` therefore produces the same mode CPython's
    `shutil.copyfile` produces only because CPython also does not chmod. That
    is measured by `test_formal_shutil.py`, which copies a file both ways and
    compares the resulting `st_mode`.

    The `FILE *` is carried as an `int`, which is the pointer value model and is
    what every pointer here is (`fs_readdir`'s docstring says the same).
    """
    return fopen(p, mode)


def fs_fwrite(f, buf, n) -> int:
    """`fwrite(buf, 1, n, f)`: items written, which is `n` or fewer.

    The size argument is `1` so the return value is a BYTE COUNT and compares
    with what the caller asked for; `fwrite(buf, n, 1, f)` would return 0 or 1
    and say nothing about a short write.
    """
    return fwrite(buf, 1, n, f)


def fs_fread(f, buf, n) -> int:
    """`fread(buf, 1, n, f)`: items read — bytes, 0 at end of file.

    The complement of `fs_fwrite`, and the reason `shutil` needs it: `fs_read`
    works on a bare DESCRIPTOR and this path cannot make a bare descriptor for
    writing, so the copy loop reads and writes through stdio on both sides.
    Reading and writing through different interfaces would work too, and would
    be one function fewer — but it would leave the caller mixing a descriptor
    and a `FILE *` for the same file, which is the kind of asymmetry that costs
    an afternoon later.
    """
    return fread(buf, 1, n, f)


def fs_fclose(f) -> int:
    """`fclose(f)`: 0 on success. FlUSHES, which is the whole reason stdio is
    used at all: a `FILE *`'s buffer reaches the filesystem at `fclose`, so a
    copy that never closes leaves an empty destination and a zero exit status.
    """
    return fclose(f)


def fs_utimes(p, asec, ausec, msec, musec) -> int:
    """`utimes(p, {atime, mtime})`: 0 on success, -1 on failure.

    THE `struct timeval` IS BUILT HERE AND NOT BY THE CALLER, because its
    layout is the ABI's rather than the source's: two `{ time_t tv_sec;
    suseconds_t tv_usec }`, eight bytes each on a 64-bit target, 32 bytes in
    total, and a caller that assembled it would be writing four offsets it has
    no way to check. Same rule as `struct stat` above, for the same reason, and
    for the same reason the offsets are written out here rather than trusted:
    the seconds fields are at 0 and 16 and the microsecond fields at 8 and 24.

    `ausec` and `musec` are separate PARAMETERS rather than one nanosecond
    number because `struct stat`'s time fields are nanoseconds
    (`st_mtimespec.tv_nsec` at offset 56) while `timeval`'s are microseconds,
    and a caller reading a stat and setting a timeval has to divide. Doing the
    division in the caller is honest about where it happens; doing it here would
    hide a rounding decision inside a wrapper.
    """
    var tv: Pointer[UInt8] = malloc(32)
    memset(tv, 0, 32)
    _put_time(tv, 0, asec, ausec)
    _put_time(tv, 16, msec, musec)
    var rc = utimes(p, tv)
    free(tv)
    return rc


def _put_time(tv: Pointer[UInt8], at, sec, usec) -> int:
    """Seconds at `tv + at` and microseconds at `tv + at + 8`, little-endian.

    One byte at a time through `le64` for the reason every other reader in this
    file is: the source declares no struct, so a load of the field's declared
    width is what C does and a wider read would be a guess about alignment.
    """
    _put_le64(tv + at, sec)
    _put_le64(tv + at + 8, usec)
    return 0


def _put_le64(tv: Pointer[UInt8], v) -> int:
    """Little-endian 64-bit STORE of `v` at `tv`, byte by byte.

    THE STORE COUNTERPART of `le64`, and it exists because this file had a
    reader for every field it wanted and no writer for any of them. A caller
    cannot write into a `struct` it does not declare any more than it can read
    one, and this is the same constraint on the other side: `memset` a whole
    buffer and then set two words in it. It is eight one-byte `memset`s, which
    is what `le64`'s reader already costs.

    `v >> 8` and `v >> 16` and so on are ARITHMETIC SHIFTS on a 64-bit word, so
    the byte extracted is the one the platform's `little-endian` means. A
    big-endian target would need `le64`'s reader mirrored here, and this file's
    `be64` already says the same thing about its own reader.
    """
    memset(tv, v & 255, 1)
    memset(tv + 1, (v >> 8) & 255, 1)
    memset(tv + 2, (v >> 16) & 255, 1)
    memset(tv + 3, (v >> 24) & 255, 1)
    memset(tv + 4, (v >> 32) & 255, 1)
    memset(tv + 5, (v >> 40) & 255, 1)
    memset(tv + 6, (v >> 48) & 255, 1)
    memset(tv + 7, (v >> 56) & 255, 1)
    return 0


def fs_flock(fd, operation) -> int:
    """`flock(fd, operation)`: 0 on success, -1 on failure.

    **HERE AND NOT IN `formal/hostmods/fcntl.mojo` BECAUSE OF THE NAME
    COLLISION RULE AT THE TOP OF THIS FILE**, and it is the rule's first
    example again: `flock` is a libc function AND the name `fcntl.mojo`'s API
    wants, so a module that defined `def flock(fd, operation)` and called
    `flock(fd, operation)` inside it would emit a call to ITSELF with the
    wrong arity. `getcwd`, `chdir`, `remove` and `rename` are all in the same
    position and are all wrapped here for the same reason.
    """
    return flock(fd, operation)


def fs_fcntl(fd, cmd, arg) -> int:
    """`fcntl(fd, cmd, arg)`: 0 on success, -1 on failure.

    THREE FIXED ARGUMENTS AND NO FOURTH, which is `fcntl(2)`'s own shape once
    the variadic tail is gone: the command is the second parameter and the
    argument is the third, and `fcntl` is called with three arguments for every
    command here. **The variadic ARGUMENT IS A POINTER for `F_SETLK` and
    friends, and that is not spelt** — see `formal/hostmods/fcntl.mojo`'s
    `lockf` docstring, which is where the consequence is written down. The
    commands reachable through this wrapper are the ones whose argument is an
    integer: `F_GETFD`, `F_SETFD`, `F_GETFL`, `F_SETFL`.
    """
    return fcntl(fd, cmd, arg)


def fs_strsignal(sig) -> str:
    """`strsignal(sig)`: the C library's own description of a signal number.

    **HERE FOR THE NAME COLLISION RULE AT THE TOP OF THIS FILE**, and it is the
    rule's second kind of case: `strsignal` is a libc function AND the name
    `formal/hostmods/signal.mojo`'s API wants, because CPython spells its
    wrapper the same way. A unit that both declares `def strsignal(sig)` and
    calls `strsignal(sig)` emits a call to ITSELF — measured, not argued: the
    first version of `signal.mojo` did exactly that and the image died with
    exit 2 and printed nothing, which is a silent recursion wearing the costume
    of a crash.

    NOT A TABLE OF STRINGS, which is the other reason it is here rather than
    written out: on this platform `strsignal(15)` is `"Terminated: 15"` — the
    number is IN the text — while Linux's is `"Terminated"`, so any table
    written in this tree would be right on one platform and a plausible wrong
    answer on the other. A signal number that is not a signal has no answer and
    the C library's answer for that is the empty string.
    """
    return strsignal(sig)


def fs_getpid() -> int:
    """`getpid()`: this process's pid, which is never 0 and never negative."""
    return getpid()


def fs_kill(pid, sig) -> int:
    """`kill(pid, sig)`: 0 on success, -1 with ESRCH if there is no such process.

    The send half of `signal.raise_signal`, which is what CPython's own source
    does (`raise_signal` is `kill(getpid(), signum)`), and it is here so that
    `signal.mojo` contains no libc call of its own and the question "what does
    this tree ask of the operating system" keeps the short complete answer this
    file's header promises.

    `SIGKILL` and `SIGSTOP` cannot be caught, blocked or ignored, so a caller
    that sends one of those to itself ends the image; that is the platform's
    rule and not a choice this wrapper makes.
    """
    return kill(pid, sig)


def fs_mkdir(p, mode) -> int:
    """`mkdir(p, mode)`: 0 on success, -1 with EEXIST if it is already there."""
    return mkdir(p, mode)


def fs_mkdtemp(tmpl) -> str:
    """`mkdtemp(tmpl)`: the path of a fresh directory, with `tmpl` REPLACED.

    **`mkdtemp(3)` rather than `mkdir` in a loop**, and the reason is `errno`:
    CPython's `mkdtemp` retries `TMP_MAX` times when a candidate name is already
    taken, and telling "already taken" from "could not be made" means reading
    `__error`, whose leading underscore is not a symbol this path can bind (see
    this module's own docstring). The C library's call does that retry with the
    error code to itself, so one call here is EXACT where a loop here could only
    be an approximation of it.

    A TEMPLATE and not a prefix/suffix pair, because that is the C library's
    interface: the last six bytes must be `XXXXXX`, the C library replaces them
    with the name it chose and writes the whole path back through the pointer.
    So this DUPLICATES the caller's string, calls with the copy, and returns the
    copy — a fresh writable buffer, which is why `str_dup` and not the input.
    That is the whole reason this wrapper exists at all: a `char *` the C
    library rewrites has to be writable, and a string literal on this path is in
    a read-only text section.

    The empty string when no name could be made, which is what every other
    failure here is (there is no exception on this path — FORMAL.md phase 7).

    The six random characters are THE C LIBRARY'S, so what comes back is a real
    answer about a real directory rather than a value this tree chose.

    **AND IT IS NOW SOMEBODY'S BODY**: `formal/hostmods/tempfile.mojo`'s
    `mkdtemp(prefix)` is one call to this, over a template of `prefix` +
    `XXXXXX` in the directory `gettempdir` names. It replaced a hand-written
    loop there that drew eight characters and retried `mkdir`, and the loop
    could not be right: this path cannot read `errno` (`__error`'s leading
    underscore, this module's own header), so every failure was a "collision"
    and a directory that could not be made cost the whole budget
    (fixed 2026-10-03 in 8c311e87, where `mkdtemp` became one
    `mkdtemp(3)` call: a loop over `mkdir` here cannot read `errno`, so it retried
    every failure as if it were a collision).
    Two consequences recorded where they are paid rather than here: the name is
    `prefix` + six characters of `[A-Za-z0-9]` where it was `prefix` + eight of
    CPython's alphabet, and the mode is the platform's `0o700` rather than a
    literal this tree passes — `test_formal_tempfile.py` reads both back.
    """
    b = str_dup(tmpl)
    if mkdtemp(b) == 0:
        memset(b, 0, 1)
    return b


def fs_open_ro(p) -> int:
    """`open(p, O_RDONLY)`: a descriptor, or -1.

    Spelled `open(p, "r")` and not `open(p, O_RDONLY)`: this path lowers
    `open` itself, building the flags word from the mode string, and refuses
    any other spelling — including the C library's own three-argument `open`,
    which is the one call here that has no bare-name spelling. What comes back
    is the same descriptor number, and `lseek` and `close` take it.
    """
    return open(p, "r")


def fs_opendir(p) -> int:
    """`opendir(p)`: a descriptor, or 0.

    This is what answers `isdir`, and it answers it exactly: `opendir` fails
    with ENOTDIR for anything that is not a directory, and follows a symbolic
    link to one, which is what `os.path.isdir` does.
    """
    return opendir(p)


def fs_readdir(d) -> int:
    """`readdir(d)`: a `struct dirent *`, or 0 at the end of the directory.

    A `char *` and NOT a string on purpose: it is the address of a struct, not
    of bytes, and `-> str` would tell a call site to compare its contents as a
    string. It is an `int` for the same reason `fs_opendir` is — a pointer this
    path carries as a word.
    """
    return readdir(d)


def fs_rewinddir(d) -> int:
    """`rewinddir(d)`: back to the first entry, so a directory can be read
    twice.

    Which is what `os.listdir` does: one pass to count the entries, one to
    copy them out. The C library will not say how many there are without reading
    them, and the blob this module builds has to be exactly the size its
    contents need — see `os.listdir` for why "big enough" is not the answer.
    """
    return rewinddir(d)


# ── Reading a name out of a `struct dirent` ────────────────────────────────
#
# The layout, measured rather than quoted: 48 bytes of the struct dumped
# through `ctypes` for the first four entries of `/etc`, with the name read out
# of each.
#
#      0  d_ino        int64
#      8  (padding, 8)
#     16  d_reclen     uint16   32 or 40
#     18  d_namlen     uint16   the length of the name
#     20  (one byte this reading does not account for)
#     21  d_name       char[]   NUL-terminated
#
# `d_name` at 21 is what those four entries say: byte 21 is `.` for `.`, `..`
# for `..`, `h` for `hostconfig~orig` and `s` for `sshd_config.~6~`, each
# followed by its own NUL. The byte at 20 is not accounted for here and is not
# read, which is the only safe thing to do with a byte whose meaning this
# source does not state.
#
# This is the half of `bugs/FORMAL_listdir_no_run_time_sequence.md` the byte
# read made answerable. It was not answerable before because a read of the
# struct was a COUNT-WALK — a bounds check against whatever word sat at offset
# 0 — and now each byte is a load of the width it declares.

def fs_dirent_name(e: Pointer[UInt8]) -> str:
    """The `d_name` of the entry `e`, in a fresh buffer the caller owns.

    COPIED rather than returned as a pointer into the struct, and the reason is
    the one this whole module is about: a `readdir` result is only valid until
    the next `readdir` on the same descriptor, so an interior pointer into it
    would be a name that changes under the caller. `d_name` is at byte 21 (see
    the table above) and the copy stops at the NUL.

    `e` is ANNOTATED `Pointer[UInt8]` and that annotation is load-bearing: it
    is what makes `e[21 + i]` a one-byte load rather than a list-blob walk
    bounds-checked against the inode number at offset 0. Without it the same
    line returns a fabricated number, and
    `bugs/FORMAL_subscript_of_a_pointer_reads_a_blob_count.md` has the
    measurement.

    1024 bytes is the array's own size on this target, so a name that long
    cannot be truncated.
    """
    var d: Pointer[UInt8] = str_alloc(1024)
    i = 0
    while e[21 + i] != 0 and i < 1023:
        d[i] = e[21 + i]
        i = i + 1
    d[i] = 0
    return d


def fs_name_is_dot(name: Pointer[UInt8]) -> int:
    """1 if `name` is `.` or `..` — the two entries a listing drops.

    BYTE VALUES and not `name[0] == "."`: a byte is a number on this path, and
    comparing it to a string literal lowers to `strcmp`, which dereferences the
    number — measured, SIGSEGV with no output
    (`model.string_compare_number_refusal`). 46 is `.`, the same number
    `os/path`'s `DOT` constant carries under the name the path functions use it
    by.

    The four cases, because the interesting one is the second: `.`, `..`, a
    name that merely BEGINS with two dots (`.profile`) and a name that begins
    with one (`.hidden`) are four answers, and a two-term test gets two of them
    wrong.
    """
    if name[0] != 46:
        return 0
    if name[1] == 0:
        return 1
    if name[1] != 46:
        return 0
    if name[2] == 0:
        return 1
    return 0


# ── The `struct stat` this target fills in ────────────────────────────────
#
# `stat(2)` and `lstat(2)` take their answer in an out-parameter, and that
# out-parameter is a `struct stat` this source does not declare. The offsets
# below are therefore a property of the TARGET, not of this program, and they
# are written out in full so that a reader can check them rather than trust
# them. They are the `__DARWIN_64_BIT_INO_T` layout — the one an arm64 macOS
# uses, where `st_ino` is 64 bits — and they are NOT the 32-bit-inode layout
# that `st_mode` at 16 and `st_size` at 96 describe; that is the layout a
# 32-bit target uses, and reading this one with those offsets gets a plausible
# wrong number rather than an error.
#
# Measured on this host by calling the C library's own `stat(2)` through
# `ctypes` and dumping the buffer, against `os.stat` in the same process:
#
#      0  st_dev          int32     4  st_mode        uint16
#      6  st_nlink        uint16    8  st_ino         int64
#     16  st_uid          uint32   20  st_gid         uint32
#     24  st_rdev         int32   28  (padding)
#     32  st_atimespec    { int64 sec; int64 nsec; }
#     48  st_mtimespec    { int64 sec; int64 nsec; }
#     64  st_ctimespec    { int64 sec; int64 nsec; }
#     80  st_birthtimespec{ int64 sec; int64 nsec; }
#     96  st_size         int64
#    104  st_blocks       int64
#    112  st_blksize      int64
#
# Every field this module reads is read ONE BYTE AT A TIME through
# `le16`/`le32`/`le64` below, so each load has the width the field declares.
# That is the difference from the state
# `bugs/FORMAL_stat_out_parameter_is_unreadable.md` describes: it was not the
# offsets that made the struct unreadable, it was that a read of it was a
# COUNT-WALK — a bounds check against whatever word was at offset 0. A byte
# read at a declared offset is what C does, and it is now answerable.
#
# The offsets are CONSTANTS, and a module-level constant is not exported as a
# word across a dylib boundary (`FORMAL_module_state_no_storage.md`), so they
# are `int` PARAMETERS of the readers and the values live at the use sites.
# The names are spelled `ST_*` here as the numbers they are; the spellings a
# caller uses are the functions further down, which is also where the layout is
# checked.

def le16(b: Pointer[UInt8], i) -> int:
    """The little-endian 16-bit field at byte `i` of `b`."""
    return b[i] + 256 * b[i + 1]


def le32(b: Pointer[UInt8], i) -> int:
    """The little-endian 32-bit field at byte `i` of `b`."""
    return b[i] + 256 * b[i + 1] + 65536 * b[i + 2] + 16777216 * b[i + 3]


def le64(b: Pointer[UInt8], i) -> int:
    """The little-endian 64-bit field at byte `i` of `b`.

    A LOOP rather than eight terms: the shift is `1 << (8*k)`, and eight of
    those in one expression is a long line whose associativity nobody has to
    check by eye. `v + byte * scale` is the same addition the other two readers
    do, and `*` binds tighter than `+` on this path.
    """
    v = 0
    k = 0
    while k < 8:
        v = v + b[i + k] * (1 << (8 * k))
        k = k + 1
    return v


MACHO_WIDTH = 0
MACHO_EXECUTABLE = 1


def fs_macho_field(p, which) -> int:
    """One fact about the Mach-O at `p`, chosen by `which`.

    `which` is `MACHO_WIDTH` (32, 64, or 0 when `p` is not a Mach-O at all) or
    `MACHO_EXECUTABLE` (1 or 0). ONE function and a parameter rather than two
    functions, because the answer to either needs the other's work: a FAT
    header has to be walked to reach either, and two walkers are two things to
    be wrong about a slice table.

    THE WIDTH, read rather than assumed, from the magic at offset 0 of each
    header:

        0xFEEDFACF   64-bit   -> 64
        0xFEEDFACE   32-bit   -> 32
        0xCAFEBABE   a FAT binary: several Mach-Os, each with its own header
        0xCAFEBABF   the 64-bit-offset FAT
        anything else         -> 0

    THE FAT CASE IS NOT A CORNER, it is `/bin/ls`, `/bin/cat` and every other
    system tool on an Apple Silicon macOS: `/bin/ls` is "Mach-O universal binary
    with 2 architectures: [x86_64:Mach-O 64-bit executable x86_64] [arm64e:
    Mach-O 64-bit executable arm64e]", and calling that "not a Mach-O" would
    make `platform.architecture("/bin/ls")` disagree with CPython on the most
    ordinary path a caller can name. So a fat header is walked: the slice count
    at offset 4, then one `struct fat_arch` per slice, and each slice's own
    header read at the offset that entry gives.

    The rule for the WIDTH of a fat binary is CPython's own: its `architecture`
    looks for `'32-bit'` anywhere in `file -b`'s output before it looks for
    `'64-bit'`, and for a fat binary that output is one line per slice — so 32
    if ANY slice is 32-bit, else 64 if any is 64-bit, else 0.

    `MACHO_EXECUTABLE` IS NOT "IS A MACHO-O", and the difference is CPython's
    parser being older than `file(1)`. CPython accepts a file whose `file -b`
    output contains the word `executable` or the phrase `shared object`:

        if 'executable' not in fileout and 'shared object' not in fileout:
            return bits, linkage          # the presets, unchanged

    and this macOS's `file` prints "Mach-O 64-bit dynamically linked shared
    library" for a dylib — never the phrase `shared object` — so CPython
    answers `architecture(dylib)` as `('64bit', '')` here, MEASURED, and
    `'Mach-O'` for an executable. Emulating that is this function's whole
    reason: the module that reads it, `platform.architecture`, is a MIRROR of
    CPython's, and a dylib answered `'Mach-O'` would be a right answer that
    disagrees with the thing being mirrored. It reads the header's `filetype`
    field (offset 12; `MH_EXECUTE` is 2), which is where `file` reads it too.

    LITTLE-ENDIAN SLICES ONLY, and stated rather than implied: the slice headers
    are read with `le32`, so a big-endian slice reads as its byte-reverse and is
    not recognised. That is not a gap on this target — both architectures
    `formal` emits are little-endian and no macOS slice is big-endian — but it IS
    a fact about the answer rather than about the world, and a reader should not
    have to derive it from the `le32`. The FAT HEADER, by contrast, is
    big-endian on disk (see `be32`).

    0 for anything that is not a Mach-O — a text file, a directory, a path that
    is not there — and that is the answer the caller needs rather than an error:
    it is what makes `architecture` fall back to CPython's own "format not
    supported" branch instead of claiming a width it did not read. The file is
    opened, read and closed here rather than handed back, because a descriptor
    cannot cross a dylib boundary and neither can the header it read.
    """
    var fd = fs_open_ro(p)
    if fd < 0:
        return 0
    var buf: Pointer[UInt8] = str_alloc(8)
    var n = fs_read(fd, buf, 4)
    if n < 4:
        fs_close(fd)
        return 0
    var m = le32(buf, 0)
    if m == 4277009103 or m == 4277009102:
        # One header, not a table: read its `filetype` and answer both.
        var exe = 0
        if which == MACHO_EXECUTABLE:
            if fs_lseek(fd, 12, 0) < 0:
                fs_close(fd)
                return 0
            if fs_read(fd, buf, 4) < 4:
                fs_close(fd)
                return 0
            if le32(buf, 0) == 2:
                exe = 1
        fs_close(fd)
        if which == MACHO_EXECUTABLE:
            return exe
        if m == 4277009103:
            return 64          # 0xFEEDFACF
        return 32              # 0xFEEDFACE
    var wide = 0
    if m == 3199925962:
        wide = 0               # 0xCAFEBABE, read little endian
    elif m == 3215774410:
        wide = 1               # 0xCAFEBABF, the 64-bit-offset FAT
    else:
        fs_close(fd)
        return 0
    # The slice count, BIG endian: a fat header is written by a tool that had
    # to be readable on a big-endian machine, so this one field is read the
    # other way round from every other header here. The bytes are the same
    # either way; only the order differs.
    n = fs_read(fd, buf, 4)
    if n < 4:
        fs_close(fd)
        return 0
    var count = be32(buf, 0)
    # One `struct fat_arch` is 20 bytes, or 32 for the 64-bit-offset FAT, and
    # `offset` is its THIRD field — cputype and cpusubtype come first — so the
    # read seeks to entry+8 rather than to the entry.
    var step = 20
    if wide == 1:
        step = 32
    var best = 0
    var exe = 0
    var k = 0
    while k < count and k < 64:
        if fs_lseek(fd, 8 + step * k + 8, 0) < 0:
            break
        var at = 0
        if wide == 1:
            n = fs_read(fd, buf, 8)
            if n < 8:
                break
            at = be64(buf, 0)
        else:
            n = fs_read(fd, buf, 4)
            if n < 4:
                break
            at = be32(buf, 0)
        if fs_lseek(fd, at, 0) < 0:
            break
        n = fs_read(fd, buf, 16)
        if n < 16:
            break
        var sm = le32(buf, 0)
        if sm == 4277009102:
            best = 32          # a 32-bit slice wins, as CPython's scan does
        elif sm == 4277009103 and best == 0:
            best = 64
        if le32(buf, 12) == 2:
            exe = 1
        k = k + 1
    fs_close(fd)
    if which == MACHO_EXECUTABLE:
        return exe
    return best


def be16(b: Pointer[UInt8], i) -> int:
    """The big-endian 16-bit field at byte `i` of `b`. See `le16`."""
    return 256 * b[i] + b[i + 1]


def be32(b: Pointer[UInt8], i) -> int:
    """The big-endian 32-bit field at byte `i` of `b`.

    BIG ENDIAN, and the reason this exists at all: a FAT Mach-O header is
    written by a tool that had to be readable on a big-endian machine, so its
    slice count and every `struct fat_arch` offset are big-endian while the
    slice's own header is not (`fs_macho_bits` reads that one with `le32`).
    Two byte orders in one header, which is exactly the kind of thing a
    transcription gets wrong silently — so the reader is named for what it does
    rather than left as an expression.
    """
    return 16777216 * b[i] + 65536 * b[i + 1] + 256 * b[i + 2] + b[i + 3]


def be64(b: Pointer[UInt8], i) -> int:
    """The big-endian 64-bit field at byte `i` of `b`. A LOOP, as `le64` is."""
    var v = 0
    var k = 0
    while k < 8:
        v = v * 256 + b[i + k]
        k = k + 1
    return v


def fs_stat(p, buf) -> int:
    """`stat(p, buf)`: 0 when `buf` was filled, -1 when it was not.

    The two-argument spelling. The C library's own third parameter is an
    `audit_t` the caller does not have to pass for the call to work, and there
    is no way to spell a three-argument extern here that is not also a way to
    pass a stack address as the third word.
    """
    return stat(p, buf)


def fs_lstat(p, buf) -> int:
    """`lstat(p, buf)`: as `fs_stat`, without following a symbolic link.

    This is the whole of what `lexists`, `islink` and `samefile` need and the
    reason they are exact rather than approximate: the difference between
    `stat` and `lstat` is the difference between the mode of a link and the
    mode of what it points at, and it is one word of the callee's behaviour
    rather than anything this path has to compute.
    """
    return lstat(p, buf)


# ── Reading `struct stat` back out, and CHECKING that it is one ─────────────
#
# Everything above reads a field the caller named. What follows reads the
# fields this path is actually asked for, and the first of them is the one that
# makes the rest trustworthy.
#
# `st_size` is the canary, and it is a canary because it is a fact this module
# can establish TWO INDEPENDENT WAYS: `lseek(fd, 0, SEEK_END)` on a
# read-only descriptor is a value, and it is the same number `stat` puts at
# offset 96. So `fs_stat_layout_ok` asks both and refuses if they disagree.
# That turns the offsets above from a table this file asserts into a table this
# file CHECKS, on every call, against the C library itself — and a target whose
# `struct stat` is laid out differently gets 0 from every `stat_*` function
# below rather than a plausible wrong number out of adjacent bytes. That is the
# whole difference from the state
# `bugs/FORMAL_stat_out_parameter_is_unreadable.md` describes.
#
# It runs only when the mode says the path is a REGULAR file, for two reasons.
# `lseek` on a directory descriptor reports something about the directory
# rather than a file size, so the two answers would differ for a reason that has
# nothing to do with the layout. And `open` on a FIFO blocks until a writer
# arrives, so a canary that ran for every non-directory would hang on one — the
# mode is read first precisely so that the only shape that is opened is the one
# that cannot block. The mode is the thing under test, so this is not a proof;
# it is a guard that catches a layout which disagrees with the C library about
# a size, and `test_formal_os.py` pins every field against CPython on a
# regular file, a directory, a device node, a FIFO and a symbolic link.

def fs_stat_layout_ok(p, buf) -> int:
    """1 if the bytes in `buf` can be read as this target's `struct stat`.

    0 means either that `stat` failed (nothing was written) or that the
    offsets do not describe what the C library put in the buffer. The two are
    not told apart on purpose: both of them mean "there is no `struct stat`
    here", and every caller below has the same answer to give.
    """
    m = le16(buf, 4)
    if m == 0:
        return 0
    if (m & 61440) != 32768:
        # Not S_IFREG. See above: this is what keeps the canary from opening a
        # FIFO. 32768 is 0x8000, the format bits of a regular file; the mask
        # keeps the permission bits out of the comparison.
        return 1
    fd = fs_open_ro(p)
    if fd < 0:
        return 1
    n = fs_lseek(fd, 0, 2)
    fs_close(fd)
    if n < 0:
        return 1
    if n != le64(buf, 96):
        return 0
    return 1


def fs_stat_fill(p, follow) -> int:
    """`p`'s `struct stat` in a fresh buffer, or 0 when there is not one.

    THE one place the `stat`/`lstat` choice, the status check and the layout
    check happen. Three field readers below need all three, and a second copy of
    the sequence is a second thing to be wrong about which of the three
    produces a -1.

    `follow` 0 means `lstat` and 1 means `stat`, spelled as a number because
    the C library's own two names are two functions and a name is not a value
    on this path. 0 rather than -1 for "no struct here", so a caller can test
    it against 0 the way it tests every other pointer the C library hands back.
    The buffer is `malloc`'d and the CALLER OWNS it; every reader above gives
    the buffer away inside the call, and the field readers below are the only
    things that keep one.
    """
    buf = str_alloc(256)
    r = 0
    if follow == 1:
        r = fs_stat(p, buf)
    else:
        r = fs_lstat(p, buf)
    if r != 0:
        return 0
    if fs_stat_layout_ok(p, buf) == 0:
        return 0
    return buf


def fs_stat_mode(p, follow) -> int:
    """`st_mode` of `p`, or -1. `follow` 0 means `lstat`, 1 means `stat`.

    -1 is the answer for a path that does not exist, for one this process
    cannot stat, and for a target whose `struct stat` the offsets above do not
    describe. All three are "there is no mode here", and a caller that has to
    tell them apart is asking a question the C library's error accessor would
    answer, which this path cannot bind (`__error`, at the top of this file).
    """
    var buf: Pointer[UInt8] = fs_stat_fill(p, follow)
    if buf == 0:
        return 0 - 1
    return le16(buf, 4)


def fs_stat_field64(p, follow, at) -> int:
    """The 64-bit field of `stat`/`lstat` on `p` at byte `at`, or -1.

    One function for `st_ino`, `st_size`, `st_blocks` and `st_blksize` rather
    than four that each pass a different constant, because the reading is the
    same instruction sequence four times over and a second implementation of it
    is a second thing to be wrong. The offset is a PARAMETER because a
    module-level constant is not exported as a word across a dylib boundary.
    """
    var buf: Pointer[UInt8] = fs_stat_fill(p, follow)
    if buf == 0:
        return 0 - 1
    return le64(buf, at)


def fs_stat_field16(p, follow, at) -> int:
    """The 16-bit field of `stat`/`lstat` on `p` at byte `at`, or -1.

    `st_mode` and `st_nlink`. The mode is what every predicate above is
    `S_IFxxx` of, and its width being 16 is why those comparisons are against
    `32768` and not against a value read at 32 bits: a 32-bit read at offset 4
    would take `st_nlink` as its high half.
    """
    var buf: Pointer[UInt8] = fs_stat_fill(p, follow)
    if buf == 0:
        return 0 - 1
    return le16(buf, at)


def fs_stat_field32(p, follow, at) -> int:
    """The 32-bit field of `stat`/`lstat` on `p` at byte `at`, or -1.

    `st_uid`, `st_gid` and `st_rdev`. The field is 32 bits in the layout above
    and reading it as 64 would take the four bytes of padding after it, so the
    width is the field's and not the alignment's.
    """
    var buf: Pointer[UInt8] = fs_stat_fill(p, follow)
    if buf == 0:
        return 0 - 1
    return le32(buf, at)


def fs_realpath(p) -> str:
    """`realpath(p, NULL)`: a `malloc`'d absolute path, or 0.

    The C library allocates, so the caller owns the result and it is already
    absolute, normalized and free of symbolic links and `..`.
    """
    return realpath(p, 0)


def fs_rename(a, b) -> int:
    """`rename(a, b)`: atomic, and it replaces `b` if `b` is there."""
    return rename(a, b)


def fs_rmdir(p) -> int:
    """`rmdir(p)`: 0 on success, -1 on failure."""
    return rmdir(p)


def fs_unlink(p) -> int:
    """`unlink(p)`: 0 on success, -1 on failure."""
    return unlink(p)


def fs_free(p) -> int:
    """`free(p)`, for a buffer this module allocated that the caller is done
    with. Nothing above calls it: the strings `os` and `os.path` return are
    the caller's to keep, and releasing one while a derived string still points
    into it is the caller's decision, not this module's."""
    return free(p)


# ── What the KERNEL says, rather than what the filesystem says ───────────────
#
# Two C library calls, both of which `formal/hostmods/platform.mojo` needs and
# both of which belong here for the reason at the top of the file: this is the
# auditable answer to "what does this backend ask of the operating system".
#
#   * `uts_str(field)` is `uname(3)`, which is five NUL-TERMINATED `char[256]`
#     fields in the caller's buffer. It is read FIELD BY FIELD one byte at a
#     time for the same reason `struct stat` is (`fs_stat_layout_ok` and the
#     `ST_DEV` block above): the source declares no struct, so the offsets are
#     the ABI's, and an offset that is wrong reads a neighbouring field
#     rather than failing.
#
#   * `kern_str(name)` is `sysctlbyname(3)`, the other way to ask the kernel a
#     question that has no syscall of its own.

def uts_field_bytes() -> int:
    """The size of one `uname(3)` field on this target: 256.

    MEASURED, not assumed. Five fields at 256 bytes each is what
    `<sys/utsname.h>` on this SDK declares, and the measured answer agrees:
    reading a filled `utsname` at offsets 0, 256, 512, 768 and 1024 yields
    `Darwin`, the node name, the release, the version string and `arm64` —
    which is `os.uname()`'s own order — and offset 1280 is past the end and
    empty. It is a FUNCTION rather than a module-level constant because a
    module-level name is not exported as a word (`formal/hostmods/sys.mojo`'s
    docstring), and a caller that needs the number has to be able to ask for it.
    """
    return 256


def uts_str(field) -> str:
    """Field `field` of `uname(3)`, in a `malloc`'d copy the caller owns.

    `field` is 0 for the system name, 1 for the node name, 2 for the release,
    3 for the version and 4 for the machine — the order `os.uname()` returns
    them in, which is the order CPython's `platform.uname()` reads them from.

    A COPY, not an interior pointer. The C library fills a buffer the CALLER
    supplies, so a pointer into it would hand back something the caller has to
    keep alive and knows nothing about; a `malloc`'d copy is a string the caller
    owns and releases with `platform.free_string` (or `os.os_free`, which is the
    same `free`).

    THE TERMINATOR IS CHECKED, and that check is the reason the field loop
    exists at all. POSIX says each field is NUL-terminated, so the natural
    spelling is `str_dup(base + 256 * field)` — and if a field ever were not
    terminated, `strlen` would walk off the end of a 1280-byte buffer into
    whatever follows it in the heap and return a number nobody can check. So
    the field is scanned for its own NUL within its 256 bytes first, and a
    field without one yields `""`: an honest wrong-looking answer for an
    impossible layout beats an unbounded read.

    The scan is a one-byte load and is spelled `q: Pointer[UInt8] = f + n`
    then `q.value()` — an EXPRESSION cannot be asked for a pointee it does not
    declare, which is the same fact `json.mojo`'s `byte_at` is written around
    and the reason this is not `(f + n).value()`.

    One `uname(3)` call per invocation, because this path has nowhere to keep
    the answer between calls (there is no module storage, so CPython's
    `_uname_cache` has nowhere to live) and a stale kernel answer would be a
    wrong one anyway.
    """
    var w = uts_field_bytes()
    var b: Pointer[UInt8] = malloc(w * 5)
    memset(b, 0, w * 5)
    if uname(b) != 0:
        free(b)
        return ""
    if field < 0:
        free(b)
        return ""
    if field > 4:
        free(b)
        return ""
    var f = b + w * field
    var n = 0
    var ok = 0
    while n < w:
        var q: Pointer[UInt8] = f + n
        if q.value() == 0:
            ok = 1
            break
        n = n + 1
    var out = ""
    if ok == 1:
        out = str_copy(str_alloc(n), f, n)
    free(b)
    return out


def kern_str(name) -> str:
    """The value of the kernel string MIB `name`, or `""` if there is no such.

    `sysctlbyname(name, …)` with the two-call idiom: ask once with no buffer to
    learn the size, then once into a buffer of exactly that size. The size is a
    run-time value, so the buffer cannot be a literal-sized one, and a fixed
    256 would be a module that silently truncates a long value — which is the
    failure `time.mojo`'s docstring calls a wrong `time.time()`, and the reason
    a probe is done here rather than a guess.

    The reported size INCLUDES the terminator, so the returned buffer is cut
    to one byte shorter: what the kernel wrote is a string and the answer is
    the string, not the string plus its own length.

    `""` for a name the kernel does not have, which is `sysctlbyname`'s own
    failure (it returns non-zero and writes nothing) and is also CPython's
    answer for an unknown version: `platform.mac_ver()` returns `''` when it
    cannot read the product version. There is no error to raise on this path
    (FORMAL.md phase 7), and a caller distinguishing "no such name" from "an
    empty value" is asking a question this target cannot answer.
    """
    var np: Pointer[Int64] = malloc(8)
    np[0] = 0
    if sysctlbyname(name, 0, np, 0, 0) != 0:
        free(np)
        return ""
    var sz = np[0]
    if sz < 1:
        free(np)
        return ""
    var v = str_alloc(sz)
    np[0] = sz
    var rc = sysctlbyname(name, v, np, 0, 0)
    free(np)
    if rc != 0:
        return v
    return str_trunc(v, sz - 1)
