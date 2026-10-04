"""`glob` — CPython's pattern-matching directory listing, for the formal backend.

`formal/imports.py`'s FIRST resolution pass finds a `.mojo` source for a name in
a search root and that wins outright, over the host-module list, so this file is
what `import glob` binds to. It is the LARGEST unclaimed row in the sweep's
host-import ranking — 50 files blocked, 15 of them naming it — and the ranking
that says so is `tools/formal_sweep_causes.py --host bugs/sweeps/sweep-arm-9.txt`.

WHAT IS HERE
------------
`glob` and `glob_free`, plus CPython's own helpers under CPython's own names
(`has_magic`, `escape`, `_glob0`, `_glob1`, `_glob2`, `_rlistdir`, `_iglob`,
`_ishidden`, `_isrecursive`) so the body can be read line against line against
CPython 3.14's own `glob.py`. **The module's whole public surface is therefore
`escape`, `glob`, `glob_free`, `has_magic`** — the underscore names are not
exported at all, because `doc/ABI.md`'s export rule excludes a leading `_`
(measured: a call to `glob._ishidden` is refused with "`glob` is a linked module
but it exports no `_ishidden`"), which is the arrangement
`formal/hostmods/textwrap.mojo` and `formal/hostmods/tempfile.mojo` already
have.

ZERO admitted contracts, and that is the claim rather than an absence: every
answer this module gives is either arithmetic over bytes a string already is, a
name this module allocated, or a decision about names the filesystem already
holds — `test_formal_admitted.py` records `glob: 0` and
`formal/hostmods/glob.mojo` is the reason that zero is the right number.

THE ANSWER IS A BLOB, AND THAT IS THE SAME DECISION `os.listdir` MADE
--------------------------------------------------------------------
CPython's `glob` returns a `list` of strings. A list's length has to be known
when it is built on this path (`bugs/FORMAL_listdir_no_run_time_sequence.md`
items 2 and 3), and `**` under `recursive` makes the length unknowable before the
tree has been walked — which is why the (now deleted) `glob`/`copy`/`collections`
measurement record concluded that a real `glob` was blocked on a capability rather
than on a module. **That conclusion was half wrong and the half that was wrong
was the interesting one:** `os.listdir` already answers a run-time-length
container, because `malloc` takes a run-time size and its memory outlives the
function that asked for it. So `glob` builds the same shape — `[count:i64][char*]…`
in `malloc`'d memory — declares `-> List[String]` (which is what puts the CONTAINER
kind in this module's manifest, and a container kind is the one thing a caller
cannot derive: a list is one word, so the C signature is `int64_t` whether it is
declared a list or an integer), and the caller writes `len(paths)`, `paths[i]` and
`for p in paths`.

`_rlistdir` is the one function with no static bound at all, so it is written the
way `os.walk` is written and for the same reason: a counting pass and a filling
pass, with the count from the first deciding the allocation for the second. The
cost is one extra walk of the tree and the benefit is that word 0 of the answer
is a fact about the filesystem rather than a property of this program.

**THE CAPACITY IS NOT EXACT AND THE LENGTH IS, and the difference matters to say
out loud.** `os.listdir` allocates `8 * (1 + n)` for an `n` it counted, and its
docstring says why: "a blob with room to spare would have a length that is a
property of the program rather than of the directory". This module's blobs are
sized by the worst case at each step — the number of entries in a directory for
`_glob1`, the sum of the per-directory answers for `_iglob`'s accumulator — while
word 0 is always the number of answers. Nothing observes a blob's capacity: `len`,
`[i]`, `for` and `free` all read word 0. The LENGTH is the property callers can
be wrong about, so the length is exact everywhere here.

EVERY STRING IN A BLOB THIS MODULE RETURNS IS A FRESH BUFFER
------------------------------------------------------------
`os.listdir`'s entries are aliases into the blob's own storage, and its
`listdir_free` releases them. Here the inputs come from `os.path`'s `dirname` /
`basename` / `join`, and those three have DIFFERENT ownership rules — `basename`
and `join(a, b)` with an empty `a` return an ALIAS into an argument, and
`join(a, b)` with a non-empty `a` allocates — so an answer assembled from them
would have elements of three different provenances and no rule a caller could
apply. Every element is therefore `str_dup`'d on the way in, and every blob this module
builds is released with `_blob_free` — the strings, then the header. There is
deliberately no "free the header only" second release: `_rlistdir_fill` writes
its words into `_glob2`'s blob rather than building one of its own, so there is
no point in this module where one blob's words are moved into another's, and a
release that dropped the strings would be a way to leak them by accident.

A NOTE ON `os.path.join` AND WHAT IT COSTS TO CALL
--------------------------------------------------
`join` is CPython's and allocates for every call except two: an absolute `b`, and
an empty `a` (where CPython's answer is `b` itself). Every join here has a
basename for `b` — `basename` never begins with a separator on this target,
because `os/path/__init__.mojo`'s `split` strips trailing ones — so **a join
allocates if and only if its first argument is non-empty**, which is the rule the
four frees in this module are written against. Where the answer is an alias the
call site frees nothing, and that is not a leak: it never allocated.

`KEYWORD ARGUMENTS AND DEFAULTS, and why `recursive` is not keyword-only
-----------------------------------------------------------------------
CPython's signature is `glob(pathname, *, root_dir=None, dir_fd=None,
recursive=False, include_hidden=False)` — four KEYWORD-ONLY parameters. A
cross-dylib call reads the callee's parameter NAMES and not its signature
(`bugs/FORMAL_functools_is_unbuildable_as_a_host_module.md`'s neighbour), so
`recursive` and `include_hidden` are declared POSITIONAL here and a caller who
passes them by name binds. This is a deliberate, documented divergence: it is
strictly more permissive than CPython (`glob(pat, True)` binds here and is a
`TypeError` there), and it is the only spelling this tree's 15 callers can make —
three of them write `recursive=True`.

The DEFAULTS are declared (`= 0`) for the same reason `formal/hostmods/
struct.mojo`'s five value slots are: a parameter the callee declares and the
caller omits gets a register home whether or not the caller mentions it, and a
register nothing wrote is whatever the caller last put there. Eleven of the 15
callers write `glob(pattern)` with one argument, so this is the row's dominant
spelling and not an edge case.

WHAT IS NOT HERE, AND WHY
-------------------------
  * `iglob`, `glob0`, `glob1`, `glob2`, `iglob`'s `include_hidden` GENERATOR —
    a generator has to survive between two calls and a value on this path is one
    64-bit word. `glob` is the eager form and `iglob` is the shape that cannot
    be eager, which is the same pair as `os.listdir`/`os.walk` and
    `fnmatch.iglob`, both named at their own definitions.
  * `root_dir` and `dir_fd` — `dir_fd` is `openat`/`fstatat` over a directory
    descriptor, and a descriptor a caller opened is a second thing for a module
    to name; no file in this repository passes either. `root_dir` is reachable
    (it is a prefix on every answer and a different base for every scan) and is
    absent because nothing here spells it, which is the same reason
    `formal/hostmods/html.mojo` gives for `unescape`'s neighbour: a name to add
    with its caller, not to approximate.
  * `escape` is HERE (see its own docstring) and `has_magic` is here because
    `_iglob` asks both on every level of every pattern.
  * `translate`-shaped surprises: there are none. This module calls
    `formal/hostmods/fnmatch.mojo`'s `match_any`, which is CPython's
    `fnmatch.filter`'s predicate, so the pattern language is the ONE matcher the
    tree has and a pattern this module and CPython disagree about is a bug in
    one of them rather than in a third copy.

THE ORDER IS CPython's, AND THAT IS A MEASUREMENT NOT A PROMISE
---------------------------------------------------------------
CPython's docstring says "The order of the returned paths is undefined. Sort them
if you need a particular order", which means a differential test has to decide
what it compares. `test_formal_glob.py` compares the ORDER where CPython's order
is determined (a single directory, which is `os.scandir` order, which is the same
`readdir` order `os.listdir` gives and which this module walks) and the SET
where it is not (`**` under `recursive`, where CPython's order is the order a
recursive generator happens to produce). Both are checked on BOTH backends,
because a directory walk with a blob index is exactly the shape where a
register-width difference shows up as a silently wrong answer rather than as a
refusal.

THE HIDDEN-FILE RULE IS THE SURPRISE, AND IT IS TWO DIFFERENT RULES
------------------------------------------------------------------
CPython's `_glob1` filters hidden NAMES unless the PATTERN is hidden
(`_ishidden(pattern)`, so `.*` sees them), while `_rlistdir` filters hidden
ENTRIES on `include_hidden` alone — so `glob("d/**", recursive=True)` never
yields a hidden file even when the pattern is exactly `**`. Both rules are
transcribed rather than reconciled, because CPython is the contract and a
reconciled version would agree with CPython on a corpus with no dotfiles in it.
`test_formal_glob.py`'s `hidden` group exists for exactly that: a fixture tree
with `.dotfile`, `.dir/` and a `.*` pattern beside a `**` one, so the two rules
are asked separately and cannot drift into one.
"""

