"""`pathlib` — the pure half of CPython's path handling, for the formal backend.

`formal/imports.py`'s FIRST resolution pass finds a `.mojo` source for a name
in a search root and that wins outright, over the host-module list, so this
file is what `import pathlib` binds to. It lives in `formal/hostmods/`, the
directory that resolver adds as its last search root and that no other
resolver in the tree lists — see `_HOSTMODS_ROOT` for why these did NOT go at
the repository root, where the first three of them captured `import os` in the
compiler's own sources.

WHAT IS HERE, AND WHY IT IS NOT `os.path` AGAIN
------------------------------------------------
`formal/hostmods/os/path/__init__.mojo` is CPython's `posixpath`, with its
answers checked against CPython's own by `test_formal_os.py`. `pathlib` and
`posixpath` OVERLAP, and the overlap is the first thing to get right here:
**a question `os.path` already answers is not answered again in this file.**
`is_absolute` is `os.path.isabs`, `joinpath` is `os.path.join`, and `exists`
/ `is_dir` / `is_file` / the size are `os.path`'s `exists` / `isdir` /
`isfile` / `getsize`. Each is named in "WHAT IS NOT HERE" with the `os.path`
name that answers it, because a module that answers a question twice is two
implementations to keep in step, and this tree has already paid for one of
those — a second implementation of a shift is
`bugs/FORMAL_arm64_lsl_imm_is_wrong_for_every_amount_above_8.md`.

What is left is the part that is pathlib's own and posixpath has no name for:
the DECOMPOSITION of a path into its name, stem, suffix and parent, the three
pure rewritings `with_name`, `with_stem` and `with_suffix`, and `as_posix`,
`relative_to`, `match` and `is_reserved`. Every one is a question with a
scalar answer, and `tools/ab_filelist.py` — the one file in this tree blocked
on `pathlib`, and `tools/ab_compare.py` behind it — wants exactly `as_posix`,
`with_suffix` and `relative_to`.

Two of them overlap `os.path` anyway and the overlap is stated rather than
hidden: `suffix`, `stem` and `parent` are `os.path.splitext`'s second answer
and `os.path.dirname` repackaged, kept here because `with_stem` and
`with_suffix` cannot be written without knowing where the name and the suffix
start, and a program that called `os.path.splitext` and then
`pathlib.with_stem` would walk the path twice.
`test_formal_pathlib.py` checks `suffix`, `stem`, `parent` and `as_posix`
against CPython over one corpus and `test_formal_os.py` checks the posixpath
spellings, so the two cannot drift without one of the two going red.

WHAT IS NOT HERE, AND WHY
-------------------------
  * `Path`, `PurePath`, `PurePosixPath`, `PosixPath`, `WindowsPath` — TYPES. A
    type is not a value on this path and cannot be returned from a module
    function, let alone stored in a module-level name
    (`bugs/FORMAL_module_state_no_storage.md`). Every function here takes a
    path as a `str`, which is the substitution `sys.mojo` makes for
    `sys.argv` and `os.mojo` makes for `os.environ`.
  * `parts`, `parents`, `suffixes` — SEQUENCES. A list is a blob carved out of
    the frame that built it, so it cannot cross a boundary; `parts("a/b")` is
    `["a", "b"]` and there is no way to hand that back.
  * `stat`, `touch`, `mkdir`, `rmdir`, `unlink`, `rename`, `open`,
    `read_text`, `write_text`, `resolve`, `absolute`, `cwd`, `iterdir`,
    `rglob`, `glob`, `samefile`, `is_mount`, `symlink_to`, `hardlink_to`,
    `chmod`, `owner`, `group` — the filesystem half. `exists`, `is_dir`,
    `is_file` and the size are `os.path`'s; the rest need a stream, a
    directory listing, or an inode, and a directory listing is a run-time-length
    sequence this path cannot build
    (`bugs/FORMAL_listdir_no_run_time_sequence.md`).
  * `is_absolute` (`os.path.isabs`), `joinpath` (`os.path.join`), `as_uri`
    (a percent-encoding, and a str is one so it is not written here rather
    than written twice), `drive` / `root` / `anchor` (a Windows question, and
    this target is POSIX), and every `PureWindowsPath` name.
  * `is_reserved` IS here, and always 0: it exists to catch `CON`, `NUL` and
    their kin, which are reserved on Windows and nowhere on a POSIX target,
    and CPython answers False here too.

A FAILURE IS A SENTINEL, NOT AN EXCEPTION
-----------------------------------------
There is no `try`/`except` on this path (`FORMAL.md` phase 7), so the CPython
calls that raise are documented return values:

  * `relative_to(p, base)` returns `""` when `p` is not under `base`, which
    CPython signals with `ValueError`. `""` is not a value CPython's own
    `relative_to` can return — `relative_to(x, x)` is `"."` — so a caller can
    tell the sentinel from an answer.
  * `with_name`, `with_stem` and `with_suffix` return the path UNCHANGED where
    CPython raises, which is a path with no name (`"/"`, `""`, `"a/.."`) and,
    for `with_suffix`, an argument that is not a suffix at all. Unchanged is
    the one answer a caller can act on, and it is stated at each definition
    rather than left to be found as a surprising string.
"""

# ── byte helpers ───────────────────────────────────────────────────────────
#
# HERE rather than imported, and the reason is worth one line: a hostmod is
# its own dylib, so a call into `json.mojo` would be a cross-dylib call for a
# load and a memcpy. These are twenty lines with no logic in them beyond
# "read a byte" and "copy n bytes", and the rule about not answering a
# question twice is about QUESTIONS.

def byte_or(s, i) -> int:
    """The byte at `s + i`, or 256 at or past the NUL. See `json.mojo`."""
    if i >= strlen(s):
        return 256
    var q: Pointer[UInt8] = s + i
    return q.value()


def put_bytes(out, at, s, n) -> int:
    """`n` bytes of `s` at `out + at`. Returns `at + n`."""
    memcpy(out + at, s, n)
    return at + n


def put_byte(out, at, b) -> int:
    """`out[at] = b & 255`. Returns `at + 1`."""
    var one: Pointer[UInt8] = malloc(1)
    memset(one, b & 255, 1)
    memcpy(out + at, one, 1)
    return at + 1


def tail(s, i) -> str:
    """`s[i:]` as a string, or `""` if `i` is outside it."""
    if i < 0 or i >= strlen(s):
        return ""
    var out: Pointer[UInt8] = malloc(strlen(s) - i + 1)
    var u = put_bytes(out, 0, s + i, strlen(s) - i)
    put_byte(out, u, 0)
    return out


def head(s, n) -> str:
    """The first `n` bytes of `s` as a string, or `""` for `n <= 0`."""
    if n <= 0:
        return ""
    var out: Pointer[UInt8] = malloc(n + 1)
    var u = put_bytes(out, 0, s, n)
    put_byte(out, u, 0)
    return out


def cat_str(a, b) -> str:
    """`a + b`, as a fresh string."""
    var out: Pointer[UInt8] = malloc(strlen(a) + strlen(b) + 1)
    var u = put_bytes(out, 0, a, strlen(a))
    u = put_bytes(out, u, b, strlen(b))
    put_byte(out, u, 0)
    return out


def is_sep(b) -> int:
    """1 for `/`, and 1 for the end of the string as well.

    The end counts as a separator because every loop below ends at the NUL and
    treats "the end" and "the end of a component" alike — a component of length
    zero is exactly what a trailing `/` leaves behind.
    """
    if b == 47:
        return 1
    if b == 0 or b == 256:
        return 1
    return 0


def has_sep(s) -> int:
    """1 if `s` contains a `/`."""
    var i = 0
    while i < strlen(s):
        if byte_or(s, i) == 47:
            return 1
        i = i + 1
    return 0