from os import listdir, listdir_len, listdir_get, listdir_free
from os.path import isdir, lexists, join
from os._syscalls import str_dup, str_len, str_cmp, str_prefix
from os._syscalls import str_alloc, str_put
from fnmatch import match_any


# ── byte access ────────────────────────────────────────────────────────────
#
# HERE rather than imported, for `formal/hostmods/fnmatch.mojo`'s reason: a
# hostmod is its own dylib, so a call into another one is a cross-dylib call for
# a load and a memcpy, and these are a few lines with no logic beyond "read a
# byte". The rule about not answering a question twice is about QUESTIONS.

def _byte(s, i) -> int:
    """The byte at `s + i`, or 256 at or past the NUL."""
    if i >= strlen(s):
        return 256
    var q: Pointer[UInt8] = s + i
    return q.value()


# ── the pattern predicates ─────────────────────────────────────────────────

def has_magic(s) -> int:
    """CPython's `has_magic`: 1 when `s` holds a `*`, a `?` or a `[`.

    `magic_check = re.compile('([*?[])')`, and a character class is a SET, so
    this is a scan over three bytes rather than a matcher — there is nothing for
    `formal/hostmods/re.mojo`'s engine to do here.
    """
    n = strlen(s)
    i = 0
    while i < n:
        c = _byte(s, i)
        if c == 42 or c == 63 or c == 91:
            return 1
        i = i + 1
    return 0