# ── `as_posix`, the normalisation every other answer is defined in terms of ─

def as_posix(p) -> str:
    """`PurePosixPath(p).as_posix()`.

    The normalisation CPython applies before it will answer any other question
    about the path: a run of separators collapses to one, a `.` component
    disappears, a trailing `/` goes, and `..` STAYS. That last one is the whole
    difference from `os.path.normpath` and the reason this is not that
    function — `normpath("a/../b")` is `"b"`, `PurePosixPath("a/../b")` is
    `"a/../b"`, and a pure path has no directory to resolve against.

    A leading `//` is kept as `//`, which is what CPython does and what POSIX
    calls implementation-defined. An empty path, and a path that was nothing
    but `.` components, are `"."`.
    """
    var n = strlen(p)
    if n == 0:
        return "."
    var out: Pointer[UInt8] = malloc(n + 2)
    var u = 0
    var lead = 0
    while lead < n and byte_or(p, lead) == 47:
        lead = lead + 1
    if lead > 0:
        # `lead == 2` and NOT `lead >= 2`: POSIX calls a leading `//`
        # implementation-defined, and CPython keeps EXACTLY two and collapses
        # three or more to one. Measured: `PurePosixPath("///a").as_posix()` is
        # `"/a"` and `PurePosixPath("//a").as_posix()` is `"//a"`, and a
        # `>=` here answers `"//a"` for both.
        if lead == 2:
            u = put_byte(out, u, 47)
        u = put_byte(out, u, 47)
    var i = lead
    var last = 0
    while i < n:
        var j = i
        while j < n and byte_or(p, j) != 47:
            j = j + 1
        if is_dot(p, i, j) == 0:
            if last > 0 and byte_or(out, last - 1) != 47:
                u = put_byte(out, u, 47)
            u = put_bytes(out, u, p + i, j - i)
            last = u
        i = j
        while i < n and byte_or(p, i) == 47:
            i = i + 1
    if u == 0:
        return "."
    put_byte(out, u, 0)
    return out


def is_dot(s, i, j) -> int:
    """1 if `s[i:j]` is the single component `.`."""
    if j - i != 1:
        return 0
    if byte_or(s, i) == 46:
        return 1
    return 0


def comp_start(s, end) -> int:
    """The index at which the component ENDING at `end` begins."""
    var i = end
    while i > 0 and byte_or(s, i - 1) != 47:
        i = i - 1
    return i


# ── the reads off the end ──────────────────────────────────────────────────

def last_name_at(q) -> int:
    """The index of the last component of the NORMALISED `q`, or -1.

    -1 is "this path has no name". That is the root, and ALSO a path that
    normalised to `.` — CPython's `PurePosixPath(".").parts` is `()`, so `.`
    has no components and therefore no name. Getting that wrong is what made
    `with_name("", "x")` answer `"x"` where CPython answers `"."`: the
    rewritings all ask this one function, so the check belongs HERE rather than
    in each of them.
    """
    if q == ".":
        return 0 - 1
    var i = strlen(q) - 1
    while i >= 0 and is_sep(byte_or(q, i)) == 1:
        i = i - 1
    if i < 0:
        return 0 - 1
    while i >= 0 and is_sep(byte_or(q, i)) == 0:
        i = i - 1
    return i + 1


def lstrip_dots(s) -> int:
    """The index of the first byte of `s` that is not `.`."""
    var i = 0
    while i < strlen(s) and byte_or(s, i) == 46:
        i = i + 1
    return i


def rfind_dot(s, frm) -> int:
    """The LAST index at or after `frm` holding `.`, or -1."""
    var i = strlen(s) - 1
    while i >= frm:
        if byte_or(s, i) == 46:
            return i
        i = i - 1
    return 0 - 1