def escape(pathname) -> str:
    """CPython's `glob.escape`: every metacharacter wrapped in `[...]`.

    `magic_check.sub(r'[\\1]', pathname)` — the drive part is split off first and
    not escaped, because "metacharacters do not work in the drive part and
    shouldn't be escaped". On a POSIX target `splitdrive` is `("", p)`
    unconditionally (`formal/hostmods/os/path/__init__.mojo`), so there is no
    drive to protect here and the scan runs over the whole string.

    The substitution is written as the SCAN it is rather than through
    `formal/hostmods/re.mojo`: a backreference and a replacement template are a
    different shape from the span matching that module does, and
    `str_replace_all` cannot do it either, because the three metacharacters each
    need their OWN brackets.
    """
    n = strlen(pathname)
    # 4n + 1 is the WORST case and not an estimate: each of three bytes becomes
    # three (`*` -> `[*]`), so a string of nothing but metacharacters needs 3n and
    # 4n has room to spare. It is the same shape as
    # `formal/hostmods/html.mojo`'s expansion bound and for the same reason —
    # an under-estimate here is a heap overflow on a short input, not a slow
    # path.
    out = str_alloc(4 * n + 1)
    var used = 0
    var i = 0
    while i < n:
        c = _byte(pathname, i)
        if c == 42 or c == 63 or c == 91:
            used = str_put(out, used, "[", 1)
            used = str_put(out, used, pathname + i, 1)
            used = str_put(out, used, "]", 1)
        else:
            used = str_put(out, used, pathname + i, 1)
        i = i + 1
    memset(out + used, 0, 1)
    return out


def _ishidden(path) -> int:
    """CPython's `_ishidden`: 1 when the first character is `.`.

    `path[0] in ('.',)` on an EMPTY string is `False` in CPython because the
    index raises and… it does not: CPython's own `_ishidden` is only ever called
    with a non-empty basename, and this returns 0 for `""` rather than
    reproducing an `IndexError` there is no way to raise on this path
    (FORMAL.md phase 7).
    """
    if _byte(path, 0) == 46:
        return 1
    return 0


def _isrecursive(pattern) -> int:
    """CPython's `_isrecursive`: 1 for exactly `**`."""
    if str_cmp(pattern, "**") == 0:
        return 1
    return 0


# ── the blobs ──────────────────────────────────────────────────────────────