def suffix_of(nm) -> str:
    """`nm`'s last suffix, by CPython's rule and not by "the last dot".

    The rule strips the LEADING dots first and then takes the last dot of what
    is left, which is why `..` and `...` have NO suffix, `.hidden` has none,
    `..a` has none, and `a.` and `a..` both have `"."`. A version that looked
    for the last dot in the whole name gets five of those six wrong, and
    `PurePosixPath("..").suffix` answering `"."` is a plausible number.
    """
    var d = rfind_dot(nm, lstrip_dots(nm))
    if d < 0:
        return ""
    return tail(nm, d)


def stem_of(nm) -> str:
    """`nm` with its last suffix removed, plus CPython's guard.

    The guard is that a stem of nothing but dots is not a stem: `..` and
    `.hidden` are their OWN stems. And the dot is looked for in the WHOLE name
    here, where `suffix_of` looks in the name with its leading dots stripped —
    the two rules differ, which is why they are two functions.
    """
    var d = rfind_dot(nm, 0)
    if d >= 0:
        var s = head(nm, d)
        if lstrip_dots(s) < strlen(s):
            return s
    return nm


def name(p) -> str:
    """`PurePosixPath(p).name`: the last component, or `""`.

    `""` for the root, for an empty path, and for a path that was nothing but
    `.` components — CPython's `PurePosixPath(".").parts` is `()`, so there is
    no name and that is the one case where `as_posix` and `name` disagree.
    """
    var q = as_posix(p)
    if q == ".":
        return ""
    var at = last_name_at(q)
    if at < 0:
        return ""
    return tail(q, at)


def stem(p) -> str:
    """`PurePosixPath(p).stem`.

    `"x.tar.gz"` is `"x.tar"` — the LAST suffix, not the first — and both rules
    live in `stem_of`.
    """
    return stem_of(name(p))


def suffix(p) -> str:
    """`PurePosixPath(p).suffix`: `".gz"` for `"x.tar.gz"`, `""` for none."""
    return suffix_of(name(p))


def root_of(q) -> str:
    """`q`'s root: `"//"`, `"/"` or `""`, per `as_posix`'s leading-slash rule."""
    if byte_or(q, 0) != 47:
        return ""
    if byte_or(q, 1) == 47:
        return "//"
    return "/"


def parent(p) -> str:
    """`PurePosixPath(p).parent`.

    `"."` for a one-component path, and the ROOT for a top-level one — which
    is where the `//` case earns its keep: `PurePosixPath("//a").parent` is
    `"//"`, not `"/"`, so a parent that trims one separator answers a path
    that does not exist.
    """
    var q = as_posix(p)
    if q == ".":
        return "."
    var at = last_name_at(q)
    if at < 0:
        return q
    if at == 0:
        return "."
    var h = head(q, at - 1)
    if strlen(h) == 0 or h == "/":
        return root_of(q)
    return h


# ── the three pure rewritings ──────────────────────────────────────────────
#
# Each splices a new name over the old one IN PLACE, which is why each starts
# from `last_name_at` and keeps everything before it — the separator included.

def with_name(p, n) -> str:
    """`PurePosixPath(p).with_name(n)`, or `p` unchanged.

    Unchanged for a path with no name (`"/"`, `""`, `"a/.."`, `"."`) and for an
    `n` that CPython refuses — an empty one, or one containing a `/`, which is
    `ValueError("Invalid name")` there. A `n` with a separator in it is the case
    worth naming: splicing it in produces a path with one MORE component than
    the source had, and a program checking `parent` afterwards would see a
    parent that is not the name it just set.
    """
    var q = as_posix(p)
    var at = last_name_at(q)
    if at < 0 or strlen(n) == 0 or has_sep(n) == 1:
        return q
    return cat_str(head(q, at), n)


def with_stem(p, n) -> str:
    """`PurePosixPath(p).with_stem(n)`, or `p` unchanged.

    The suffix SURVIVES: `with_stem("a/b.txt", "y")` is `"a/y.txt"`, not
    `"a/y"`. That is the whole difference from `with_name`, and it is why both
    exist.
    """
    var q = as_posix(p)
    var at = last_name_at(q)
    if at < 0 or strlen(n) == 0:
        return q
    return cat_str(cat_str(head(q, at), n), suffix_of(name(p)))


def with_suffix(p, s) -> str:
    """`PurePosixPath(p).with_suffix(s)`, or `p` unchanged.

    Unchanged for a path with no name, and for an `s` that is not a suffix:
    CPython requires one to start with `.` and to contain no `/`, and raises
    `ValueError` otherwise. `with_suffix(p, "")` REMOVES the suffix, which is
    the spelling `tools/ab_filelist.py` uses — `.with_suffix("")` on a
    `*.mojo` file, to get the module name.

    The name is rebuilt as STEM, so a path with no suffix gains one rather than
    losing its name: `with_suffix("a", ".json")` is `"a.json"`.
    """
    if strlen(s) > 0 and byte_or(s, 0) != 46:
        return as_posix(p)
    if has_sep(s) == 1:
        return as_posix(p)
    var q = as_posix(p)
    var at = last_name_at(q)
    if at < 0:
        return q
    return cat_str(cat_str(head(q, at), stem_of(name(p))), s)


# ── `relative_to` ──────────────────────────────────────────────────────────

def relative_to(p, base) -> str:
    """`PurePosixPath(p).relative_to(base)`, or `""` if not under it.

    LEXICAL, and that is the word that matters: it compares components and
    resolves nothing, so `relative_to("a/./b", "a")` is `"b"` and
    `relative_to("a/b", "/a")` is `""` — a relative path and an absolute one
    are not comparable, which CPython also refuses. It is NOT
    `os.path.relpath`, which resolves against the working directory first and
    so answers a different question.
    """
    var a = as_posix(p)
    var b = as_posix(base)
    if b == ".":
        # A base that normalised to `.` has NO components — CPython's
        # `PurePosixPath("").parts` is `()` — so everything is under it and the
        # answer is the path itself. `relative_to("a", "")` is `"a"`, and a
        # version that compared components answers `""`, which is this module's
        # "not under" sentinel: the two failures look the same and mean
        # opposite things.
        if a == ".":
            return "."
        return a
    return _under(a, b)


def _under(a, b) -> str:
    """`a` with the leading `b` removed AS COMPONENTS, or `""`.

    `""` means "not under", and it is not an answer for two equal paths —
    which is why `relative_to` does not need a separate equality test:
    an equal pair answers `"."` here.
    """
    var i = strlen(b)
    if i > strlen(a):
        return ""
    if strncmp(a, b, i) != 0:
        return ""
    if strlen(a) == i:
        return "."
    if byte_or(a, i) != 47:
        return ""
    return tail(a, i + 1)


# ── `match` ────────────────────────────────────────────────────────────────

def n_components(q) -> int:
    """How many components the NORMALISED `q` has.

    `""` — 0 — for a path that is only a root or only `.` components, which is
    CPython's `PurePosixPath("/").parts == ()` and `PurePosixPath(".").parts
    == ()`. The `"."` case is written out because `as_posix` SPELLS an empty
    path `"."` and a one-character `"."` looks like a component to a walk that
    is counting separators. The root is not counted as one: `PurePosixPath("/a/b").parts` is
    `('/', 'a', 'b')`, so the root is a part, and this is the count MINUS that
    one — which is what the anchored rule below compares, and the difference
    cancels because both sides of that comparison carry a root or neither does.
    """
    if q == ".":
        return 0
    var n = 0
    var i = 0
    while i < strlen(q):
        while i < strlen(q) and byte_or(q, i) == 47:
            i = i + 1
        if i >= strlen(q):
            break
        n = n + 1
        while i < strlen(q) and byte_or(q, i) != 47:
            i = i + 1
    return n