def _blob_new(cap) -> Pointer[Int64]:
    """A `[count][char *]…` blob with room for `cap` strings, count 0.

    Zeroed rather than left alone, so a blob's word 0 is a count from the moment
    it exists and a caller that reads it before the fill finishes reads 0 and not
    whatever `malloc` returned.
    """
    var b: Pointer[Int64] = malloc(8 * (1 + cap))
    memset(b, 0, 8 * (1 + cap))
    b[0] = 0
    return b


def _blob_free(paths: Pointer[Int64]) -> int:
    """Release a blob of this module's own making: every string, then the header.

    The same shape as `os.listdir_free`, and the same contract: the CALLER owns
    the result and every name in it. 0 for a 0, so the same call releases
    "nothing" and a caller that never got a listing does not have to test first.
    """
    if paths == 0:
        return 0
    i = 0
    while i < paths[0]:
        free(paths[1 + i])
        i = i + 1
    free(paths)
    return 0


def glob_free(paths: Pointer[Int64]) -> int:
    """Release a `glob` answer and every path in it. 0.

    The public spelling of `_blob_free`, for the same reason
    `os.listdir_free` and `os.walk_free` are public: the answer is a blob the
    CALLER owns, and a value on this path has no `__del__`, so releasing it is
    the caller's to spell. `formal/imports.py`'s `HOST_OWNED_BLOBS` names this
    export so a STORE through the result is refused rather than obeyed.
    """
    if paths == 0:
        return 0
    i = 0
    while i < paths[0]:
        free(paths[1 + i])
        i = i + 1
    free(paths)
    return 0


def _single(s) -> Pointer[Int64]:
    """A one-element blob holding a copy of `s`."""
    var b: Pointer[Int64] = _blob_new(1)
    b[0] = 1
    b[1] = str_dup(s)
    return b


def _empty() -> Pointer[Int64]:
    """A blob with a count and nothing in it — `[]`, not 0.

    The distinction is CPython's and it is observable: `len(glob("nothing*"))` is
    0, and 0 is what `os.listdir` answers for "no such directory", so an empty
    answer has to be a blob whose count is 0 or a caller cannot tell "matched
    nothing" from "there is no directory here".
    """
    return _blob_new(0)


# ── `_glob0`: a LITERAL basename ────────────────────────────────────────────

def _glob0(dirname, basename, dironly, include_hidden) -> Pointer[Int64]:
    """CPython's `_glob0`: the one existence check, for a basename with no magic.

    `if basename: if _lexists(_join(dirname, basename)): return [basename]` and
    otherwise "patterns ending with a slash should match only directories", so
    `a/b/` yields `a/b/` for a directory and nothing for a file.

    `dironly` and `include_hidden` are taken and ignored, which is CPython's own
    shape (`_glob0` has no use for either) and not an omission here: the caller
    in `_iglob` passes them to one function that stands for three.

    CPython yields the BASENAME and lets its caller do the `os.path.join`, and
    this returns the same thing, so the join happens in exactly one place.
    """
    if str_len(basename) > 0:
        j = join(dirname, basename)
        hit = lexists(j)
        # `join` allocates if and only if its first argument is non-empty (see
        # the module docstring), and a basename never begins with a separator.
        if str_len(dirname) > 0:
            free(j)
        if hit == 1:
            return _single(basename)
        return _empty()
    if isdir(dirname) == 1:
        return _single("")
    return _empty()


# ── `_glob1`: one pattern component, in one directory ──────────────────────