def match(p, pat) -> int:
    """`PurePosixPath(p).match(pat)`: 1 or 0.

    MATCHED FROM THE RIGHT, and non-recursive: `match("a/b/c.py", "b/*.py")`
    is 1 because the last TWO components match and the pattern says nothing
    about `a`, while `match("a/b.py", "/*.py")` is 0 because a pattern starting
    with `/` is ANCHORED and must match the whole path. Those two rules are
    the whole of `PurePath.match`, and `fnmatch.fnmatch` has neither — the two
    are not interchangeable, which is why this is not `fnmatch` and does not
    import it.

    Inside one component the pattern language IS `fnmatch`'s: `*`, `?`,
    `[seq]`, `[!seq]`, with `*` not crossing a `/`.

    `**` IS `*` HERE, and that is a MEASUREMENT rather than an omission —
    CPython's documentation says `**` "matches any number of path segments",
    and for `match` that is not what it does. Measured over thirteen `**`
    patterns, it is indistinguishable from `*` in this right-aligned walk:

        match("a/b/c.py", "a/**")       False   (and "a/b" is True)
        match("a", "a/**")              False
        match("a/b/c/d", "a/**/d")      False   (and "a/b/c" is True)
        match("a/b/c.py", "**")         True
        match("a/b/c.py", "**/*.py")    True
        match("a/b/c.py", "**/**")      True

    Every one of those is what `*` gives in the same place, and the
    "any number of segments" reading is a statement about `full_match`, which
    is a 3.13 method this module does not have. So `**` is two `*`s in a
    component and needs no special case; the first version of this function
    gave it one, a backtracking walk over every split of the remaining path,
    and it answered `match("a/b/c.py", "a/**")` as True.
    """
    var a = as_posix(p)
    var b = as_posix(pat)
    if n_components(a) == 0 and n_components(b) > 0:
        # The path has NO components — `PurePosixPath("")` and
        # `PurePosixPath("/")` both have `parts == ()` — and the pattern has at
        # least one, so nothing can match. Without this, `as_posix("")` is
        # `"."` and `"."` looks like a component that `*` matches:
        # `match("", "*")` answered 1 where CPython answers 0. The pattern's
        # own count is in the test because `match("/", "/")` IS 1 — two
        # component-less paths match each other.
        return 0
    if strlen(pat) == 0:
        # CPython raises `ValueError("empty pattern")` and this path has no
        # exceptions, so the answer is 0 — "no pattern, no match" — which is
        # stated here because a caller that gets 0 has to be able to tell it
        # from a pattern that did not match. Tested on `pat` and NOT on `b`:
        # `as_posix("")` is `"."`, so a check on the normalised pattern never
        # fires and `match("", "")` answered 1.
        return 0
    if byte_or(b, 0) == 47:
        # ANCHORED, and two conditions rather than one. The roots must be the
        # SAME — `match("a", "/a")` is 0 and `match("a/b.py", "/*.py")` is 0
        # for exactly this reason — and the component COUNTS must be equal,
        # because an anchored pattern matches every component and may not leave
        # any over: `match("/a/b.py", "/*.py")` is 0 while
        # `match("/a/b.py", "a/*.py")` is 1, and the only difference is the
        # root. Comparing the two STRINGS' lengths, which is the obvious way,
        # gets the second one right and the first two wrong.
        if root_of(a) != root_of(b):
            return 0
        if n_components(a) != n_components(b):
            return 0
    return match_path(a, strlen(a), b, strlen(b))


def match_path(a, an, b, bn) -> int:
    """One component from each end, then the next pair inward.

    `an` and `bn` are END indices and the components are taken from the right,
    which is what makes the alignment right-aligned without the caller having
    to choose one. Each call consumes one pattern component, so the depth is
    the pattern's component count and not the path's.
    """
    while an > 0 and byte_or(a, an - 1) == 47:
        an = an - 1
    while bn > 0 and byte_or(b, bn - 1) == 47:
        bn = bn - 1
    if bn <= 0:
        return 1
    if an <= 0:
        return 0
    var bs = comp_start(b, bn)
    var asx = comp_start(a, an)
    if match_seg(a, asx, an - asx, b, bs, bn - bs) == 0:
        return 0
    return match_path(a, asx - 1, b, bs - 1)