def _glob1(dirname, pattern, dironly, include_hidden) -> Pointer[Int64]:
    """CPython's `_glob1`: the entries of `dirname` that match `pattern`.

    Three filters, in CPython's order, and the order is only here because the
    first one costs a `stat` per entry:

      * `dironly` — `_iterdir`'s `entry.is_dir()` test, which is `_iglob`'s
        dirname recursion asking for directories only;
      * hidden NAMES, dropped unless `include_hidden` or the PATTERN is hidden;
      * `fnmatch.filter(names, pattern)`, which is `formal/hostmods/fnmatch.mojo`'s
        `match_any` over the same names in the same order.

    The capacity is the directory's entry count and the LENGTH is the number that
    matched; the module docstring says why those are allowed to differ.

    `dirname` is CPython's `root_dir`, which is `""` at the top of a relative
    pattern — and `_listdir("")` scans `os.curdir`, so a join with an empty
    first argument contributes no separator and the answers are bare names. That
    is why the scan directory is computed separately from the join prefix: the
    two are the same string for every pattern with a directory in it and
    different for every pattern without one.

    A DIRECTORY THAT IS NOT THERE IS AN EMPTY ANSWER, and `os.listdir`'s `0` is
    how that arrives: `listdir_len(0)` is **-1**, which is what tells "no such
    directory" from "an empty directory" (0), and a blob sized by it would be
    `malloc(0)` with word 0 written past the end of it. CPython's `_iterdir`
    swallows the `OSError` and yields nothing, so the count is clamped to 0 here
    and the entry loop below never runs. Measured, and not hypothetically: this
    is the crash `glob(".tmp/g/tree/**/*.txt", recursive=True)` produced before
    the clamp, because a wrong base directory in the recursion (see
    `_rlistdir_fill`) sent `_glob1` after `sub/deep` as though it were `deep`.
    """
    var scan = dirname
    if str_len(dirname) == 0:
        scan = "."
    names = listdir(scan)
    n = listdir_len(names)
    if n < 0:
        n = 0
    var b: Pointer[Int64] = _blob_new(n)
    var k = 0
    var i = 0
    var keep = include_hidden
    if _ishidden(pattern) == 1:
        keep = 1
    while i < n:
        nm = listdir_get(names, i)
        if keep == 1 or _ishidden(nm) == 0:
            hit = 1
            if dironly == 1:
                # Only this branch needs the joined path, so only this branch
                # allocates one — and the free is on the same condition the
                # allocation was, which is the rule the module docstring states.
                p = join(dirname, nm)
                hit = isdir(p)
                if str_len(dirname) > 0:
                    free(p)
            if hit == 1 and match_any(nm, pattern) == 1:
                b[1 + k] = str_dup(nm)
                k = k + 1
        i = i + 1
    b[0] = k
    listdir_free(names)
    return b


# ── `_rlistdir`: every name at and below a directory ────────────────────────

def _rlistdir_count(dirname, dironly, include_hidden) -> int:
    """How many names `_rlistdir` yields, for the sizing pass.

    The counting twin of `_rlistdir_fill`, and the reason it is a separate
    A DIRECTORY THAT IS NOT THERE COUNTS ZERO, for `_glob1`'s reason: CPython's
    `_iterdir` swallows the `OSError` and yields nothing. This is not
    hypothetical on this path — a file recursed into yields `listdir`'s `0` and
    `listdir_len`'s **-1**, and a count that started at -1 would size every blob
    in the tree one word short.

    `""` SCANS THE CURRENT DIRECTORY rather than nothing, which is CPython's
    `_iterdir("")` → `os.curdir` and is what makes `glob("**", recursive=True)`
    list the directory it was run in.
    """
    var scan = dirname
    if str_len(dirname) == 0:
        scan = "."
    names = listdir(scan)
    n = listdir_len(names)
    if n < 0:
        n = 0
    var total = 0
    var i = 0
    while i < n:
        nm = listdir_get(names, i)
        if include_hidden == 1 or _ishidden(nm) == 0:
            p = join(dirname, nm)
            if dironly == 0 or isdir(p) == 1:
                total = total + 1 + _rlistdir_count(p, dironly, include_hidden)
            if str_len(dirname) > 0:
                free(p)
        i = i + 1
    listdir_free(names)
    return total


def _rlistdir_fill(dirname, prefix, dironly, include_hidden,
                   b: Pointer[Int64], w) -> int:
    """Write `_rlistdir`'s names at blob word `w` on, and return the next free word.

    THE TWO DIRECTORIES ARE NOT THE SAME STRING, and that is the whole subtlety
    of CPython's `_rlistdir`:

        for x in names:
            yield x
            path = _join(dirname, x) if dirname else x   # where to LOOK
            for y in _rlistdir(path, ...):
                yield _join(x, y)                        # what to CALL it

    `path` descends into the tree and `x`/`_join(x, y)` is what comes out, so a
    name is RELATIVE TO THE DIRECTORY `_rlistdir` WAS ASKED ABOUT, not to the
    directory it is standing in when it finds it. `d/a/b.txt` under `d` is
    `a/b.txt` — writing `b.txt`, or `deep/d.txt` from a scan of `deep`, is the
    bug this parameter exists to prevent, and it is a bug this module HAD: the
    first version passed no prefix and every answer below the first level was a
    bare name, which is also how `glob("d/**/*.txt", recursive=True)` ended up
    scanning `d/deep` — a directory that does not exist — and taking
    `listdir_len`'s -1 for a count (see `_glob1`).

    The recursion is UNBOUNDED, which is CPython's own shape: `_rlistdir` calls
    itself on every non-hidden entry and lets the C library's refusal to open a
    file as a directory end the descent. A symbolic link to an ancestor therefore
    loops forever here exactly as it does in CPython 3.14 — matching it is the
    contract, and the depth is the tree's own, the same property
    `formal/hostmods/fnmatch.mojo`'s `match_core` recursion has.
    """
    var scan = dirname
    if str_len(dirname) == 0:
        scan = "."
    names = listdir(scan)
    n = listdir_len(names)
    if n < 0:
        n = 0
    var i = 0
    while i < n:
        nm = listdir_get(names, i)
        if include_hidden == 1 or _ishidden(nm) == 0:
            p = join(dirname, nm)
            if dironly == 0 or isdir(p) == 1:
                # `rel` is the name this entry is CALLED, and it is an ALIAS
                # into the listdir blob when `prefix` is empty — which is why
                # the word stored in `b` is a `str_dup` of it and why `rel`
                # outlives neither `listdir_free` below nor the recursion.
                rel = join(prefix, nm)
                b[w] = str_dup(rel)
                w = w + 1
                w = _rlistdir_fill(p, rel, dironly, include_hidden, b, w)
                if str_len(prefix) > 0:
                    free(rel)
            if str_len(dirname) > 0:
                free(p)
        i = i + 1
    listdir_free(names)
    return w


# ── `_glob2`: `**` ─────────────────────────────────────────────────────────

def _glob2(dirname, pattern, dironly, include_hidden) -> Pointer[Int64]:
    """CPython's `_glob2`: the `**` pattern, and the only unbounded one.

        if not dirname or _isdir(dirname): yield pattern[:0]
        yield from _rlistdir(dirname, dir_fd, dironly, include_hidden)

    The leading EMPTY STRING is CPython's and is load-bearing twice: it is what
    makes `d/**` include `d` itself (zero directories matched), and `iglob` then
    DROPS it for a pattern that is `**` in the first two characters, which is why
    `glob("**", recursive=True)` does not answer `""`. Both halves are here and
    the drop is in `glob`.

    The count comes from `_rlistdir_count` and the words from `_rlistdir_fill`,
    which writes them into THIS blob rather than building one of its own — the
    same arrangement `os.walk` uses, and for the same reason: a blob's length
    has to be decided before the first word is stored.
    """
    n = _rlistdir_count(dirname, dironly, include_hidden)
    var b: Pointer[Int64] = _blob_new(1 + n)
    var w = 1
    if str_len(dirname) == 0 or isdir(dirname) == 1:
        b[w] = str_dup("")
        w = w + 1
    w = _rlistdir_fill(dirname, "", dironly, include_hidden, b, w)
    b[0] = w - 1
    return b


# ── `_iglob`: one pattern, at any depth ────────────────────────────────────

def _glob_in_dir(dirname, basename, mode, dironly, include_hidden) -> Pointer[Int64]:
    """The per-directory half of `_iglob`, dispatched on CPython's three helpers.

    CPython picks a function object (`glob_in_dir = _glob2` / `_glob1` /
    `_glob0`) and a value on this path is one 64-bit word, so there is no word
    that denotes a function to put in it (`bugs/FORMAL_a_type_cannot_be_
    constructed_or_cloned_at_run_time.md`). The choice is therefore an integer,
    and it is the same choice at the same point in the same order.
    """
    if mode == 0:
        return _glob0(dirname, basename, dironly, include_hidden)
    if mode == 1:
        return _glob1(dirname, basename, dironly, include_hidden)
    return _glob2(dirname, basename, dironly, include_hidden)