def match_seg(a, ai, an, b, bi, bn) -> int:
    """One component against one: `fnmatch`, with no `/` inside either.

    A backtracking walk, and the only recursive function in this file. Each
    step consumes at least one character of the pattern, so the depth is the
    pattern COMPONENT's length — a property of the input rather than a
    constant somebody had to choose, which is why there is no depth guard here
    where `json.mojo`'s scanner has one.
    """
    if bn == 0:
        # The pattern is exhausted AND so must the input: a component match is
        # whole-component on both sides, and returning 1 here with input left
        # over is what made `match("a/b.py", "[!]]")` answer 1 where CPython
        # answers 0 — the set matched the `b` and the `.py` had nowhere to go.
        if an == 0:
            return 1
        return 0
    if an == 0:
        # Only a pattern of nothing but `*` can still match nothing.
        if byte_or(b, bi) == 42:
            return match_seg(a, ai, an, b, bi + 1, bn - 1)
        return 0
    var bc = byte_or(b, bi)
    if bc == 42:
        var k = 0
        while k <= an:
            if match_seg(a, ai + k, an - k, b, bi + 1, bn - 1) == 1:
                return 1
            k = k + 1
        return 0
    if bc == 63:
        return match_seg(a, ai + 1, an - 1, b, bi + 1, bn - 1)
    if bc == 91:
        return match_bracket(a, ai, an, b, bi, bn)
    if bc != byte_or(a, ai):
        return 0
    return match_seg(a, ai + 1, an - 1, b, bi + 1, bn - 1)


def match_bracket(a, ai, an, b, bi, bn) -> int:
    """A `[...]` set at `b[bi]` against the byte at `a[ai]`.

    `[!...]` and `[^...]` both negate, which is CPython's `fnmatch` spelling,
    and a `]` IMMEDIATELY after the `[` or the `!` is a literal — the two rules
    that make `[]]` and `[!]]` mean what a program means by them. An
    unterminated `[` is a literal `[`, again as in `fnmatch`.
    """
    # `j` and `end` are ABSOLUTE indices into `b` and `bn` is a LENGTH, and
    # keeping those two on the same scale is the whole of this function: the
    # first version compared an index against a length, which happened to work
    # while the bracket was the first thing in its component and broke the
    # moment it was not — `match("a/b.py", "b[.]py")` answered 0.
    var end = bi + bn
    var j = bi + 1
    var neg = 0
    if j < end and byte_or(b, j) == 33:
        neg = 1
        j = j + 1
    var c = byte_or(a, ai)
    var hit = 0
    if j < end and byte_or(b, j) == 93:
        if c == 93:
            hit = 1
        j = j + 1
    while j < end and byte_or(b, j) != 93:
        if j + 2 < end and byte_or(b, j + 1) == 45:
            if c >= byte_or(b, j) and c <= byte_or(b, j + 2):
                hit = 1
            j = j + 3
        else:
            if c == byte_or(b, j):
                hit = 1
            j = j + 1
    if j >= end and c == 91:
        hit = 1
    if neg == 1:
        hit = 1 - hit
    if hit == 0:
        return 0
    return match_seg(a, ai + 1, an - 1, b, j + 1, end - j - 1)


# ── the one whose answer never changes ─────────────────────────────────────

def is_reserved(p) -> int:
    """`PurePosixPath(p).is_reserved()`: always 0.

    It exists to catch `CON`, `NUL`, `PRN` and their kin, which are reserved on
    Windows and reserved nowhere on a POSIX target, and CPython answers False
    for every path here too. It is 0 rather than absent because a program that
    asks gets the right answer, and the cost is three words.
    """
    return 0