def _iglob(pathname, recursive, dironly, include_hidden) -> Pointer[Int64]:
    """CPython's `_iglob`: every path under `pathname` that matches it.

    CPython's is a GENERATOR and the recursion is lazy, which is the one place
    this transcription cannot follow it literally: `dirs` here is a blob and the
    loop over it is an index. Two consequences, both stated where they happen:

      * **two passes over `dirs`**, one to total the answers and one to write
        them, because a blob's allocation has to be decided before the first
        word is stored. This is `os.listdir`'s and `os.walk`'s bargain, and the
        cost is a second scan of each directory at each level.
      * the per-directory answers are BUILT TWICE, once per pass, and released
        after each is consumed — they are this module's own blobs, so they are
        freed with `_blob_free`.

    `dironly` is CPython's own flag: `_iglob` passes 1 when it recurses into the
    pattern's DIRECTORY, so every intermediate answer is a list of directories
    and the leaves are the only answers that can be files.
    """
    dn = dirname(pathname)
    bn = basename(pathname)
    if has_magic(pathname) == 0:
        # No magic: the answer is the pattern itself or nothing. CPython tests
        # `_lexists(_join(root_dir, pathname))` and `root_dir` is `""`, so this
        # is `lexists(pathname)` — not a join of the two halves, which would
        # spell the directory twice.
        if str_len(bn) > 0:
            if lexists(pathname) == 1:
                return _single(pathname)
            return _empty()
        if isdir(dn) == 1:
            return _single(pathname)
        return _empty()
    if str_len(dn) == 0:
        if recursive == 1 and _isrecursive(bn) == 1:
            return _glob_in_dir(dn, bn, 2, dironly, include_hidden)
        return _glob_in_dir(dn, bn, 1, dironly, include_hidden)
    # `dirname != pathname` is CPython's guard against a drive or UNC path whose
    # own name carries magic characters: without it this recurses on the same
    # string for ever. It is transcribed rather than assumed away, because on a
    # POSIX target it is also the only thing keeping `//`-shaped patterns finite.
    var dirs: Pointer[Int64]
    if str_cmp(dn, pathname) != 0 and has_magic(dn) == 1:
        dirs = _iglob(dn, recursive, 1, include_hidden)
    else:
        dirs = _single(dn)
    var mode = 0
    if has_magic(bn) == 1:
        if recursive == 1 and _isrecursive(bn) == 1:
            mode = 2
        else:
            mode = 1
    # Pass one: how many answers in all.
    var total = 0
    var k = 0
    while k < dirs[0]:
        d = dirs[1 + k]
        part = _glob_in_dir(d, bn, mode, dironly, include_hidden)
        total = total + part[0]
        _blob_free(part)
        k = k + 1
    var out: Pointer[Int64] = _blob_new(total)
    # Pass two: write them, in `dirs` order and in each part's order.
    var w = 1
    k = 0
    while k < dirs[0]:
        d = dirs[1 + k]
        part = _glob_in_dir(d, bn, mode, dironly, include_hidden)
        var j = 0
        while j < part[0]:
            out[w] = str_dup(join(d, part[1 + j]))
            w = w + 1
            j = j + 1
        _blob_free(part)
        k = k + 1
    out[0] = w - 1
    _blob_free(dirs)
    return out


# ── the public entry point ─────────────────────────────────────────────────

def glob(pathname, recursive = 0, include_hidden = 0) -> List[String]:
    """CPython's `glob.glob(pathname, recursive=False, include_hidden=False)`.

    `List[String]`, which on this path is the annotation that means "one word
    pointing at a `[count][char *]…` blob" — the shape the module docstring
    describes, and the reason a caller can write `len(paths)`, `paths[i]` and
    `for p in paths` instead of an accessor per operation. It costs nothing: the
    C signature is `int64_t` either way, because a list is one word, so this is
    metadata and not an ABI change.

    `recursive` and `include_hidden` are INTEGERS and are declared positional
    rather than keyword-only; see the module docstring for why, and for why the
    defaults are declared at all.

    THE EMPTY-FIRST-ANSWER RULE, transcribed: `iglob` pulls the first answer off
    its generator and puts it back only if it is non-empty, for a pattern that is
    empty or whose first TWO characters are `**` under `recursive`. That is what
    drops the `""` `_glob2` yields first, so `glob("**", recursive=True)` answers
    nothing for a tree with nothing in it rather than answering `[""]`.
    """
    one = _iglob(pathname, recursive, 0, include_hidden)
    if str_len(pathname) == 0 or (recursive == 1 and _isrecursive(str_prefix(pathname, 2)) == 1):
        if one[0] > 0 and str_len(one[1]) == 0:
            dropped = one[1]
            var i = 1
            while i < one[0]:
                one[i] = one[1 + i]
                i = i + 1
            free(dropped)
            one[0] = one[0] - 1
    return one