"""Import resolution for the formal backends: source → dylib → link line.

The formal path compiles ONE file and, until this module, silently ignored
every `import`. That is worse than an error: an ignored import leaves the
calls it implies as BLs against symbols nothing defines, so the program builds
and then dies in dyld at launch. This turns the import into what it means — a
dependency — by resolving the module, compiling its WHOLE source into a dylib
that represents it, and handing the link step that dylib.

"Whole source" is the point, and it is deliberate. A module dylib is a
*representation of a source file*, not a cache of the call sites that happened
to need it: the function this program never mentions still has to be in there,
compiled and exported, because the next module that imports the same file will
link against exactly this artifact and expect it. Building only the referenced
functions would make the artifact depend on who asked for it — the same source
compiled twice, two different libraries, and a symbol that exists in one and
not the other depending on which program triggered the build. So: one module in
⇒ every public function it defines, exported per doc/ABI.md.

Everything is content-addressed (cas.formal_build_key), so a module is compiled
once per (source, compiler, dependency-closure) and shared by every program
that imports it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cas
import fire_compiler as F

from formal import model as _model
from formal.build import ImportBuildError  # noqa: E402  (cycle-free: build
# imports this module lazily, inside the function)

# Built module dylibs this process has already produced, keyed by resolved
# path, so a program importing the same module twice (or a cycle) reuses it.
_BUILT: dict = {}

# Parsed module sources, keyed by (absolute path, content digest). See
# `module_statements`: one parse per file per content, shared by every reader
# in this module.
_PARSED: dict = {}

# The root of this source tree — the directory holding fire_compiler.py. This
# repository is itself the source the formal path compiles, so it is a
# legitimate (and bounded) place to look for a module name.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Where this backend's OWN implementations of CPython's modules live: `os/`
# (with `os/path/` and `os/_syscalls.mojo`), `sys.mojo` and `struct.mojo`.
#
# They were at the REPOSITORY ROOT, which is where the first three landed, and
# that is a search root for FOUR INDEPENDENT resolvers, not just this one:
# `imports.py`'s `Resolver` (MOJO_PATH puts the repo root on every gimple
# build's path), `module_loader.py`, `myinterpreter.py`'s
# `_load_mojo_sibling_module` (it walks up from the importing file and then
# adds `sys.path`), and the gimple backend's `_module_candidate_paths` (whose
# last resort is this very directory). So a Mojo `os` at the root captured
# `import os` in `fire.py`, `module_loader.py` and `gimple_codegen.py`
# themselves — the compiler's own source — and the compiled path lowered
# `os.sep` (a `char *` constant) as if it were a module-level name with no
# storage, which gcc then rejected as `invalid operands to binary + (have
# 'char *' and 'void *')`. Measured in the integrator's gate, at
# `bootstrap-stage2-cc` and `selfhost`.
#
# Under `formal/` the directory is reachable ONLY from a resolver that
# deliberately adds it, and this is the one: `_search_roots` below, and
# nothing else in the tree lists it. `formal_sweep.py`'s default roots walk
# the repository, so the module sources are still swept — as
# `formal/hostmods/os/__init__.mojo`, which is a more honest name for what
# they are than a bare `os/` at the top level.
#
# A file INSIDE this directory is compiled by this backend like any other, and
# the relative imports its own modules use (`from ._syscalls import …`) resolve
# from the file's own directory, so the move changes no path inside them.
_HOSTMODS_ROOT = os.path.join(_REPO_ROOT, "formal", "hostmods")


# CPython's standard library, SPLIT BY WHAT IMPLEMENTING IT WOULD REQUIRE.
#
# These have no Mojo source in this tree and no symbol this formal model could
# bind, so a file importing one cannot be built here — that much is a statement
# about the TARGET, not a module-resolution failure. But "cannot be built here"
# and "could never be built here" are different claims, and the coverage report
# used to conflate them: `tools/formal_sweep.py`'s CLASS_HOST blurb says a host
# import is *"outside this backend's reach, and not fixable"*, which is FALSE of
# `os`, `sys`, `math`, `struct`, `time`, `json` and `re`. Those are modules
# whose capability is reachable — libSystem provides the underlying facility, or
# the work is pure computation. Saying "not fixable" about them is how the
# largest bucket in the report came to rest on a claim nobody had checked.
#
# The rule that separates the tiers, stated once: **does implementing it need an
# object a freestanding image that links libSystem and NOTHING ELSE does not
# have?** A second process, a thread, a socket, a dynamic loader for foreign
# code, an embedded CPython, a terminal — or a library outside libSystem. That
# is a property of the target and no amount of backend work changes it.
# Everything else is `HOST_MODELLED`: reachable in principle, not implemented
# today, and therefore a gap with an owner rather than a permanent fact.
#
# This is a judgement with a stated rule, not a proof. A module is placed by the
# rule and by nothing else — never because it happens to be unimplemented, and
# never because it is unimplemented *on this backend specifically*.
#
# `_is_host_module` consults the UNION, so this is a CLASSIFICATION change and
# not a behaviour change: every one of these refuses the build exactly as
# before, and the union is asserted to equal what the single list used to hold.
HOST_UNREACHABLE = frozenset((
    # `subprocess`, `threading`, `concurrent`, `concurrent.futures` and `ctypes`
    # were here until 2026-10-02 and are now in HOST_ADMITTED below, because each
    # has a `formal/hostmods/` model.  A name LEAVES this set by being WRITTEN,
    # for the reason the HOST_MODELLED comment states: an entry left behind is a
    # claim that is false once the module that answers it is in the tree, and this
    # one is worse than false -- it feeds `host_module_tier`, so the sweep's reach
    # line would go on reporting these as "needs a host process this image does
    # not have" for a file that now builds.  The capability is still missing; what
    # changed is that the module answers anyway, under a declared contract.
    #
    # A second process.
    # A thread, and a proved model of one.
    "asyncio",
    # A socket.
    "socket", "urllib", "http",
    # A dynamic loader for foreign code, or an embedded CPython.  `ctypes` moved
    # to HOST_ADMITTED with the rest; what is left here is the embedded CPython.
    "importlib", "importlib.util", "importlib.machinery",
    # The interpreter's own frames, allocation set, or shutdown path. There is
    # no interpreter here to ask, and on this path a value is one 64-bit word,
    # so there is nothing for `gc` to track and no bytecode for `dis` to
    # disassemble (the formal backends emit machine code, not bytecode).
    # `builtins` is here for the same reason and it is measured rather than
    # read off: the three files in this repository that want it
    # (`tools/codeindex.py`, `tools/wave2c_explicit_imports.py`,
    # `tools/wave2b_fix_deps.py`, ranked by `tools/formal_sweep_causes.py
    # --host`) all spell `set(dir(builtins))` — they ask the INTERPRETER to
    # enumerate its own namespace, which is the one question on this page with
    # no answer at all here.
    "traceback", "gc", "atexit", "signal", "warnings", "dis", "builtins",
    # Process-wide reporting machinery, which is a host object by construction.
    "logging", "unittest", "unittest.mock",
    # A terminal. `tempfile` WAS here too — under this heading, for the
    # `TMPDIR`-derived half of it rather than the terminal half — and left on
    # 2026-10-03, because both halves were measured away: the terminal one is
    # still true and is why `formal/hostmods/tempfile.mojo` asks for nothing
    # that needs one, and the `TMPDIR` one was false, since `os` has `getenv`,
    # `mkdir` and `os.path.isdir`. That module is the reason this list is worth
    # reading rather than trusting: every other entry under this heading is a
    # fact about the target, and the way to tell the two apart is to ask whether
    # `os` can already do the thing the entry names. `shutil`'s
    # `get_terminal_size` is the half that survived the same removal and is
    # absent in that module with the reason at its own definition.
    "getpass", "webbrowser",
    # A library outside libSystem, so linking it would contradict the premise
    # that a formal image links libSystem and nothing else. `zlib` and `gzip`
    # also have an honest route that does NOT link anything — DEFLATE is
    # arithmetic over bytes, so a `formal/hostmods/zlib.mojo` could compute it
    # the way `re.mojo` computes a match — and 15 files in the sweep's host
    # ranking are behind `zlib`. It is here rather than in HOST_MODELLED
    # because the tier means "a Mojo-side implementation could in principle
    # provide this, and has not yet", and for `zlib` the premise of this
    # heading is the thing to argue with first: the cheapest correct module is
    # one that implements inflate and deflate itself rather than one that links
    # libz, and that is a project rather than a patch.
    "zlib", "gzip", "locale",
    # An EMBEDDED CPython's installation, which is the reading of `sysconfig`
    # that has no other: `get_paths()` answers "where is the interpreter that
    # would run this program", and there is none. `fire.py` imports it and
    # never uses it (measured — the module is reached on its first line and no
    # `sysconfig.` appears anywhere in the file), so it is in this row for the
    # diagnostic it gets rather than for anything fixing it would reach.
    "sysconfig",
))

# The reachable half: libSystem provides the facility, or the module is pure
# computation over values the model already represents. NOT implemented today.
# Grouped by what it would need, because that is what "reachable" means here.
HOST_MODELLED = frozenset((
    # A libSystem/libc facility: getcwd, stat, clock_gettime, regcomp,
    # arc4random_buf, CommonCrypto for hashlib, the POSIX file calls.
    #
    # A module on this list is a CLAIM: CPython has it, this tree can
    # eventually compile it. The claim stops being true the moment a Mojo
    # source for it exists here, because `resolve_module_path`'s FIRST pass
    # finds that source before this set is ever consulted — an entry left
    # behind would refuse a file AFTER the module that answers it is sitting
    # in the tree, which is a false statement rather than a conservative one.
    # So a name LEAVES here by being WRITTEN, and each says in one line what
    # it is written in and what it still cannot do; the omissions are bug
    # docs, stated at the function that lacks the capability, not here.
    #
    #   `sys`  — `formal/hostmods/sys.mojo`, checked by `test_formal_sys.py`.
    #     What it cannot answer is written at the top of the file itself:
    #     `argv`, `path` and the stream objects are ONE missing capability (an
    #     argument vector with no place to put it, and streams), not nine
    #     missing names, so they are filed once, as a bug.
    #   `os`  — `formal/hostmods/os/__init__.mojo`,
    #     `formal/hostmods/os/path/__init__.mojo` (CPython's posixpath) and
    #     `formal/hostmods/os/_syscalls.mojo` (every libSystem call it makes,
    #     once), all three built and RUN by `test_formal_os.py`: 436 path
    #     answers against CPython's own, 75 filesystem operations against the
    #     real filesystem. `listdir` and `walk` need a run-time-length
    #     sequence, which a list on this path cannot be, and `environ` needs
    #     a `char **` walk; both are bug docs rather than approximations.
    #   `io`  — `formal/hostmods/io.mojo`, in the part of CPython's `io` that
    #     is not streams: `SEEK_SET`, `SEEK_CUR`, `SEEK_END` and
    #     `DEFAULT_BUFFER_SIZE`, each checked against CPython's own `io` by
    #     `test_formal_small_hosts.py`. The streams are absent because a
    #     stream is a descriptor, a cursor and a buffer and a value cannot
    #     cross a dylib boundary unless it is one 64-bit word — which
    #     `formal/hostmods/sys.mojo` already says about `sys.stdout`, and `io`
    #     is those streams one level up. It also closes the `io.open`-over-
    #     `os` idea the `module:small-hosts` doc proposed: `os/_syscalls.mojo`
    #     has `fs_open_ro`, `fs_lseek` and `fs_close` and NO read or write, so
    #     the missing half is a stream.
    #   `platform`  — `formal/hostmods/platform.mojo`, checked name by name
    #     against CPython's own `platform` by `test_formal_platform.py`: the
    #     five `uname(3)` fields (`system`, `node`, `release`, `version`,
    #     `machine`), `uname().processor`, both computable components of
    #     `mac_ver()` and `system_alias` in full including CPython's SunOS
    #     release arithmetic. It is the largest reachable host-import row in
    #     the sweep — thirty files, and all thirty ask for `machine()` — so it
    #     is the row whose disappearance is worth counting; the accounting is in
    #     `bugs/FORMAL_platform_reachable_row_measured.md`. What it cannot
    #     answer is written at the top of the file: `platform()` itself is one
    #     call away and blocked on `architecture()`, which needs `file(1)`, and
    #     `processor()`/`libc_ver()` are subprocesses and a readable file.
    #   `stat`  — `formal/hostmods/stat.mojo`, the MODE VOCABULARY and nothing
    #     else: every `S_I*` / `S_IF*` / `ST_*` constant, `S_IFMT`, `S_IMODE`,
    #     the seven `S_IS*` predicates this platform compiles, and `filemode`,
    #     each checked name by name against CPython's own `stat` by
    #     `test_formal_stat.py` over an EXHAUSTIVE mode corpus — every one of
    #     the 4096 permission combinations and every type CPython's `filemode`
    #     table has a row for. It is the only host module with no dependency on
    #     the C library and none on `os`, because CPython's `stat` is the
    #     VOCABULARY for reading `os.stat`'s answer and holds no syscall of its
    #     own; the syscall and its byte-wise field reader are
    #     `formal/hostmods/os/_syscalls.mojo`'s (`fs_stat_field64`,
    #     `fs_stat_mode`) and are deliberately NOT re-exported here, so there is
    #     one reader of `struct stat` in this tree. What it cannot answer is at
    #     the top of that file: `S_ISDOOR` / `S_ISPORT` / `S_ISWHT` are
    #     compiled out of CPython on this platform and answering "no" would be a
    #     plausible wrong answer about a whiteout, and Darwin's
    #     `ST_BIRTHTIME` / `ST_BLOCKS` / `ST_BLKSIZE` have no CPython name to
    #     be checked against.
    "errno", "select",
    #   `pathlib`  — `formal/hostmods/pathlib.mojo`, in the pure half only,
    #     checked read for read against CPython's own `PurePosixPath` by
    #     `test_formal_pathlib.py`: `as_posix`, `name`, `stem`, `suffix`,
    #     `parent`, the three pure rewritings, `relative_to`, `match` and
    #     `is_reserved`, over a corpus of awkward corners. It is the part
    #     pathlib has and `os.path` has no name for, and the names `os.path`
    #     already answers are NOT answered again there — see the module's own
    #     docstring, which names each one.
    #   `fnmatch`  — `formal/hostmods/fnmatch.mojo`, checked answer for answer
    #     against CPython's own `fnmatch` by `test_formal_fnmatch.py`: the
    #     bracket set, the range, the negation, the literal `]` first, the
    #     unterminated `[`, and the two spellings CPython has (`fnmatch` and
    #     `fnmatchcase`, one function on a POSIX target because `normcase` is
    #     the identity). It is worth one paragraph rather than one line because
    #     its matcher is not its own: `pathlib.mojo`'s `match_seg` calls
    #     `match_core` here with the flag that keeps `*` inside a component, so
    #     the tree has ONE bracket matcher instead of two. What it cannot answer
    #     is written at the top of the file: `filter`/`filterfalse` are
    #     sequences, `iglob` is a generator, and `translate` emits a regex
    #     dialect `re.mojo` does not compile.
    "glob", "secrets", "uuid",
    #   `ast`  — `formal/hostmods/ast.mojo`, the TOKENIZER and a lexical
    #     validator, not a tree: `parse`, `parse_reason`, `tokenize`,
    #     `tokenize_from`, `token_bound` and `token_name`, with token kinds,
    #     positions and counts compared against CPython's own `tokenize` by
    #     `test_ast_formal.py`. What it cannot do is build a tree, because a
    #     value on this path is one 64-bit word and a node is not one: the
    #     subset, the 38 pinned ways `parse` differs from CPython's verdict and the
    #     three stream divergences are in `formal/hostmods/ast.mojo`'s own
    #     docstring, under "WHAT parse(src) DOES NOT MEAN".
    #   `struct`  — `formal/hostmods/struct.mojo`, in the subset the formal
    #     backends can lower, compared BYTE FOR BYTE against CPython's own
    #     answers by `test_struct_formal.py`. The four measured limits it is
    #     written around are in that file's own docstring. It also matters for
    #     the work accounting: an entry here is the claim
    #     `formal_sweep.py` sizes its "not answerable" column from, and it
    #     reported seven files as blocked on a module that now exists.
    #   `time`  — `formal/hostmods/time.mojo`, checked by `test_formal_time.py`
    #     against CPython's own clocks: every value it produces is a clock
    #     READING, so the test asserts relations (the image's wall clock within
    #     2 s of this process's, monotonic never decreasing, `sleep_ns` at
    #     least as long as asked) rather than a table. A float is not a value
    #     on this path — `formal/arm64_codegen.py` truncates a `FloatLiteral`
    #     to an integer and there is no float arithmetic — so the fractional
    #     `time.time()` is the IEEE-754 BIT PATTERN of one, verified bit-exact
    #     against exact rational arithmetic over 534 inputs. What it cannot
    #     answer is written at the top of the file: `localtime`, `gmtime`,
    #     `mktime`, `strftime` and `get_clock_info` all return a `struct tm`
    #     or a named tuple, and a struct is a frame blob, so they are absent
    #     rather than approximated. Filed as
    #     `bugs/FORMAL_time_struct_shaped_answers.md`.
    #   `hashlib` — `formal/hostmods/hashlib.mojo`, checked BYTE FOR BYTE
    #     against CPython's own digests by `test_formal_hashlib.py`: six
    #     digests from CommonCrypto (which libSystem provides) and BLAKE2b
    #     computed from RFC 7693 because libSystem has no BLAKE2 and
    #     `py314_cache.py` asks for `blake2b(digest_size=20)`. 1,182 digests
    #     compared, none from a table. CPython's factory API is not
    #     expressible — a hash object is 8 to 64 bytes of state that cannot
    #     cross a dylib boundary — so each digest is one function, and the
    #     seven absent names (SHA-3, SHAKE, blake2s) are named, with the
    #     measurements, the rule that decided them and what each would cost, in
    #     the module's own "WHAT IS NOT HERE, AND WHY".
    #   `re`  — `formal/hostmods/re.mojo`, a backtracking regex engine in the
    #     subset `regex_compile.py` says it exists for plus `\b`, `^`/`$`
    #     under MULTILINE, DOTALL and `(?P<name>…)` — the four things the
    #     thirteen sweep files and `fire_compiler.py` actually spell — checked
    #     span for span against CPython's own `re` by `test_re_formal.py`
    #     (112 patterns, every integer compared). It matters for the same
    #     reason `struct` does: thirteen files of the arm64 sweep stopped on
    #     this one import. What it cannot answer is written at the top of the
    #     file, and the three absences are refusals rather than wrong answers
    #     — lookaround and backreferences return `STATUS_UNSUPPORTED`, a
    #     pattern bigger than the module compiles returns `STATUS_LIMIT`, and
    #     the compiled-pattern and match OBJECTS are functions taking a
    #     caller-allocated span list, because an object is more than one
    #     64-bit word and a compiled pattern has nowhere to live between
    #     calls.
    #   `json`  — `formal/hostmods/json.mojo`, checked case for case against
    #     CPython's own `json` by `test_formal_json.py`: RFC 8259's accept and
    #     reject over ~180 documents, the kind of every one of them, the
    #     scanner's and the encoder's escape tables, and `dumps_str` over
    #     every code point in nineteen ranges — the surrogate-pair arithmetic
    #     is the part most likely to be wrong at exactly one point. Its
    #     `loads`/`load`/`dump`/`dumps` of a CONTAINER are absent, because a
    #     dict is a frame blob and cannot cross a dylib boundary; what is here
    #     is the scanner, which is the half of the module whose answers are
    #     one word each. Its docstring also records WHY the byte-value read
    #     that a 2026-09-29 attempt at this module measured as UNAVAILABLE is
    #     in fact available — it is a spelling, `var q: Pointer[UInt8] = s + i`
    #     before `q.value()`, and not a capability the target lacks — and
    #     `test_formal_json.py`'s `primitive` group is the assertion that says
    #     so over 351 byte values, each against the byte CPython's `ord` names.
    #
    #   `typing`  — `formal/hostmods/typing.mojo`, ONE function
    #     (`TYPE_CHECKING`, checked against CPython's own), and the count is
    #     the finding: the formal backends ERASE ANNOTATIONS, so a
    #     `from typing import Optional` resolves as soon as the module EXISTS
    #     and `Optional` need not be in its export table, because nothing ever
    #     reads the name. `formal/elf.py` and `type_system.py` put all seven of
    #     their imported names in annotations or in a default, which is why the
    #     module is one function long. `test_formal_small_hosts.py` pins that
    #     measurement — the annotation shapes build and run, and a name used as
    #     a VALUE is still refused, so the erasure is not a promise the module
    #     makes.
    #   `enum`  — `formal/hostmods/enum.mojo`, checked accessor for accessor
    #     against CPython's own `enum` by `test_formal_core_hostmods.py`, on both
    #     backends. The module is ONE function (`Enum`) and the interesting part
    #     is why: an enum member on this path is a CLASS-LEVEL CONSTANT and the
    #     base is erased, so `class Reg(Enum): RAX = 0` reads `Reg.RAX` as `0`
    #     with no `enum.mojo` in the tree at all. What the module buys is that
    #     the import RESOLVES — `type_system.py` and `formal/x86_64.py` each
    #     `from enum import Enum` on their first line, and without it both are
    #     refused for a statement that is not wrong. What is NOT the module's is
    #     `.value` and `.name`: those are attribute reads on a class constant and
    #     are answered in `formal/model.py` (`enum_member_accessor`) and
    #     `formal/build.py` (`_enum_member_sites`), because `.value` on a member
    #     was silently reading 0 where CPython reads the member's value —
    #     `formal/x86_64.py` does its register arithmetic through it.
    #   `contextlib`  — `formal/hostmods/contextlib.mojo`, ONE function
    #     (`nullcontext`), checked against CPython's own for both arities by
    #     `test_formal_core_hostmods.py` on both backends. It is the one name in
    #     CPython's `contextlib` whose meaning is fully carried by `with EXPR as
    #     TARGET` on this path, which binds the target to the expression. The
    #     neighbours are absent for the reason the module's docstring measures:
    #     `suppress` needs an exception, `redirect_stdout` needs a stream,
    #     `contextmanager` is a decorator (silently DROPPED, so it would build
    #     and do nothing) and `closing` would bind correctly and then silently
    #     never close anything — the one shape a mirror of CPython must not ship.
    #   `math`  — `formal/hostmods/math.mojo`, the SEVEN functions in CPython's
    #     `math` that answer an INTEGER (`gcd` / `lcm` / `isqrt` / `factorial`
    #     / `comb` / `perm` / `prod`), plus the IEEE-754 bit patterns of the
    #     five float constants, checked name by name against CPython's own
    #     `math` by `test_formal_math.py`. Everything else in CPython's `math`
    #     takes and answers a `float`, and that is not a missing libc call:
    #     libSystem has every one of them, and a `double` does not travel in an
    #     integer register on either ABI (arm64 `d0`, SysV x86-64 `XMM0`), so
    #     calling `sqrt(x)` here would hand the C library a garbage bit pattern
    #     and return a plausible wrong answer. `floor`/`ceil`/`trunc`/`round`/
    #     `fabs` are absent for that reason and not because their integer case
    #     is hard: for an integral argument each of them answers the argument,
    #     and a `floor` that returns its argument is `copy.copy`. What the
    #     module cannot answer is at the top of that file: a binomial
    #     coefficient or a factorial above 64 bits is -1 rather than a wrapped
    #     number, which is a status because there are no exceptions here
    #     (FORMAL.md phase 7).
    # Pure computation over representable values: string and text handling,
    # numeric containers, pattern matching, data structures.
    "random", "decimal", "fractions",
    "numbers", "array", "operator", "functools", "itertools",
    #   `collections`  — NO `formal/hostmods/` module, and the entry says why in
    #     the form a reader acts on: `HOST_MODULE_ADVICE` below is what the
    #     REFUSAL prints, which is where a person moving one of the five files
    #     that stop here will actually be. CPython's `collections` is one
    #     module-level function and eight classes, and the measurement is that
    #     neither half is a module.
    #
    #     `namedtuple` is a TYPE FACTORY, and a type is not a value on this
    #     path: there is no word that denotes one, so a class it builds cannot
    #     be returned from a module function or bound to a module-level name.
    #     The want behind the five call sites is not that though — measured, five
    #     of the six uses spell a compile-time-KNOWN record, which this target
    #     can express, as a `struct`. The capability and the measurement are
    #     `bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md`,
    #     which also owns `copy.deepcopy` because the two are one missing thing.
    #
    #     The eight classes are containers, and the `os.listdir` BLOB route
    #     serves exactly one of their operations and no more: a caller CAN
    #     subscript-assign into a blob a hostmod returned (measured — a
    #     `malloc`'d `Int64` array, `counts[2] = 5`, `counts[2]` answers 5), so
    #     `counts[opcode] += 1` works. It is not `Counter`, for three measured
    #     reasons: word 0 of a blob is its LENGTH, so a key of 0 reads the
    #     count instead of counting; a `Counter` inserts on a miss with a
    #     default while a blob has no dispatch, so the caller must pre-size and
    #     pre-test and the source spells neither; and `most_common`/`items`/
    #     `keys`/iteration/`+=`/`|` are method calls and operators on a value,
    #     which needs a type this image can see. Shipping the blob under the
    #     name `Counter` is the approximation
    #     `bugs/FORMAL_hashlib_sha3_and_blake2s_absent.md` declined to ship.
    "collections",
    "heapq", "bisect", "textwrap", "csv", "difflib", "base64",
    "codecs", "copy", "abc", "types", "queue",
    "weakref", "pprint", "reprlib", "pickle",
    #   `shlex`  — a state machine over a string, the same shape as `re` and
    #     `fnmatch`, which are written. `split`, `quote` and `join` are pure
    #     computation over bytes a value already is; the streaming `shlex.shlex`
    #     reader is a GENERATOR over `readline`, which is the `fnmatch.iglob`
    #     shape, so it is not in reach by the same argument. It is here because
    #     it is a standard-library module, and a name in NEITHER tier made
    #     `unresolvable_import_error` say "not a stdlib or sibling module" —
    #     a false statement about the target, and the one diagnostic in this
    #     family that misidentifies what kind of thing the name is.
    #
    #     Four more names were in NEITHER tier on 2026-10-03 for the same
    #     reason and are placed here by the RULE above rather than by reading:
    #     none of the four needs a second process, a thread, a socket, a dynamic
    #     loader, an embedded CPython, a terminal or a library outside
    #     libSystem, so none of the four is a permanent fact about the target.
    #     The ranking that found them is `tools/formal_sweep_causes.py --host`,
    #     which is what turned "UNTIERED" from a label into a list of six
    #     modules and ten files.
    #   `html`  — `escape`/`unescape` are five character replacements over a
    #     string: the `shlex` shape, and `os/_syscalls.mojo`'s `str_replace_all`
    #     is the primitive. One file wants it (`tools/md2html.py`, `html.escape`
    #     x1 measured), so the row is one file — which is the honest number and
    #     not a reason to place it anywhere else.
    #   `datetime`  — a CLOCK plus calendar arithmetic, and both halves are
    #     reachable: `formal/hostmods/time.mojo` has every clock `datetime` can
    #     read, and the arithmetic is integer work. What is NOT reachable is its
    #     ANSWER: a `datetime` object is a record of six fields and
    #     `strftime` is a formatted record, which is the same limit that keeps
    #     `time.localtime` out of that module
    #     (`bugs/FORMAL_time_struct_shaped_answers.md`). The two files that want
    #     it (`run_stdlib_tests.py`, `scripts/bootstrap_full_test.py`) spell
    #     `from datetime import datetime` and `datetime.now()` — the one call
    #     whose answer is that object.
    #   `resource`  — `getrusage(2)` is libSystem, so the CALL is reachable and
    #     the two `RUSAGE_*` constants are arithmetic; the answer is
    #     `struct rusage`, a fixed layout read one byte at a time, which is
    #     `formal/hostmods/os/_syscalls.mojo`'s `fs_stat_fill` exercise rather
    #     than a new capability. Both files that want it
    #     (`tools/mem_slope.py`, `test_selfhost_memory.py`) spell exactly
    #     `resource.getrusage(resource.RUSAGE_CHILDREN)`.
    #   `posixpath`  — **THE MODEL IS ALREADY WRITTEN AND THIS ENTRY IS A
    #     SPELLING, not a capability.** `formal/hostmods/os/path/__init__.mojo`
    #     IS CPython's `posixpath` (its own header says so) and answers
    #     `abspath`, `basename`, `commonprefix`, `dirname`, `isabs`, `join`,
    #     `normpath`, `realpath` and the rest, compared against CPython's own by
    #     `test_formal_os.py`. What a file that writes `import posixpath` gets
    #     instead is a module-RESOLUTION failure, because the resolver looks
    #     for a source NAMED `posixpath`. One file wants it that way
    #     (`test_formal_os.py`, measured — eight distinct `posixpath.` names), and
    #     the fix is a `formal/hostmods/posixpath.mojo` that re-exports
    #     `os.path`, which is what `os/__init__.mojo` already does for its own
    #     five names. It is not written: `test_formal_os.py` spells `os.path`
    #     everywhere else, so the one file is not evidence that CPython's
    #     spelling is wanted.
    "shlex", "html", "datetime", "resource", "posixpath",
    #   `shutil`  — `formal/hostmods/shutil.mojo`, checked against CPython's own
    #     `shutil` on a real filesystem by `test_formal_shutil.py`: `copyfile`
    #     over a source larger than its own copy buffer, `copy`/`copy2`'s
    #     one observable difference (the mode and not the time, and both),
    #     `copymode`, `copystat`, `move`, `rmtree`, `copytree` and `which` over
    #     a `PATH` corpus chosen for its branches. It was in `HOST_UNREACHABLE`,
    #     not here, so its removal is a REVERSAL of a permanent-fact claim and
    #     the reason is worth stating: that claim said "a writable filesystem
    #     this target does not get", and `formal/hostmods/os/__init__.mojo` has
    #     had `mkdir`, `makedirs`, `remove`, `rmdir`, `rename`, `replace` and
    #     `chmod` for a while — `test_formal_os.py` runs 75 filesystem
    #     operations against the real filesystem — so the filesystem half was
    #     false and only the TERMINAL half is not. What it adds to make the copy
    #     possible is `fopen`/`fwrite`/`fread`/`fclose` and `utimes` in
    #     `formal/hostmods/os/_syscalls.mojo`, because this path lowers `open`
    #     itself and refuses the C library's three-argument spelling of it.
    #     What it cannot answer is at the top of that file: `disk_usage` is a
    #     three-tuple (`bugs/FORMAL_time_struct_shaped_answers.md`),
    #     `get_terminal_size` is the terminal that IS unavailable, `move` has no
    #     cross-device fallback because `errno` cannot be bound
    #     (`__error` has a leading underscore), and the archives are a library
    #     with a struct layout nobody in the sweep asks for.
    #   `tempfile`  — `formal/hostmods/tempfile.mojo`, checked against
    #     CPython's own `tempfile` by `test_formal_tempfile.py`: `gettempdir`
    #     over CPython's candidate list, `gettempprefix`, `TMP_MAX`, and
    #     `mkdtemp`'s real directory, mode 448, eight-character name over
    #     CPython's own alphabet, and its retry-on-collision loop. It was in
    #     `HOST_UNREACHABLE` under "a terminal", and that claim was half false:
    #     a temporary directory is a directory, and `os` had `getenv`,
    #     `getcwd`, `mkdir` and `os.path.isdir` all along. It is the LARGEST
    #     host-import row in the sweep — 111 files, 109 of which name something
    #     the module publishes, ranked by
    #     `tools/formal_sweep_causes.py --host` — and what it moves is the
    #     SUBJECT of each file's refusal rather than its verdict: every call
    #     site in this corpus spells `mkdtemp(prefix=…)`, and a call across a
    #     dylib boundary cannot fill a default
    #     (`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`), so
    #     what those 51 files get is a refusal naming the argument they did not
    #     pass. What is absent is at the top of that file and it is 64 files'
    #     worth: `TemporaryDirectory`'s contract is the removal on the way OUT
    #     of a `with`, and `formal/hostmods/contextlib.mojo` measured that
    #     there is no `__exit__` to hook —
    #     `bugs/FORMAL_tempfile_context_manager_needs_a_way_out_of_a_with.md`.
    #   `argparse`  — `formal/hostmods/argparse.mojo`, in the subset the formal
    #     backends can lower, checked case for case against CPython's own
    #     `argparse` by `test_formal_argparse.py`: the same values, the same
    #     usage lines, the same error wording and the same exit statuses, on
    #     sixty-three generated programs whose declarations and command lines
    #     are the same table. What it cannot do is written in that file's own
    #     docstring — `type=float` is REFUSED because a value on this path is
    #     one 64-bit integer word, `sys.argv` has no source here at all so the
    #     caller supplies the vector, and there is no `ArgumentParser` object
    #     to accumulate into because a module has no state.
    # A SUBSET is reachable, and the subset is the point. `inspect` reads
    # attributes off live values, which this path has (the gimple runtime
    # carries a type tag and `mojo_obj_getattr`); what it cannot do is walk a
    # live interpreter's frames, because there is no interpreter. Flagged as
    # considered rather than missed.
    "inspect",
))

# The THIRD tier, and it exists because the other two could not say what is now
# true of five modules.
#
# `HOST_MODELLED` says "a Mojo-side implementation could in principle provide
# this, and has not yet" -- a gap with an owner.  `HOST_UNREACHABLE` says "this
# needs an object a freestanding image does not have" -- a fact about the target,
# permanent.  Both are FALSE of `subprocess` since its `formal/hostmods/` model
# landed: the module is written, so it is not a gap, and the second process is
# still missing, so it is not modelled either.  What it is, and what neither tier
# had a word for, is a module that ANSWERS under a DECLARED CONTRACT -- its API
# shape is computed and checked against CPython, and its host-dependent answers are
# each a named claim of trust, emitted into the generated Lean as a `sorry` that
# `formal/lean.py`'s census counts and printed by `fire.py` as a `trust:` line.
#
# So the tier is not a bookkeeping convenience.  A reader asking "can a person
# write `subprocess` for this backend?" used to get "no", which sends them away
# from a file that now builds; and a reader asking "what does this build trust?"
# got no answer at all, because there was no category to ask in.
#
# Membership rule: a name is here IFF it has a `formal/hostmods/` source, exactly
# as `HOST_MODELLED`'s rule is "a name LEAVES here by being WRITTEN".  It is the
# same rule with the opposite arrow, and `test_formal_admitted.py` asserts the
# partition -- both that every admitted name has a model and that every hostmod
# declaring a contract is in this tier -- so a module cannot be written and
# forgotten, which is the failure mode a hand-maintained tier always has.
HOST_ADMITTED = frozenset((
    # A second process: `run`, `call`, `check_call`, `check_output`, `getoutput`,
    # `getstatusoutput`, `Popen.wait` -- seven contracts, and everything decidable
    # about the arguments is decided rather than admitted.
    "subprocess",
    # A dynamic loader for foreign code.  The type table and the buffer helpers
    # are pure; `CDLL` and a call through the handle are the two contracts.
    "ctypes",
    # A thread.  `Future`'s five states and the lock's bit are arithmetic; the
    # pool and the thread are the contracts.
    "concurrent", "concurrent.futures", "threading",
    # `fcntl` WAS here — eleven constants and one admitted `flock` — and left on
    # 2026-10-02, because it no longer needs an admission:
    # `formal/hostmods/fcntl.mojo` is the real `flock(2)` over the real
    # filesystem, measured (a take/retake/release sequence, and a SECOND
    # descriptor of the same file refused, because a `flock` is per open file
    # description) by `test_formal_fcntl.py` on both backends. An admitted
    # contract is for a host fact this tree cannot answer; a lock it can take
    # and release is not one. See the module's own docstring, which also
    # records that **macOS's `flock` and `F_SETLK` share a lock space**, the
    # opposite of Linux.
))

# A name in HOST_ADMITTED whose `formal/hostmods/` source has gone, and a hostmod
# that declares a contract without its module being in the tier.  Both are
# reported rather than corrected: the first would be a claim this table cannot
# keep true by itself, and the second would be a proof resting on a contract the
# tier does not admit to.  `test_formal_admitted.py` asserts this is empty.
def _admitted_tier_conflicts() -> list:
    import os
    root = _HOSTMODS_ROOT
    if not os.path.isdir(root):
        return ["formal/hostmods/ does not exist"]
    bad = []
    have = set()
    for dirpath, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(files):
            if not name.endswith(".mojo"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            parts = rel.split(os.sep)
            if parts[-1] == "__init__.mojo":
                parts = parts[:-1]
            else:
                parts[-1] = parts[-1][:-len(".mojo")]
            have.add(".".join(parts))
    for n in sorted(HOST_ADMITTED):
        if n not in have:
            bad.append(f"{n} is in HOST_ADMITTED but has no formal/hostmods source")
    from formal import admitted as _admitted
    for c in _admitted.all_contracts():
        if c.module.split(".")[0] not in HOST_ADMITTED:
            bad.append(f"{c.module} declares an admitted contract but is not in "
                       f"HOST_ADMITTED")
    return bad


# Everything the build treats as a host module. The union, deliberately: the
# predicate the BUILD consults must not change behaviour, and this is the one
# place that says so.
#
# `__future__` is deliberately NOT in either tier. It is not a host module but a
# compiler directive that binds nothing, and it is excluded as INERT_MODULES
# below — a different and more accurate reason than "the host provides it", and
# the reason that matters is the sweep's: a file whose FIRST problem was
# `from __future__ import annotations` was reported as importing a module that
# cannot be built, which buried the `import os` that was what actually stopped
# it. That was the reason `asyncio`, `ctypes` and `concurrent` were added here in
# the first place: the coverage report was working around their absence, telling
# files they imported "not a stdlib or sibling module", which is a statement
# about module RESOLUTION and is simply false of a CPython standard-library
# module with no Mojo source.
# `fcntl` WAS IN NEITHER TIER, which is why its note is here and not in one of
# them: the sweep classified `import fcntl` as `not-answerable/host-import`
# because no `fcntl.mojo` existed for the resolver to find, not because a set
# said so — and `_is_host_module` returns False for it, so the refusal a caller
# got was "not a stdlib or sibling module, and no such file exists", the same
# message any unresolvable import gets. `formal/hostmods/fcntl.mojo` is
# `flock(2)` and the whole of CPython's integer surface — 30 constants, each
# read out of CPython's own `fcntl` by `test_formal_fcntl.py`, and the lock
# itself over a take/retake/release sequence including the case a POSIX
# record-lock implementation gets wrong (a SECOND descriptor of the same file
# is refused, because a `flock` is per open file description). Worth saying
# plainly: **it moves ZERO files to PASS**, since all three files that want
# `fcntl` also want `subprocess` and move to that instead — the same accounting
# `bugs/FORMAL_platform_reachable_row_measured.md` §2 records for `platform`.
# What is absent is at the top of that file, and one absence is a SPELLING
# rather than a fact about the target: the third argument of `fcntl(2)` does not
# arrive, so `getfd`/`setfd`/`getfl`/`setfl` would be a `setfd` that reports
# success and changes nothing —
# `bugs/FORMAL_a_variadic_call_drops_its_third_argument.md`. A second measured
# fact worth keeping: **macOS's `flock` and `F_SETLK` SHARE a lock space**, the
# opposite of Linux, so a reader who assumes Linux gets this backwards.

HOST_MODULES = HOST_UNREACHABLE | HOST_MODELLED
HOST_MODULES = HOST_UNREACHABLE | HOST_MODELLED | HOST_ADMITTED


# A module the formal FRONT END implements at COMPILE TIME, so the import is
# legal and nothing goes on the link line.
#
# This is a third answer, and neither of the two above is it. A HOST module is
# CPython's, and the build refuses it because there is no source to compile. A
# WRITTEN module has a `formal/hostmods/*.mojo` and is compiled into a dylib the
# image links. A FRONT-END-PROVIDED module is a shape over the SOURCE LANGUAGE
# — a decorator transform — and it is consumed by the front end while the
# statement list is still AST, so there is no symbol for a dylib to export and
# no `BL` for the codegen to emit.
#
# `dataclasses` is the first and only member. The measurement that put it here
# rather than in `formal/hostmods/` is in `formal/dataclass_transform.py`'s
# docstring, and it is the reason a Mojo module would have been wrong: a
# decorator applied to a CLASS is dropped by both backends before the front end
# looks at it, so a `def dataclass(cls)` in a Mojo module would be a symbol
# nothing calls, and the transform would silently do nothing — which is the
# outcome this backend exists to prevent, because `@dataclass` changes what a
# class MEANS and a dropped decorator is a program that runs and prints numbers
# the source never wrote.
#
# It is separate from `INERT_MODULES` below, and the difference is load-bearing
# rather than tidiness. `__future__` binds NOTHING and emits nothing, so there
# is no name in the file for anything to answer about. `dataclasses` binds
# NAMES the program uses — `dataclass`, `field`, `is_dataclass` — and every one
# of them is answered by the front end: the decorator by
# `dataclass_transform.dataclass_classes`, `field(default=…)` by
# `lower_field_defaults`, and the runtime reflection names by
# `check_reflection_calls`, which refuses each of them BY NAME with the reason
# the capability is missing. So a name from this module is never silently
# dropped — it is either lowered or refused, and the file says which.
FRONTEND_PROVIDED_MODULES = frozenset(("dataclasses",))


def is_frontend_provided(name: str) -> bool:
    """True when the FRONT END implements this module at compile time.

    The accessor the resolver asks before it looks for a file, and the reason
    `dataclasses` resolves: pass 1 of `resolve_module_path` searches for Mojo
    source (there is none, and there must not be — see
    `dataclass_transform.py`), and pass 2 refuses a host module. This is the
    answer in between: the import is satisfied by the front end, so
    `resolve_module_path` returns None — the same `None` a host module returns,
    meaning "nothing to compile" — and `_resolve_imports` skips it because
    `imported_modules` does not list it at all.

    Dotted, and on the FIRST component: `dataclasses.something` is the same
    module, exactly as `_is_host_module` treats it. A member access into it is
    refused by `dataclass_transform.check_reflection_calls` when the member is
    one of the reflection names, and by `check_module_symbols` when it is not —
    so an unknown member of a front-end-provided module is an unresolved name
    in the file that uses it, which names the file."""
    if not name:
        return False
    return name in FRONTEND_PROVIDED_MODULES \
        or name.split(".")[0] in FRONTEND_PROVIDED_MODULES


def host_module_tier(name: str) -> str:
    """`'modelled'`, `'admitted'`, `'unreachable'`, or `''` for no such name.

    The accessor that makes the split usable. A coverage report can then say
    "this file is out of reach because it needs a second process" — a fact
    about the target, permanent — separately from "this file is out of reach
    because `os.path.join` has not been built yet", which is a gap with an
    owner. Before this existed both were one bucket, and the bucket's own
    description asserted the stronger of the two claims about all of them.

    `'admitted'` is the third answer, for a module that has a
    `formal/hostmods/` source AND declares `@admitted` contracts for the
    operations whose answer is an external fact -- see `HOST_ADMITTED`.  It is
    tested after `unreachable` and before `modelled` because a name in two tiers
    is a bug the partition check reports, and the order only decides what such a
    bug looks like.

    `unreachable` is tested first, so a name in both tiers would resolve to the
    permanent answer; the partition is asserted to be disjoint by the test
    suite, and `_host_tier_conflicts` reports any overlap on demand, with
    `_admitted_tier_conflicts` doing the same for the admitted half plus its
    "has a source" rule.
    """
    if not name:
        return ""
    top = name.split(".")[0]
    if top in HOST_UNREACHABLE or name in HOST_UNREACHABLE:
        return "unreachable"
    if top in HOST_ADMITTED or name in HOST_ADMITTED:
        return "admitted"
    if top in HOST_MODELLED or name in HOST_MODELLED:
        return "modelled"
    return ""


def _host_tier_conflicts() -> list:
    """Names in both tiers, and (for auditing a future edit) names in neither.

    Empty is correct. This exists so a name added to one tier and forgotten in
    the other is a visible failure rather than a silent change to a verdict
    nobody reads a diff for. The suite asserts on it.
    """
    return sorted(HOST_UNREACHABLE & HOST_MODELLED)



def _is_host_module(name: str) -> bool:
    """Whether this name is a HOST MODULE this path refuses for want of source.

    NOT "is this a name in CPython's standard library" — that is
    `is_cpython_stdlib`, and the two are different questions with different
    consumers. This one is `resolve_module_path`'s pass 2 and the tier tables'
    own membership test, so it answers "is this one of the names we have
    CLASSIFIED", and a classified name includes every module with a
    `formal/hostmods/` source, which is why `math`, `stat`, `shutil`, `fcntl`
    and `platform` all answer False here and are pinned False by their own
    suites: they are built here, so nothing refuses them.
    """
    return name in HOST_MODULES or name.split(".")[0] in HOST_MODULES


def is_cpython_stdlib(name: str) -> bool:
    """Whether `name` names a module of the HOST's standard library.

    **CPython's own list is the authority**, `sys.stdlib_module_names` (3.10+),
    with the hand-maintained tiers as a second opinion rather than the first.
    The tiers are a CLAIM about the target — "does implementing this need an
    object a freestanding image that links libSystem and nothing else does not
    have" — and a claim is the wrong thing to answer "is `binascii` part of the
    standard library". That question has an oracle, and using a hand-kept list
    for it made this build say, of a module CPython ships:

        build: a.mojo imports 'binascii', which is not a stdlib or sibling
        module, and no such file exists

    which is false about the target in a message nobody wrote a rule for, and
    which sent 36 sweep rows to be filed as unresolved imports rather than as
    the host-import rows they are (measured, and recorded in
    `tools/formal_sweep.py`'s own `_is_cpython_stdlib`, which grew a second
    authority to compensate — two readers of one fact, which is how they come to
    disagree; this function is the one, and that copy now calls it).

    Matched on the TOP component, like `_is_host_module` and `host_module_tier`,
    so `os.path` and `os` answer alike. The interpreter's table is read through
    `getattr` and a missing one answers False, which is the direction that keeps
    a Python older than 3.10 behaving as it did rather than raising.
    """
    if not name:
        return False
    top = name.split(".")[0]
    if name in HOST_MODULES or top in HOST_MODULES:
        return True
    names = getattr(sys, "stdlib_module_names", None)
    return bool(names) and top in names


# Modules whose import is a DECLARATION to the reader rather than a
# dependency, so there is nothing for the link step to provide.
#
# `from __future__ import annotations` is the whole of it. `__future__` is not
# a library: importing a name from it is a compiler directive (`annotations`
# means "store string annotations"), it binds no value the program can use, and
# it produces no code. Demanding a source file for it is the resolver asking a
# file to exist that was never meant to, and it buries the real reason a file
# cannot be built under a name nobody is looking for: it was the FIRST thing
# wrong with 30+ real files in this repo, reported instead of the `import os`
# that is what actually stops them.
#
# This is the general rule stated once: an import that cannot change what the
# program computes is not a dependency. The rest of that family needs no list
# because it is already excluded structurally — a `TYPE_CHECKING` block, an
# `if False:`/`if sys.version_info >= ...` arm and a `try: import x except
# ImportError:` are all NESTED inside an If/Try, and `imported_modules` reads
# only the module's top level. That is load-bearing, not incidental: descending
# into a body would make every one of those names a hard dependency, so
# `test_guarded_imports_stay_inert` pins it.
INERT_MODULES = frozenset(("__future__",))


def _is_inert_module(name: str) -> bool:
    return name in INERT_MODULES


def _manifest_path(dylib_path: str) -> str:
    from formal.build import dylib_manifest_path
    return dylib_manifest_path(dylib_path)


def admitted_contracts(source_path: str) -> list:
    """Every ADMITTED CONTRACT this file's build reaches, transitively.

    A `formal/admitted.py` `Contract` per `@admitted(...)` in any module of the
    file's import CLOSURE — the same closure `import_closure_digest` walks, with
    the same `imported_modules` / `resolve_module_path` pair and the same
    `relative_to` / `project_root`, so the two cannot disagree about what this
    file builds against.

    TRANSITIVE is the load-bearing word and it is why this is not a lookup of the
    entry file's own imports.  `formal/build.py`'s `_resolve_imports` compiles
    every module in the closure into a dylib and links it, so a file that never
    names `subprocess` still links a library whose `run` is an admitted
    contract; a per-file `trust:` line that only looked at the entry file would
    under-report for exactly the files with the deepest closures, which is where
    the trust is hardest to see.

    The whole MODULE's contracts are reported for a module that is reached, not
    only the ones the calling file calls.  That is a deliberate over-report and
    the reason for it is that the narrower answer needs a call-graph walk across
    dylib boundaries, and the failure mode of getting it wrong is a `trust:`
    line that omits a contract the image's link line carries.  A contract listed
    for a call nobody makes costs a reader one line; one missing costs them the
    whole point of the line.  `formal/admitted.py`'s module docstring states the
    same rule where the contracts themselves are declared.

    A file that reaches none returns `[]`, which is what every caller tests for
    and what keeps the common case free.
    """
    from formal import admitted as _admitted
    hostmod_paths = {os.path.abspath(full)
                     for _rel, full in _admitted.hostmod_files()}
    seen_paths = set()
    out = {}
    queue = [os.path.abspath(source_path)]
    while queue:
        path = queue.pop(0)
        if path in seen_paths:
            continue                      # cycle, or a diamond: one visit
        seen_paths.add(path)
        for st in module_statements(path):
            if not isinstance(st, F.ImportStmt):
                continue
            names = [st.module]
            for mod, _alias in (st.extra or []):
                names.append(mod)
            for m in names:
                if not isinstance(m, str) or not m:
                    continue
                dep = resolve_module_path(m, relative_to=path,
                                          project_root=source_path)
                if dep is None:
                    continue
                if os.path.abspath(dep) not in seen_paths:
                    queue.append(os.path.abspath(dep))
        if path in hostmod_paths:
            for c in _admitted.contracts_in_file(path):
                out[c.qualified] = c
    return [out[k] for k in sorted(out)]


def import_closure_digest(source_path: str, _seen=None) -> str:
    """A digest of every SOURCE this file's build reads besides itself.

    The question a cache key has to answer before it can decide whether a
    stored verdict is still true, and for this backend it is not "the entry
    file": `formal/build.py`'s `_resolve_imports` compiles every module in the
    file's transitive import closure into a dylib and links it, so a module's
    bytes decide which symbols the image binds, whether it builds at all, and
    the image's whole dependency set. A key that folds in the compiler and the
    entry file but not those sources serves a verdict about the module's OLD
    contents — and the sweep's output is a CLASSIFICATION derived from the
    build's message, so the replay is not merely a stale pass/fail: the same
    file can come back as `not-answerable/host-import` (module not found),
    `codegen/dependency` (module found, refuses a construct) or `pass`.
    Measured on `tools/formal_sweep.py`: a fix to `formal/hostmods/re.mojo`
    left the next run reporting `cas: 4 hit` and "verdict history: unchanged: 4"
    for four files that now build
    (`cas.formal_build_key`'s `imports` clause is where this digest is folded
    in, and `test_formal_sweep_cache_key.py` is what pins that it moves the
    key).

    It walks with the SAME two functions the build walks with —
    `imported_modules` for what a statement list imports and
    `resolve_module_path` for where a name is found, with the same
    `relative_to`/`project_root` the build passes — so it cannot resolve a
    module the build would not have compiled, or skip one it would. A second
    resolution walk written here would be exactly the kind of pair that agrees
    until the day it does not, and the disagreement would be a stale verdict
    rather than an error.

    What goes in:

      * the RESOLVED path and its content digest, for every module in the
        transitive closure — a `.py` sibling, a `formal/hostmods/*.mojo`, or a
        stdlib source, since all three are compiled;
      * the module NAME for every name that resolves to nothing. The path being
        unresolvable is itself an input (it is what makes the verdict
        `not-answerable/host-import`), and the resolver's own table is in
        `cas.formal_fingerprint()` already.

    A module that is already on the walk is not walked twice (`_seen`, keyed by
    resolved path), which is what makes a cyclic import terminate — the same
    reason `build_module_dylib`'s `_stack` exists, and a key function that hangs
    on `a` importing `b` importing `a` would take the sweep down with it.

    Returns `''` for a file that imports nothing, and for one that cannot be
    parsed or read. Neither is a hole: a file with no imports has nothing to
    fold in, and such a file's verdict is a parse error (or an unreadable-file
    cause), which depends on nothing else — while raising here would turn a
    cache key into a second thing that can fail a sweep the build itself would
    have reported.

    Cost, measured: `''` for a file with no imports, 0.11 s for one importing
    four modules, and 1.5 s for `std/python/bindings.mojo`'s whole stdlib
    closure — parsing the modules, not hashing them (a lighter parse that skips
    the field-evidence census is 0.2 s faster and produces the same digest, so
    the build's own parse is kept for the reason above).
    """
    _seen = {} if _seen is None else _seen
    key = os.path.abspath(source_path)
    if key in _seen:
        return _seen[key]
    # Set BEFORE the walk, so a cycle sees this entry rather than recursing.
    _seen[key] = ""
    try:
        with open(source_path, "rb") as f:
            source = f.read()
    except OSError:
        return ""
    try:
        stmts = parse_module_for_closure(source, source_path)
    except Exception:  # noqa: BLE001 — a parse error is the build's answer
        return ""
    parts = []
    for mod in imported_modules(stmts):
        path = resolve_module_path(mod, relative_to=source_path,
                                   project_root=source_path)
        if path is None:
            parts.append(f"{mod}\0unresolved")
            continue
        abspath = os.path.abspath(path)
        if abspath in _seen:
            parts.append(f"{mod}\0{abspath}\0seen")
            continue
        try:
            with open(path, "rb") as f:
                parts.append(f"{mod}\0{abspath}\0{cas.hash_parts(f.read())}")
        except OSError:
            parts.append(f"{mod}\0{abspath}\0unreadable")
            continue
        parts.append(import_closure_digest(path, _seen))
    # A file that imports NOTHING contributes `''`, not the hash of an empty
    # list. That is not a micro-optimisation: `''` is the value
    # `cas.formal_build_key` was already producing for such a file, so adding
    # this clause to the key leaves every import-free verdict's key — and its
    # cache entry — exactly where it was, and the invalidation this fixes is
    # confined to the files that actually reach a module.
    digest = cas.hash_parts(*parts) if parts else ""
    _seen[key] = digest
    return digest


def parse_module_for_closure(source: bytes, filename: str):
    """`formal.build.parse_module` for a source already in hand.

    The build's own parse, deliberately, including the field-evidence census it
    attaches: a digest computed over a differently-parsed tree would be a
    digest of something this backend never compiles. Bytes in, statements out —
    the caller has the bytes because it read them for its own digest.
    """
    from formal.build import parse_module
    if isinstance(source, bytes):
        source = source.decode("utf-8", "replace")
    return parse_module(source, filename=filename)


def imported_modules(stmts) -> list:
    """The module names a statement list imports, in source order, deduped.

    `import a.b`, `import a.b as c` and `from a.b import x, y` all name the
    module `a.b`; the alias and the imported names do not change which module
    has to be built. `extra` carries `import a, b, c`'s additional names.

    A FUNCTION-LOCAL import is collected too, and the reason is that the
    exclusion below is about CONDITIONALS, not about nesting: `import x` at
    column 0 and `import x` inside a `def` are both unconditional statements of
    their block, and the callee they bind is on the link line either way.

    Measured: `test_runtime_header_scan.py:67` writes

        def exports(header):
            import reflect
            return {e['name'] for e in
                    reflect.collect_runtime_exports_h(...)}

    and the local import was not seen at all, so `reflect` reached
    `check_module_symbols` as a bare name with nothing to place it and the file
    was refused with

        exports: 'reflect' has no home: this module declares no module-level
        name by that spelling, and the reading function declares no local or
    parameter by it either. This path places a name in a register or a spill
    slot allocated for THIS function […]

    which is FALSE in a way a reader cannot check: `reflect` is a module-level
    name of ANOTHER module, and the walk asked the wrong question because the
    name it never found is the answer. Hoisting the same import to column 0
    changes the message to the true one ("imports 'reflect', which cannot be
    built either: … importlib, which is a host module"), which is the whole
    diagnosis in one line and moves the file out of the `codegen` class it does
    not belong in.

    Two kinds of import are deliberately NOT dependencies, and both exclusions
    belong here rather than at each call site, because every consumer of this
    list wants the same answer:

      * a semantically inert import (`from __future__ import annotations` — see
        `INERT_MODULES`), which binds nothing and emits nothing;
      * anything nested inside an `if`/`try` body. A `TYPE_CHECKING` block, an
        `if sys.version_info` arm and a guarded `try: import x except
        ImportError` are inert for the same underlying reason — the name is not
        unconditionally required — and excluding them structurally means the
        rule cannot go stale as new spellings appear.

    So the walk descends into a function body and stops at a conditional, and
    `test_guarded_imports_stay_inert` pins both halves: it asserts a guarded
    import inside a function body is still inert, not just one at module level.

    What is left is exactly "what must be on the link line for this file".
    """
    out = []
    for st in stmts or []:
        if isinstance(st, F.ImportStmt):
            names = [st.module]
            for mod, _alias in (st.extra or []):
                names.append(mod)
            for m in names:
                if (isinstance(m, str) and m and m not in out
                        and not _is_inert_module(m)
                        and not is_frontend_provided(m)):
                    out.append(m)
        elif isinstance(st, F.FromImportStmt):
            m = st.module
            if (isinstance(m, str) and m and m not in out
                    and not _is_inert_module(m)
                    and not is_frontend_provided(m)):
                out.append(m)
        elif isinstance(st, F.FunctionDef):
            # Into the BODY, and nowhere else. `elif`, not `if`: a
            # `ClassDef`/`StructDef` body is a class body, where `import` has
            # the same conditional-or-not question a function body's does —
            # but this walk has no reason to reach it and adding it is a
            # second question, not this one. An `If`/`Try` is deliberately NOT
            # descended, which is the whole exclusion the docstring states.
            for m in imported_modules(getattr(st, "body", None) or []):
                if m not in out:
                    out.append(m)
    return out


def import_bindings(stmts) -> dict:
    """`{local name: (module as spelled, defining name)}` for this file.

    THE missing half of `imported_modules`. That function answers "which
    modules have to be on the link line", which is a question about DEPENDENCIES
    and is deliberately blind to the alias and to the imported names — the same
    answer for `from m import f` and `from m import f as g`. This one answers
    "which name in THIS file means which export of which module", which is the
    question a call site asks, and the two are different questions about the
    same statements.

    It exists because the answer was being reconstructed at the call site, from
    a name that could not carry it. `ARM64Codegen._extern_symbol` looks a bare
    callee up in the flat `{bare name: exported symbol}` map built from the
    libraries' manifests, which is keyed by the DEFINING name, and the callee
    it is given is the name AS SPELLED at the call site. For `from m import f as
    g` those differ, the lookup misses, and the fallback binds `g` itself —
    which the link audit then refuses, because nothing defines `g`:

        build: osp3.mojo: the image would bind 2 symbol(s) that nothing
        provides, so it could not be loaded: os_exists, os_isdir.

    The information was already in hand at import time and was simply not
    carried to the call site; this is where it is read off the same statements
    `imported_modules` reads, so the two cannot disagree about which file
    imported what.

    The module is kept AS SPELLED, which is what `model.dylib_export_module`
    needs: it falls back to `abi_module_name(spelling)`, and a relative
    spelling's manifest is keyed by the dot flattened (`._syscalls` builds and
    is filed as `__syscalls`). A local name that also DEFINES something in
    this file is left out — that is a local definition and it wins, which is
    the same precedence `reexported_names` states for a re-export.
    """
    defined = {st.name for st in (stmts or [])
               if isinstance(st, (F.FunctionDef, F.StructDef))}
    out: dict = {}
    for st in stmts or []:
        if not isinstance(st, (F.ImportStmt, F.FromImportStmt)):
            continue
        for bound, module, name in _model.import_bindings(st):
            if (bound in defined or bound in out or not isinstance(bound, str)
                    or not bound or not isinstance(name, str) or not name):
                continue
            out[bound] = (module, name)
    return out


def module_statements(path: str) -> list:
    """The parsed top-level statements of the module at `path`, or [].

    ONE parse per (path, content), for every reader in this module, and the
    cache key includes the content digest rather than the mtime: three callers
    (`imported_struct_defs`, `declared_kinds`, `build_module_dylib`) each want
    the same file's AST and each used to read and parse it for itself, so a
    program importing four modules parsed each of them four times — and after
    `external_declarations` existed it would have been five. The digest is
    computed from the bytes already read, so verifying the cache costs a hash
    and not a parse.

    Unreadable or unparsable is [] rather than an exception, which is what all
    three callers already did: a module whose source has gone is a module with
    no declarations, and each caller has a better message for its own case."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return []
    digest = cas.hash_parts(raw)
    key = (os.path.abspath(path), digest)
    hit = _PARSED.get(key)
    if hit is not None:
        return hit
    try:
        stmts = F.Parser(F.py_tokenize(raw.decode("utf-8", "replace"))) \
                  .with_filename(path).parse_module()
    except Exception:
        stmts = []
    _PARSED[key] = stmts
    return stmts


# Source TEXT, cached beside `_PARSED` on the same (path, content-digest) key and
# for the same reason. `reflect.export_exclusions` — the one rule that says which
# declared names are generic templates, and the one `collect_exports_src` filters
# the export table through — is a function of the text, so the text is a first
# class input to the export and specialization decisions and re-reading it per
# question is what `module_statements` exists to stop. Unreadable is "" rather
# than an exception, for `module_statements`'s own reason: every caller has a
# better message for a module whose source has gone.
_SOURCE_TEXT: dict = {}


def module_source_text(path: str) -> str:
    """The text of the module at `path`, or "" — cached per (path, content)."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return ""
    digest = cas.hash_parts(raw)
    key = (os.path.abspath(path), digest)
    hit = _SOURCE_TEXT.get(key)
    if hit is None:
        hit = raw.decode("utf-8", "replace")
        _SOURCE_TEXT[key] = hit
    return hit


def external_declarations(linked: list) -> dict:
    """`{export symbol: FunctionDef}` for the linked libraries' function exports.

    A call into another image needs the CALLEE's parameter list, and the
    importing build has no copy of it: the callee is not in this module's
    function registry, it is a symbol in a library on the link line. So
    `bind_call_arguments` was never consulted for it, the omitted argument
    register kept whatever the caller last put there, and a defaulted parameter
    arrived as a stack address — measured, `need_two(1)` across a dylib
    returning 1867609072 where the callee's own default says 511, while the
    identical call in the SAME file returned 511. A silently wrong argument, at
    a boundary whose whole purpose is that the contract does not change there.

    The declarations are read from each library's OWN source — the path its
    manifest records, which is the exact file it was compiled from — so the
    parameter list read here cannot disagree with the library on disk. That is
    the same argument `imported_struct_defs` makes for a struct's layout, and
    the reason the manifest carries the path rather than a module name that a
    reader would have to resolve a second time.

    Keyed by the EXPORT SYMBOL and not by the bare name, which is what makes
    this safe: two libraries on one link line may export the same name, and the
    flat `{bare: symbol}` map resolves that by first-wins. Keying by the symbol
    the call will actually bind means a call can never be handed the wrong
    callee's signature, whatever the name collision was.

    A library with no `source` — the runtime dylib, whose exports come from a C
    header — contributes nothing, which is the honest answer: there is no
    declaration here to read, so a call to one keeps the old positional-only
    behaviour rather than being given a fabricated signature."""
    out: dict = {}
    for lib in linked or []:
        source = lib.get("source")
        if not source or not os.path.isfile(source):
            continue
        by_name = {}
        for st in module_statements(source):
            name = getattr(st, "name", None)
            if isinstance(st, F.FunctionDef) and name:
                by_name.setdefault(name, st)
        for entry in (lib.get("exports") or []):
            st = by_name.get(entry.get("name"))
            if st is not None:
                out.setdefault(entry.get("symbol"), st)
    return out


def linked_module_paths(linked: list) -> list:
    """The source path of every linked library that recorded one, in link order.

    A library built from a module's own source records that path in its
    manifest (`write_dylib_manifest`'s `source`), so this is the exact file the
    library was compiled from and not a module name resolved a second time.
    Duplicates are dropped and order is kept, so a program that links the same
    module twice is read once.

    A library with no recorded source — the runtime dylib, whose exports come
    from a C header — contributes nothing, which is the honest answer: there is
    no module declaration behind it to read."""
    out, seen = [], set()
    for lib in linked or []:
        path = lib.get("source")
        if path and os.path.isfile(path) and path not in seen:
            seen.add(path)
            out.append(path)
    return out


def linked_struct_owners(linked: list) -> dict:
    """`{struct name: [{"library", "module", "signature"}, …]}` off the link line.

    The complement of `linked_module_paths`, and it answers with NO source at
    all: a library advertises a struct's METHODS (`kind: "method"` entries, one
    per `add`/`__len__`/`__init__`) whether or not the file it was built from
    is still readable, and the struct's NAME is in every one of them. So a
    manifest alone can say "this image links a library that has `Bag`", which is
    the fact a build-pass refusal needs when the declaration itself is missing
    (`check_construction_shapes`'s `undeclared_linked_struct_refusal` arm).

    The struct name is the `signature` up to its last `.`, because that is what
    `_formal_exports` writes there — `f"{struct}.{method}"`, so `Bag.__len__`
    and `My_Bag.add` both yield the struct and neither yields a fragment of it.
    Deriving it from `name.split("_")[0]` instead would turn `My_Bag` into `My`,
    which is a different type; that is why there is one rule and not two
    spellings to choose between.

    Entries are deduped per library, because a struct with four methods would
    otherwise contribute four near-identical rows to a message and the reader
    would read the repetition as four libraries. Link order is kept."""
    out: dict = {}
    for lib in linked or []:
        library = lib.get("install_name") or lib.get("path") or ""
        module = lib.get("module") or ""
        seen = set()
        for entry in (lib.get("exports") or []):
            if entry.get("kind") != "method":
                continue
            signature = entry.get("signature") or ""
            struct, dot, _method = signature.rpartition(".")
            if not dot or not struct or struct in seen:
                continue
            seen.add(struct)
            out.setdefault(struct, []).append(
                {"library": library, "module": module, "signature": signature})
    return out


def module_struct_defs(path: str, project_root: str = None) -> list:
    """The `StructDef`s the module at `path` declares, following its re-exports.

    The one-module half of `imported_struct_defs`, split out because
    `_imported_structs` reaches it from a LINKED LIBRARY as well as from an
    import, and a library is a path rather than an importing file with
    statements to walk out of. Same contract as the whole-module version: a
    package's API is its re-exports, so reaching a type means walking to the
    module that defines it, and the walk is transitive and cycle-safe."""
    out, seen, visited = [], set(), set()

    def collect(p):
        key = os.path.abspath(p)
        if key in visited:
            return
        visited.add(key)
        mod_stmts = module_statements(p)
        for st in mod_stmts:
            name = getattr(st, "name", None)
            if isinstance(st, F.StructDef) and name not in seen:
                # The same attach `imported_struct_defs` does, and for the same
                # reason — see that function's docstring. It is here as well as
                # there because a LINKED LIBRARY reaches its declarations
                # through this function and never through the import walk, so
                # attaching only in `imported_struct_defs` would leave every
                # struct behind a `--link-dylib` exactly as unclassified as the
                # ones behind an import were.
                _attach_declared_census(st, p)
                seen.add(name)
                out.append(st)
        for st in mod_stmts:
            if not isinstance(st, F.FromImportStmt):
                continue
            dep = resolve_module_path(st.module, relative_to=p,
                                      project_root=project_root or p)
            if dep:
                collect(dep)

    collect(path)
    return out


def module_templates_by_path(path: str, project_root: str = None) -> dict:
    """`{module path: [generic template name, …]}` for `path`'s re-export closure.

    The same walk as `module_struct_defs` and for the same reason: a package's
    API is its re-exports, so a template an importer reaches through a package is
    DECLARED by a sibling and has to be instantiated in that sibling's library —
    the demand belongs to the module that owns the definition, not to the one
    whose name the importer happened to import. `std/collections/__init__.mojo`
    re-exporting `BinaryHeap` is the measured case, and it is 162 of the 165
    files in `bugs/FORMAL_sweep_work_map_2026-10-03_b8.md` §3.1.

    Which declared names are templates is `formal/monomorph.py`'s question and is
    answered there by `reflect.export_exclusions` — the same rule the export
    table is filtered through, so the set instantiated and the set excluded
    cannot drift apart.
    """
    from formal import monomorph as MM            # lazy — pulls the middle tier
    out, visited = {}, set()

    def collect(p):
        key = os.path.abspath(p)
        if key in visited:
            return
        visited.add(key)
        names = MM.template_names(module_source_text(p))
        if names:
            out[key] = names
        for st in module_statements(p):
            if not isinstance(st, F.FromImportStmt):
                continue
            dep = resolve_module_path(st.module, relative_to=p,
                                      project_root=project_root or p)
            if dep:
                collect(dep)

    collect(path)
    return out


def instantiation_demands(module_path: str, consumer_src: str,
                           project_root: str = None,
                           own_templates=()) -> dict:
    """`{module path: {template: [(type arg, …), …]}}` — what `consumer_src`
    asks of `module_path`'s re-export closure.

    `consumer_src` is ONE source's text, and the answer is keyed by the module
    that DECLARES each template rather than by the module the consumer imported
    the name from, because that is where the instantiation has to be compiled:
    a boundary symbol lives in the library that defines the body.

    ONE parse of `consumer_src` for the whole closure. `module_templates_by_path`
    can reach thirty modules (a program importing `std.collections` pulls the
    package and every sibling it re-exports), and re-parsing the consumer per
    module made the cost of a demand set the product of the two. The unfiltered
    set of bracketed callees is therefore computed once here and intersected per
    module, which is also why the intersection is a plain set test rather than a
    re-walk: `formal/monomorph.py::demands` is the one place that reads call
    sites, and it reads them for the filtered set too.
    """
    from formal import monomorph as MM            # lazy — pulls the middle tier
    found = MM.all_instantiation_calls(consumer_src)
    if not found:
        return {}
    out = {}
    for p, names in module_templates_by_path(module_path,
                                            project_root).items():
        got = MM.demands_from_calls(found, names, own=own_templates
                                    if os.path.abspath(p) ==
                                    os.path.abspath(module_path) else ())
        if got:
            out[p] = got
    return out


def _search_roots(relative_to: str, project_root: str) -> list:
    """Directories a module name is looked for in, nearest first.

    A module inside a package importing a sibling of the PACKAGE (not of
    itself) is ordinary code, not a mistake: `pkg/__init__.mojo` doing
    `from leaf import base` while `leaf.mojo` sits beside `pkg/`. So the walk
    goes from the importing file's own directory up towards the project root
    — the directory of the program being compiled — and stops there. It does
    NOT continue past the project root: an unbounded walk would happily
    resolve `import math` to some unrelated ~/math.mojo, which is far worse
    than failing to find it. A file under the stdlib also gets the stdlib
    root, so stdlib modules resolve each other.

    Two roots are FIXED rather than walked: the repository root, and
    `_HOSTMODS_ROOT` — this backend's own `os`/`sys`/`struct`. Both are
    appended after everything nearer, and the second is listed by NO OTHER
    resolver in the tree, which is what keeps a Mojo `os` from capturing
    `import os` in the compiler's own sources."""
    roots = []
    if relative_to:
        here = os.path.dirname(os.path.abspath(relative_to))
        # project_root is normally the path of the file being compiled, so
        # normalise it to a directory — comparing against a filename would
        # never match a walk that stops at directories.
        top = os.path.abspath(project_root) if project_root else None
        if top and not os.path.isdir(top):
            top = os.path.dirname(top)
        d = here
        # Ascending from `here` towards `top`: while d is below top we keep
        # going; when d IS top we take it and stop; and if d is a strict
        # ANCESTOR of top we have overshot the project root and must stop
        # there — continuing would search the whole filesystem, where
        # `import math` could bind to an unrelated ~/math.mojo.
        unlimited = 8
        while True:
            if top:
                if d == top:
                    roots.append(d)
                    break
                if top.startswith(d + os.sep):
                    break                       # overshot the project root
            roots.append(d)
            parent = os.path.dirname(d)
            if parent == d:
                break
            if not top:
                unlimited -= 1
                if unlimited <= 0:
                    break                          # no project root: bounded
            d = parent
    # The repository root, last among the local roots. For the file being
    # compiled the "project root" above IS that file's own directory, so the
    # walk stops after one entry and a sibling of the REPO — `fire_compiler`,
    # `gimple_codegen`, `type_system` — is out of reach even though the file
    # importing it is in the same tree. That is the ordinary case for a
    # multi-file project in this repository, and it produced the flatly false
    # "not a stdlib or sibling module, and no such file exists" for a file
    # that was sitting there. This root is fixed and specific (the tree this
    # module lives in), NOT a walk to `/`: the whole point of stopping at the
    # project root was to keep `import math` from binding to an unrelated
    # ~/math.mojo, and a bounded root cannot do that.
    roots.append(_REPO_ROOT)
    # This backend's own modules — `os`, `os.path`, `sys`, `struct` — last, so
    # a project's own `os.mojo` beside the file importing it still wins. They
    # are Mojo source in a search root, so they are found by PASS 1, which is
    # what keeps the "Mojo source beats the host-module list" rule the rest of
    # this module is built on: `os` is not in `HOST_MODULES` at all, and
    # reaching it here is the only reason that is true.
    #
    # LAST rather than first is deliberate, and the ordering is the same one
    # `_REPO_ROOT` is appended under: nearest first, and this is neither the
    # importing file's directory nor anything above it. It is also the ONLY
    # root in this list that no other resolver in the tree shares, which is the
    # property that keeps a Mojo `os` from capturing `import os` in
    # `fire.py` — see `_HOSTMODS_ROOT`.
    if os.path.isdir(_HOSTMODS_ROOT):
        roots.append(_HOSTMODS_ROOT)
    try:
        import module_loader
        stdlib = getattr(module_loader, "STDLIB_PATH", None)
        if stdlib and (not relative_to or
                       os.path.abspath(relative_to).startswith(
                           os.path.abspath(stdlib) + os.sep)):
            roots.append(os.path.abspath(stdlib))
    except Exception:
        pass
    seen, out = set(), []
    for r in roots:
        if r and r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _candidates(module_name: str, base: str, ext: str) -> list:
    """The file shapes a module name can take under `base`, for one extension.

    `<name>.mojo`, `<name>/__init__.mojo` (a package), and the same two spelled
    with the LEAF only. The leaf fallback is what makes a package-relative
    dotted import of a sibling work: inside `formal/`, `import formal.types`
    looks for `formal/formal/types.mojo` (the path spelled from the project
    root, which is `formal/` itself here) and finds nothing, but the sibling
    really is `types` in the very directory the import was written in.
    module_loader resolves the same two shapes for the stdlib, so this is the
    same rule, not a second one.
    """
    rel = module_name.replace(".", os.sep)
    leaf = module_name.split(".")[-1]
    return [os.path.join(base, rel + ext),
            os.path.join(base, rel, "__init__" + ext),
            os.path.join(base, leaf + ext),
            os.path.join(base, leaf, "__init__" + ext)]


def _relative_candidates(module_name: str, relative_to: str, ext: str) -> list:
    """The file shapes a RELATIVE module name can take, resolved properly.

    A leading dot is not a path separator, and treating it as one is what made
    `..` resolve to the importer's own package. `_candidates` does
    `module_name.replace(".", os.sep)`, so `".."` becomes `"/"`, the first two
    candidates land at the FILESYSTEM ROOT where they never exist, and the leaf
    fallback — which takes `"..".split(".")[-1]`, i.e. the empty string — then
    matches the importer's OWN `__init__.mojo`. Measured, before this function
    existed:

        _candidates("..", ".../std/gpu/host/nvidia", ".mojo")
          ['//.mojo', '//__init__.mojo',
           '.../gpu/host/nvidia/.mojo', '.../gpu/host/nvidia/__init__.mojo']

        from .../gpu/host/nvidia/tma.mojo
          ".."            -> .../gpu/host/nvidia/__init__.mojo   WRONG
          "std.gpu.host"  -> .../gpu/host/__init__.mojo         right

    so `from .. import DeviceBuffer` imported nvidia's own package instead of
    its parent, and the file was refused for a module that resolves perfectly
    well (bugs/FORMAL_known_limits.md 1.3).

    The rule, which is Python's and needs no special case: **the containing
    package's directory is the importing file's own directory, whatever the file
    is called.** `a/b/c.py` is a module of package `a.b`, and `a/b/__init__.py`
    *is* package `a.b`; in both cases `.` is `a/b`. So `.` is `dirname(file)`,
    each additional dot ascends one level, and whatever follows the dots is
    appended to the result.

    This deliberately reproduces what the leaf fallback already did for `.leaf`
    and `.` — `from .path import ...` inside `os/path/__init__.mojo` resolves to
    `os/path/path.mojo` today and still does, because it was never the broken
    case. Fixing `..` must not disturb it, so `resolve_module_path` tries the
    relative form FIRST and leaves the four root passes exactly as they were.

    Ascending stops at the filesystem root rather than looping, and a name that
    asks for more levels than exist simply yields the root, fails to match, and
    falls through to the ordinary search — a miss, not a wrong answer.
    """
    if not module_name or not module_name.startswith("."):
        return []
    if not relative_to:
        return []
    dots = 0
    while dots < len(module_name) and module_name[dots] == ".":
        dots += 1
    rest = module_name[dots:]
    base = os.path.dirname(os.path.abspath(relative_to))
    for _ in range(dots - 1):
        parent = os.path.dirname(base)
        if parent == base:            # already at the root: stop, do not spin
            break
        base = parent
    if not rest:
        # `.` and `..` with nothing after them name a PACKAGE, and a package is
        # a directory. Its `__init__` is the only spelling.
        return [os.path.join(base, "__init__" + ext)]
    rel = rest.replace(".", os.sep)
    return [os.path.join(base, rel + ext),
            os.path.join(base, rel, "__init__" + ext)]


def resolve_module_path(module_name: str, relative_to: str = None,
                        project_root: str = None) -> str:
    """The source file for `module_name`, or None if it cannot be resolved.

    The search is four ordered passes, and the order is the contract — it is
    what decides whether a name binds to the target's own module, to CPython's,
    or to a source file in this repository:

      1. MOJO SOURCE, any search root, nearest first. `<name>.mojo` or
         `<name>/__init__.mojo`. This wins OUTRIGHT, including over the
         host-module list below: a `.mojo` file sitting beside the importer is
         the target's own module, and refusing it because a same-named CPython
         module exists would bind the program to the wrong one. A real Mojo
         module is a stronger statement than any name in `HOST_MODULES`.
      2. HOST MODULE. If no Mojo source exists and the name is in
         `HOST_MODULES` (or its first dotted component is), the answer is
         "CPython standard library, nothing to compile" and no sibling is
         consulted. This has to come BEFORE pass 3 rather than after it,
         because this repository contains `formal/types.py` and
         `mojo/middle/types.py` — a `.py` sibling whose basename is a host
         module name. Looking at siblings first would silently rebind a file's
         ordinary `from types import SimpleNamespace` to a same-named local
         module, which is precisely the kind of quietly-narrower result that
         turns into a bug nobody can see. Python's own absolute-import rule
         agrees: `import types` is the standard library, never a neighbour.
      3. REPOSITORY SIBLING, any search root, nearest first, `.py` and
         `__init__.py`. This repository IS the source the formal path compiles
         (that is what `fire_compiler.py`, `gimple_codegen.py` and
         `type_system.py` are), so a program that imports a sibling has to be
         able to find it. Without this pass those files were reported as
         importing "not a stdlib or sibling module, and no such file exists" —
         a statement that is simply false about a file that is sitting right
         there. A `.py` loses to a `.mojo` of the same name in a further root
         (pass 1 runs first, over every root): Mojo source is the target's own
         vocabulary and outranks a host-language source file.
      4. module_loader, for the stdlib, as the last resort.

    Returns None when all four come up empty; the caller then distinguishes a
    host module from a plain typo and says which (see
    `unresolvable_import_error`, the single wording for that).

    A RELATIVE name (`.x`, `..x`, `..`) is resolved before all four passes, from
    the importing file's own directory, by `_relative_candidates`. It cannot go
    through the root search at all: the roots are absolute directories and a
    relative name is not spelled from any of them, so pass 1 reduces it to a
    filesystem-root path that never exists and the leaf fallback then finds the
    importer's OWN package. That is how `from .. import DeviceBuffer` came to
    mean `gpu.host.nvidia` rather than `gpu.host`. Trying it first leaves the
    four passes — and the leaf fallback that several real stdlib
    `from .sibling import` statements depend on — exactly as they were.
    """
    if module_name.startswith("."):
        for ext in (".mojo", ".py"):
            for cand in _relative_candidates(module_name, relative_to, ext):
                if os.path.isfile(cand):
                    return cand
        # A relative name that resolved to nothing is a MISS, and returning None
        # here rather than falling through is the point. A relative name is by
        # definition not spelled from any of the search roots, so the root
        # passes cannot answer it correctly -- they can only answer it wrongly.
        # They did: the leaf fallback takes `"..".split(".")[-1]`, which is the
        # EMPTY STRING, so any all-dots name matched `__init__` in the importing
        # file's own directory and `from .......... import x` resolved to the
        # importer's own package. A miss is the honest answer.
        return None
    roots = _search_roots(relative_to, project_root)
    for ext in (".mojo",):                       # pass 1
        for base in roots:
            for cand in _candidates(module_name, base, ext):
                if os.path.isfile(cand):
                    return cand
    if is_frontend_provided(module_name):        # pass 1b
        # The front end implements it, at compile time, so there is no source
        # to compile and no dylib to link — the same answer a host module
        # gives, and the same `None`, for a different reason. Placed HERE,
        # between pass 1 and pass 2 and not inside pass 2, because pass 2 is the
        # HOST MODULE rule and this is not one: a name that left
        # `HOST_MODLED` to become front-end-provided would otherwise fall
        # through to pass 3, where this repository's own `dataclasses.py`-like
        # siblings would capture it.
        return None
    if _is_host_module(module_name):              # pass 2
        return None
    for ext in (".py",):                         # pass 3
        for base in roots:
            for cand in _candidates(module_name, base, ext):
                if os.path.isfile(cand):
                    return cand
    try:                                         # pass 4
        from module_loader import ModuleLoader
        path = ModuleLoader().resolve_module_path(module_name)
        if path and os.path.isfile(path):
            return path
    except Exception:
        pass
    return None


# What to DO about a host module, for the names where measurement has already
# answered it.  Published here rather than written into the message at each site
# because the message is generated: one wording for one cause is what keeps a
# cause from being filed under two headings, and the advice has to travel with
# the SAME generated string or it will be true of the one call site somebody
# edited.
#
# It is a table and not a comment because a comment is read by the next person
# editing `formal/` and a refusal is read by the person whose file does not
# build.  `HOST_MODELLED`'s entries are the former; this is the latter, and it
# exists because the gap it fills is measured: every file that stops on one of
# these names stops on the module, never reaching the call, so a message that
# only names the module leaves the reader with nothing to act on and the fix is
# a bug doc one reader has to find.
#
# A name LEAVES by being WRITTEN, the same rule `HOST_MODELLED` follows: the
# advice must name what the file CAN do, never what it cannot, and an entry left
# behind after a module exists would be the advice to reimplement it.  So an
# entry here is a CLAIM that the module still has no source, and
# `host_module_advice_is_honest` is the check that says so.
#
# This is also the cheapest real deliverable in
# `bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md`, and it is a
# MESSAGE, not a module: that document measured five files in this repository's
# own tooling blocked on `import collections`, and without a line saying what to
# write instead the refusal reads as "this target cannot do records" — which is
# what the next person files the next bug document about.  The `collections` entry
# is the worked example: a COMPILE-TIME-KNOWN record with readable fields is a
# `struct` (`formal/hostmods/struct.mojo` exists, and a struct's fields are words
# in a frame), while a type built AT RUN TIME has no answer at all, because
# there is no word that denotes a type on this path.  Both halves are stated so
# nobody has to discover the second one by building.
HOST_MODULE_ADVICE = {
    "collections":
        "the record the callers here want is a STRUCT: declare it with its "
        "fields, and read them as fields. Its only module-level name is "
        "`namedtuple`, which builds a TYPE at run time, and there is no word on "
        "this path that denotes a type (doc/ABI.md, Generics), so "
        "`namedtuple(\"Census\", \"ok detail …\")` asks for something that cannot "
        "be lowered even in principle — which is why \"write a struct instead\" is "
        "a complete answer for a record whose fields the compiler can see and is "
        "NOT an answer for one it cannot. Measured: five files in this "
        "repository's own tooling import it (`formal/lean.py`'s `Census`, "
        "`formal/model.py`'s `InitShape`, `tools/formal_sweep.py`'s three). "
        "`Counter` is a dict rather than a record, so it is the other question: "
        "see bugs/FORMAL_listdir_no_run_time_sequence.md",
    "copy":
        "a field-wise copy of a type the COMPILER KNOWS at the call site is a "
        "struct construction: build a new one and assign the fields. A copy "
        "chosen at run time, over a graph whose shape the build cannot see, has "
        "no answer here — the same missing thing as a type built at run time",
    "functools":
        "the higher-order functions are a callable this path has no "
        "representation for; the arithmetic they wrap is ordinary code and can "
        "be written out",
}

# Three entries, and three is the right size for a mechanism that must not become
# a dumping ground: an entry is worth a row only when the answer is MEASURED and
# the alternative is a spelling the reader can write today.  `math`, `argparse`
# and `contextlib` are the other candidates and none qualifies yet — their files
# answer, so the reader is not stuck.


def host_module_advice(name: str) -> str:
    """The `name`'s next step, or `''` when there is no measured one.

    `name` is matched on its TOP component, like `_is_host_module` and
    `host_module_tier`, so an advice written for a package names every module
    under it — which is what a reader of `collections.abc` wants and what a
    per-spelling table would get wrong by omission."""
    if not name:
        return ""
    return HOST_MODULE_ADVICE.get(name) \
        or HOST_MODULE_ADVICE.get(name.split(".")[0], "")


def unresolvable_import_error(source_path: str, module_name: str) -> str:
    """The one wording for "this import names nothing this backend can build".

    Two call sites raise it — formal/build.py for the file being compiled and
    `build_module_dylib` for a file reached through a dependency — and two
    messages for one cause is how a real failure ends up filed under the wrong
    heading. It lives here, next to the rules that decide which of the two
    reasons applies, so the wording cannot drift from the resolution it
    describes.
    """
    # THREE reasons now, not two, and the order is the order
    # `resolve_module_path` tries them in: Mojo source (which returns, so it is
    # never this function), then front-end-provided, then host module, then
    # plain unresolvable. A front-end-provided name is listed for completeness
    # rather than because a caller reaches it — `imported_modules` filters those
    # out before anything asks — so that the set of answers this function can
    # give is the set `resolve_module_path` can return, and a future caller
    # that bypasses the filter says the right thing.
    advice = ""
    if is_frontend_provided(module_name):
        kind = ("provided by this backend's front end as a compile-time "
                "transform, so there is no source to compile and nothing for "
                "the link step to provide")
    elif _is_host_module(module_name):
        kind = ("a host module (CPython standard library), which has no Mojo "
                "source for this backend to compile")
    elif is_cpython_stdlib(module_name):
        # The one sentence that used to be FALSE about the target.  CPython
        # ships `binascii`, `cmath`, `getopt`, `html`, `tomllib` and 217 other
        # names this table does not classify, and each of them was reported as
        # "not a stdlib or sibling module, and no such file exists" — a
        # statement about the TARGET that the interpreter's own
        # `sys.stdlib_module_names` denies.
        #
        # It is worded apart from the classified case on purpose, because the
        # two differ in something a reader acts on: a name in a tier has an
        # owner and a next step (`host_module_advice` below, and
        # `host_module_tier` for a coverage report), and a name in NO tier has
        # neither — `bugs/FORMAL_stdlib_module_names_are_not_classified.md` is
        # the queue for the 222, and it records that ZERO of them is imported by
        # any file in this repository or the stdlib, which is what makes the
        # classification a bounded piece of work rather than a coverage
        # emergency. So this says what is true (it is the host's library, there
        # is no source here) and claims nothing about which tier it belongs to.
        kind = ("a CPython standard-library module, which has no Mojo source "
                "in this tree and no tier in `formal/imports.py` saying whether "
                "implementing it would need an object this target does not "
                "have — so nothing here can say whether it is reachable")
    else:
        kind = "not a stdlib or sibling module, and no such file exists"
    advice = host_module_advice(module_name)
    out = (f"{os.path.basename(source_path)} imports {module_name!r}, which "
           f"is {kind}")
    # The next step, when there is a measured one, as its own sentence.  It is
    # appended rather than folded into `kind` so that `kind` stays the three
    # reasons the resolver can produce and a caller matching on it — a
    # classifier, the sweep's `_FRAME_ESCAPES` family, a test — keeps seeing
    # the one string it was written against.
    return f"{out}; {advice}" if advice else out


def unresolvable_import_errors(source_path: str, module_names) -> str:
    """The same sentence for a file with SEVERAL unresolvable imports, one line each.

    **One sentence per module, sorted, and every module named**, which is what
    makes the diagnostic a property of the FILE rather than of the order its
    imports happen to be written in. One-at-a-time was the only shape here for
    years, and its measurement is
    `bugs/FORMAL_admitted_contracts_sweep_measurement.md`: a file importing
    `subprocess`, `tempfile` and `glob` was refused for whichever came first in
    its statement list, so which module the diagnostic — and any census built
    from it — named changed when an unrelated import was added anywhere in the
    file. Fixing `subprocess` moved the file from "refused for `subprocess`" to
    "refused for `tempfile`", and a per-module breakdown drawn from those names
    measured a different thing before and after a change that moved no file.

    The SORT is what makes it order-independent, and the per-module lines are
    what makes it complete: a reader who has three modules to remove is told
    about three, and `tools/formal_sweep.py` can classify a file by the whole
    set instead of by whichever name it happened to parse last.

    One module still gets `unresolvable_import_error`'s single sentence verbatim,
    because that is the wording every needle in the tree — a `refuse:` case, a
    message a test asserts on, a chain the sweep peels — is written against, and
    "several" must not cost the single case its wording.
    """
    mods = sorted(set(module_names))
    if len(mods) == 1:
        return unresolvable_import_error(source_path, mods[0])
    lines = "\n".join(f"  {unresolvable_import_error(source_path, m)}"
                      for m in mods)
    return (f"{os.path.basename(source_path)} imports {len(mods)} modules "
            f"this backend cannot build, and every one of them is named here "
            f"rather than only the first: fixing one moves the file to the "
            f"next, and a diagnostic that reports one blocker at a time is a "
            f"diagnostic that has to be re-run to discover the rest\n"
            f"{lines}")


def imported_struct_defs(source_path: str, stmts: list,
                         project_root: str = None) -> list:
    """The StructDefs reachable through the modules `source_path` imports.

    An importer needs these for the same reason its own file's structs are
    needed: a constructor call and a method call have to be recognised as
    operations on a TYPE. `from lib1 import Counter` binds the name `Counter`
    in this file, so `Counter()` here is a struct default-construction — but
    with only this file's declarations in hand it looks like a call to an
    unknown function, and lowered to a BL against a symbol named `Counter`
    that nothing defines.

    The declarations are read from the imported module's own source, which is
    the same parse the module's dylib was built from, so the two cannot
    disagree about a struct's shape.

    The walk follows RE-EXPORTS, and that is not a refinement — it is the
    whole point for a package. `from pkg import Two` resolves to
    `pkg/__init__.mojo`, which declares no struct at all; it re-exports one
    from `pkg/two.mojo`. Reading only the file the import NAME resolved to
    therefore found nothing, and the importer's `Two(...)` was lowered as a
    call to an undefined function — the type half of exactly the bug the
    re-export fix in `build_module_dylib` addresses on the symbol half. A
    package's API is its re-exports, so reaching a type means walking to the
    module that defines it.

    Transitive, and cycle-safe: a package that re-exports from a sibling that
    re-exports back terminates on the visited set, and a struct is collected
    once however many paths reach it.

    **The census is attached to each struct by the module that DECLARES it**,
    and that is what makes a `comptime` class member of an IMPORTED module a
    constant here: before, nothing attached it, so `_split_declaration` returned
    None and every class-level name stayed a field.
    `module_statements` caches one parse per file per content, so
    the statements a declaration came from are in hand here; before this,
    nothing called `formal.model.attach_field_evidence` on an IMPORTED module's
    structs, so `struct_field_evidence` was None, `_split_declaration` returned
    None, and every class-level name stayed a field. A `comptime IS_FLAT = True`
    in an imported module was therefore reported as a field the struct does not
    have — which is the in-file refusal `formal/build.py`'s
    `_rewrite_class_constants` exists to prevent, reached through the module
    boundary instead of around it.

    Attached from the DEFINING module's statements rather than the importer's,
    and that direction is the whole of the soundness argument: the evidence is
    "what does this unit write into a field", so the unit that has to answer is
    the one that declares the struct. Attaching the importer's census instead
    would let a file that happens to write `x.a` demote `a` in a class it does
    not declare, which is `attach_field_evidence`'s own docstring's reason for
    putting the evidence ON the struct rather than passing it down.

    Attached for EVERY struct the walk collects, including ones it reached
    through a re-export, and before `seen` filters by name — a struct already
    collected keeps the evidence its own module gave it, so the answer does not
    depend on which path reached it first.

    **What this does NOT settle**, and the doc is explicit that it cannot be
    settled here: the census is what decides a struct's WIDTH, so attaching it
    to imported modules re-measures every imported struct in the tree at once,
    and a width decides whether a receiver is a value or a frame address. Only
    a sweep says whether that is a net gain, and a sweep is not a light
    worker's to run.
    """
    out, seen = [], set()
    for mod in imported_modules(stmts):
        path = resolve_module_path(mod, relative_to=source_path,
                                   project_root=project_root or source_path)
        if path is None:
            continue
        for st in module_struct_defs(path, project_root or source_path):
            if st.name in seen:
                continue
            # The DEFINING module's statements, not this file's: `path` is the
            # module the walk reached, and `module_statements` is the same
            # cached parse the walk itself read the struct out of, so the
            # evidence and the declaration cannot come from different versions
            # of the file. `visited` is the walk's own set, so a struct reached
            # twice is attached once.
            _attach_declared_census(st, path)
            seen.add(st.name)
            out.append(st)
    return out


def _attach_declared_census(struct_def, declaring_path: str) -> None:
    """`attach_field_evidence` for one struct, from ITS OWN module.

    Split out of `imported_struct_defs` because it has to be callable from
    `module_struct_defs` too — that is the function a LINKED LIBRARY reaches,
    and a library's declarations come through it rather than through the
    import walk. Two call sites attaching the same evidence is one rule with two
    callers, which is the point; a second implementation here would be a second
    thing that could disagree about what a class-level name is.

    A struct with evidence already attached is left alone, so an inner
    `attach_field_evidence` (from `formal/build.py`'s `parse_module`, which runs
    when the module is compiled as the ENTRY) is not overwritten by an importer's
    view — and two modules' evidence for one struct is not a thing that can
    happen anyway, since the walk is keyed by declaring path.
    """
    if getattr(struct_def, "_field_evidence", None) is not None:
        return
    from formal import model as M
    M.attach_field_evidence([struct_def],
                            M.unit_field_evidence(
                                module_statements(declaring_path)))


def declared_kinds(path: str) -> dict:
    """{name: "function"|"type"} for what `path` declares at top level.

    Read from the module's OWN source — the same file the dylib is built from,
    so the two cannot disagree about what the module contains. A name the
    source does not declare at all is simply absent, which is how a re-export
    of something that does not exist gets caught rather than forwarded.

    **A `TraitDef` is filed as a TYPE.** It was not, and the omission refused
    every package that re-exports a trait: `std/traits/__init__.mojo` is five
    `from .sub import Name` statements over four submodules whose whole content
    is traits, and an absent name reaches `compile_formal_dylib` with kind
    `"unknown"` — which is not `"type"`, so it lands in the re-exported-FUNCTION
    set that must be *provided as a symbol*. A trait has no symbol, so the
    check refused `std/traits` with "re-exports AnyType from .anytype, but no
    module it imports exports that name", which is the message for a missing
    FUNCTION DEFINITION and is false about a name that is declared two files
    away. Filing it as the kind it is also keeps it out of that set for the
    same reason a re-exported struct is: a type is not a missing symbol."""
    out: dict = {}
    for st in module_statements(path):
        name = getattr(st, "name", None)
        if not name:
            continue
        if isinstance(st, F.FunctionDef):
            out.setdefault(name, "function")
        elif isinstance(st, (F.StructDef, F.TraitDef)):
            out.setdefault(name, "type")
    return out


def _from_import_bindings(stmts) -> list:
    """[(bound_name, original_name, module_as_spelled)] per imported name.

    The primitive both readers of a `from … import …` share, so the two cannot
    come to disagree about what the statement says. TWO names and not one,
    because `x as y` is two facts and the two readers want different ones: this
    file binds `y`, while the module being re-exported is whatever DEFINED `x`,
    and only a table keyed on the definition's own name can be matched against
    a library's export set later. The module is recorded AS SPELLED (`.sub`,
    `pkg.sub`) because nothing has resolved it here and a qualified spelling is
    a different question from a bound name."""
    out = []
    for st in stmts or []:
        if not isinstance(st, F.FromImportStmt):
            continue
        for pair in (st.names or []):
            if isinstance(pair, (tuple, list)):
                original = pair[0] if pair else None
                bound = pair[1] if len(pair) > 1 and pair[1] else original
            else:
                original = bound = pair
            if isinstance(original, str) and original:
                out.append((bound, original, st.module))
    return out


def _defined_names(stmts) -> set:
    """The names this module DEFINES — a function or a struct's name."""
    return {st.name for st in (stmts or [])
            if isinstance(st, (F.FunctionDef, F.StructDef))}


def imported_bound_names(stmts) -> dict:
    """{bound_name: module} for every name a `from … import …` BINDS here.

    Every one of them, including the private ones, which is the whole difference
    from `reexported_names`: that table answers "what does this module publish
    under its own name", and a leading underscore is exactly what stops a name
    being published. This one answers "which names in this file come from
    somewhere else", and `from ._b64encode import _b64encode` binds
    `_b64encode` here whatever it is allowed to export. The two readers used to
    be the same loop with a different filter, which is the pair that agrees
    until somebody changes one of them.

    A name this module also DEFINES is not in it, for the reason
    `reexported_names` gives and not for the export's sake: a bare call resolves
    by name, so `def take_it` here is what a call of `take_it` reaches, and the
    submodule's same-named symbol is irrelevant to it.

    Read from the AST alone, so it needs no resolution and no file: the caller
    is a pass that runs BEFORE `_resolve_imports` (`_prepare_functions`), and
    the question it asks — is this bare callee a name from another module? — is
    answerable from the import statements themselves. Whether that module
    actually builds is a different question, asked later and by someone else;
    this table does not claim it does.

    `import a.b` binds the MODULE and not a name, so it contributes nothing,
    here or in `reexported_names`."""
    defined = _defined_names(stmts)
    out: dict = {}
    for bound, _original, module in _from_import_bindings(stmts):
        if bound and bound not in defined:
            out.setdefault(bound, module)
    return out


def star_imported_modules(stmts) -> tuple:
    """The modules this file writes `from … import *` for, in source order.

    The complement of `imported_bound_names`, and it exists because that table
    CANNOT answer the question a star import raises.  `from lib import *` parses
    to a `FromImportStmt` with an EMPTY `names` list — there is nothing in the
    AST to enumerate — so the set of names it binds is `lib`'s EXPORT SET,
    which is a fact about another module's compilation and about a library that
    `_resolve_imports` has not built yet.  22 files of the standard library
    write one.

    A caller that wants to say "this callee is not defined here and not named by
    any import" has to say what this returns in the same breath, or it is
    claiming nothing binds the name when a star import may well bind it."""
    out = []
    for st in stmts or []:
        if isinstance(st, F.FromImportStmt) and not (st.names or []) \
                and st.module:
            if st.module not in out:
                out.append(st.module)
    return tuple(out)


def reexported_names(stmts, kinds_by_module: dict = None) -> dict:
    """{name: (module, kind, defining_name)} for the names this module binds by
    RE-EXPORT.

    `from .sub import addone` binds `addone` in this file without defining
    it. A package `__init__.mojo` is nothing BUT such statements, and that is
    a module with a real public API, not one with none — which is why it used
    to be refused as "a struct-only module has no free-function API" and took
    every importer of the package down with it.

    A name this module also DEFINES is not a re-export: its definition is
    here, it exports under this module's own qualifier, and the submodule's
    same-named symbol is irrelevant to anything binding it. (Which of the two
    a bare call resolves to is the pre-existing name-based-dispatch limit,
    stated in `compile_formal_dylib`'s overload handling.)

    `kind` is the DECLARED kind in the defining module (`declared_kinds`), and
    it is what makes a missing symbol reportable as the right kind of gap: a
    re-exported FUNCTION nobody exports is a missing definition, while a
    re-exported TYPE is not a missing symbol at all — a type crosses the
    boundary as a layout in the reflection table and is carried to the importer
    by `imported_struct_defs`, not by a trie entry. Conflating the two would
    either refuse every package that re-exports a type (most of them) or wave
    through a genuinely missing function.

    `defining_name` is the name the DEFINING module published the symbol under,
    and it is what every consumer of this table has to look the symbol up by:
    the link line's flat `{bare name: symbol}` map is keyed by it, so an
    ALIAS's own entry has to say whose name it stands for. It equals the key for
    an unaliased re-export, which is every re-export that existed before the
    alias was recorded.

    `import a.b` binds the MODULE, not a name, so it contributes nothing here;
    only `from ... import ...` does. The loop is `_from_import_bindings`, shared
    with `imported_bound_names`, and the three filters below are what make this
    table a PUBLICATION list rather than a binding list: a name this module
    defines, one `_is_inert_module` accepts, and a private name. The second of
    those is applied to the imported NAME and not to the module the statement
    names, which is what it has always been applied to and is not what its own
    name suggests — so `from __future__ import annotations` is still listed
    here, inert module or not. Pre-existing, harmless (a manifest entry no
    consumer asks for), and not this reader's to change while it is rewriting
    the loop underneath.

    **BOTH SPELLINGS ARE PUBLISHED, and the value carries the DEFINING name.**
    `from x import f as g` records `f -> (x, kind, f)` AND `g -> (x, kind, f)`,
    which is what this table did not do and why an aliased re-export was
    unlinkable: the manifest published the name no consumer of this module asks
    for and not the one every consumer does, so `g(21)` reached the bind audit
    as a symbol nothing provides. Recording `f` alone is right for the
    re-export's own sake — an export is matched against a library's export set
    by the name the DEFINING module gave it — and it is what a *non-aliased*
    re-export still records, so this is ADDITIVE: a consumer of either spelling
    resolves, and nothing that resolved before stops. The third element is what
    makes the second key honest: a symbol is found under the DEFINING name (the
    flat link-line map is keyed by it), so `g`'s entry has to say which name
    `g` stands for rather than looking `g` up and finding nothing.

    The alias is filtered by the SAME three rules as the original, applied to
    the alias's own spelling: a name this module defines wins over any import
    (the precedence `imported_bound_names` and `import_bindings` both state), a
    private alias is not published, and an inert one is not either. The
    original name's own filters are unchanged, so a private definition brought
    in under a public alias stays out of the manifest exactly as before rather
    than becoming a build refusal over a name the defining module does not
    export at all."""
    defined = _defined_names(stmts)
    kinds_by_module = kinds_by_module or {}
    out: dict = {}
    for bound, name, module in _from_import_bindings(stmts):
        if (name in defined or _is_inert_module(name)
                or name.startswith("_")):
            continue
        kind = kinds_by_module.get(module, {}).get(name, "unknown")
        out.setdefault(name, (module, kind, name))
        if (bound != name and bound not in defined
                and not _is_inert_module(bound)
                and not bound.startswith("_")):
            out.setdefault(bound, (module, kind, name))
    return out


def own_module_identity(source_path: str, project_root: str = None) -> str:
    """The dotted name `source_path` is ADDRESSED by, independent of who reached it.

    `_module_identity` qualifies a name against the module that spelled it, and
    so it needs to be HANDED the importer's identity — which `build_module_dylib`
    takes as `_parent` and which nothing computed. A relative import at the root
    therefore resolved differently depending on the spelling that reached it:
    `formal/hostmods/os/path/__init__.mojo` builds its `.._syscalls` import as
    the library `___syscalls.<digest>.arm64.dylib` with exports
    `___syscalls_fs_chdir_9f63a2` when compiled on its own (`_parent` is None,
    so the name passes through with its dots), and as `__syscalls.<digest>…`
    with exports `__syscalls_fs_chdir_9f63a2` when the same process reached the
    same file as `.path` from `formal/hostmods/os/__init__.mojo`. Two spellings,
    two libraries, one source file. Nothing FAILED — `_BUILT` is keyed by
    resolved path, and every consumer reads the manifest written beside the
    library the build actually produced — but `build_module_dylib`'s own comment
    says the source digest in the filename "is what makes sharing safe rather
    than merely rare", and for this module the artifact depended on the
    spelling rather than on the source. That is a content-addressing hole, and
    the fix is to make the identity a function of the FILE.

    THE PACKAGE CHAIN, and that is the rule rather than "the longest search
    root": a directory is part of a module's name exactly when it is a PACKAGE,
    which on this path means it holds an `__init__.mojo`. So the name is built
    by walking up from the file's own directory for as long as each directory
    is a package, prefixing the file's own basename at each step. For
    `formal/hostmods/os/path/__init__.mojo` that is `os` then `path` — the
    `__init__` itself contributes nothing, because it is the package rather
    than a module inside it — and for `formal/hostmods/os/_syscalls.mojo` it is
    `os` plus `_syscalls`. Which is what an importer actually spells, so
    `.._syscalls` from `os/path` resolves to `os._syscalls` whether the file was
    reached from `os` or built on its own.

    "The longest search root" was tried first and is wrong for a reason worth
    recording: `_search_roots` deliberately contains the importing file's OWN
    directory and, as a catch-all for an absolute name, the repository root.
    Both are strict ancestors of almost every file here, so the longest one is
    usually the repository — which would name `formal.hostmods.os.path`. The
    root that matters is the one whose modules are addressed WITHOUT a package
    prefix, and that is a different question from the one a search root
    answers.

    A file in no package at all falls back to the roots: the longest one that is
    a strict ancestor, relative to it with `__init__` and `.mojo` dropped. For
    `formal/hostmods/sys.mojo` under `_HOSTMODS_ROOT` that is `sys`, which is
    how `import sys` spells it.

    None when neither answers — a file outside every search root, whose
    identity nothing in this build can name. The caller then behaves exactly as
    it did before: this makes the common case right rather than making every
    case answerable, and a wrong answer here would be a wrong LIBRARY NAME,
    which is worse than the naming instability it removes.
    """
    if not source_path:
        return None
    target = os.path.abspath(source_path)
    if not target.endswith(".mojo"):
        return None
    stem = os.path.basename(target)
    stem = stem[: -len(".mojo")]
    is_package_init = stem == "__init__"

    # The package chain: each directory that holds an `__init__.mojo` is one
    # component of the name, nearest first. `os/path/__init__.mojo` is the
    # package `os.path` and contributes `path` only because its own directory
    # is the package; `os/__init__.mojo` is the package `os` and contributes
    # nothing itself.
    parts = [] if is_package_init else [stem]
    directory = os.path.dirname(target)
    while directory and os.path.exists(os.path.join(directory, "__init__.mojo")):
        parts.append(os.path.basename(directory))
        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent
    if len(parts) > (0 if is_package_init else 1):
        return ".".join(reversed(parts))

    # No package chain: fall back to the roots, so a top-level module under a
    # fixed root is still named by it.
    best = None
    for root in _search_roots(target, project_root):
        if not root:
            continue
        root = os.path.abspath(root)
        # A STRICT ancestor: the root must be above the file, never the file's
        # own directory, or every module in one directory would answer with a
        # single-component name and two of them would collide.
        if not target.startswith(root + os.sep):
            continue
        if best is None or len(root) > len(best):
            best = root
    if best is None:
        return None
    rel = os.path.relpath(target, best)
    out = []
    for part in rel.split(os.sep):
        if part.endswith(".mojo"):
            part = part[: -len(".mojo")]
        if part == "__init__":
            continue
        if not part:
            continue
        out.append(part)
    if not out:
        return None
    return ".".join(out)


def _module_identity(module_name: str, parent: str = None) -> str:
    """`module_name` resolved against the module that spelled it.

    An absolute name is its own identity. A relative one — `.sub`, `..util` —
    only means something relative to the module that wrote it, so it is
    qualified by `parent`, that module's own already-resolved identity. The
    result is the dotted name the file is really addressed by, which is what
    makes two different `a/sub.mojo` and `b/sub.mojo` two different libraries
    instead of one name written twice.

    With no parent (a top-level build, where the import is resolved from the
    project root rather than from a package) a relative name keeps its own
    spelling: there is nothing to qualify it against, and flattening it is
    better than dropping it, since the name is then at least stable."""
    if not module_name or not module_name.startswith("."):
        return module_name
    if not parent:
        return module_name
    if parent.endswith(".__init__"):
        parent = parent[: -len(".__init__")]
    return parent + module_name


def _qualified_reexports(reexports: dict, parent: str) -> dict:
    """`reexported_names`' table with every module spelling made ABSOLUTE.

    `reexported_names` records the module as the source SPELLS it, which for a
    relative import is `.sub` — a name that means nothing outside the file that
    wrote it, and this table is published in the manifest, which is read by
    builds that have never seen this file. Qualifying it here, with the same
    `_module_identity` the library's own NAME is derived with, is what makes
    the record say `pkg.sub` where the source said `.sub`, so a reader of the
    manifest can tell which module actually defines the forwarded name.

    Same function, same parent, so the record and the file name cannot disagree
    about which relative name resolved to.

    The third element is `reexported_names`' `defining_name` and is carried
    through untouched: qualifying a module must not renumber a name, and
    dropping the element here would silently turn every ALIAS back into a
    lookup under its own spelling."""
    return {name: (_module_identity(module, parent), kind, defines)
            for name, (module, kind, defines) in (reexports or {}).items()}


def _dylib_lock(out: str):
    """Exclusive, cross-process, released on exit: an flock on a side file.

    A side file and not the library itself: `compile_formal_dylib` truncates
    and rewrites the `.dylib`, so locking that would let a second process in
    as soon as the first created it. A side file is never rewritten, so the
    lock spans the whole build. `flock` is advisory and per-open-file-
    description, so it is released when the process dies — a crashed build
    cannot wedge the tree.
    """
    import contextlib
    import fcntl

    @contextlib.contextmanager
    def _locked():
        fd = os.open(out + ".lock", os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)
    return _locked()


def build_module_dylib(module_name: str, source_path: str, out_dir: str,
                       arch: str = "arm64", project_root: str = None,
                       _stack=(), _parent: str = None,
                       demands: dict = None) -> str:
    """Compile `source_path` in full into a dylib; return its path.

    "In full" = every public function the module defines. Its own imports are
    resolved first and the resulting dylibs are recorded in the manifest's
    `depends_on`, so a program linking this module also gets what IT needs
    (that is Stage 2's transitive closure; the dependency list is written now
    so nothing has to be rediscovered later).

    A module already on the stack is a cycle — legal, because ABI.md
    forward-declares functions precisely so mutual imports work. It is
    reported as a dependency and not rebuilt, which is what breaks the
    recursion.

    `arch` is part of the identity of what comes out, so it is part of BOTH
    keys. `_BUILT` used to be keyed by source path alone, so a process that
    built the same module for two architectures got the first architecture's
    dylib back for the second request; and the OUTPUT NAME is the same for
    both, so even across processes one architecture's library overwrote the
    other's on disk. Together those are why an x86-64 program could link an
    arm64 module dylib and then die in dyld with "mach-o file, but is an
    incompatible architecture" — a cache key that was not the thing being
    cached, in the one place where a stale hit is a wrong-architecture load
    rather than a slow rebuild. `out_dir` is per-architecture for the same
    reason (see `formal/build.py`'s `_resolve_imports`).

    `demands` is `{module path: {template: [(type arg, …), …]}}` — the
    INSTANTIATIONS of generic templates the importing chain asks for, attributed
    to the module that declares each template (`instantiation_demands` above).
    It is part of the artifact's identity, in BOTH keys, for the same reason
    `arch` is: a library built for `Pair[Int]` exports `prefix_Pair_Int_*` and
    one built for `Pair[String]` exports `prefix_Pair_String_*`, so they are two
    different libraries that a program may not be handed for one another. Keying
    on the source path alone would return the first one for the second request —
    in-process a wrong-boundary-symbol library that still builds and links, and
    on disk two builds writing over one path.

    A module with no demands for its own templates is unaffected: the empty set
    digests to the empty string and nothing is added to the name, so every
    existing module dylib keeps the exact path it had before this parameter
    existed.
    """
    from formal import monomorph as MM            # lazy — pulls the middle tier
    here = os.path.abspath(source_path)
    mine = (demands or {}).get(here) or {}
    dkey = MM.demands_key(mine)
    key = (arch, here, dkey)
    if key in _BUILT:
        return _BUILT[key]
    if os.path.abspath(source_path) in _stack:
        return None            # cycle: the caller links us, we link them

    from formal.build import (compile_formal_dylib, default_format,
                              FormalBuildError)
    from formal.arm64_codegen import CodegenError

    # This module's own identity, which is also what a RELATIVE import of
    # its own is resolved against. Computed before the recursion so each
    # level qualifies the next (see the `_parent` note at the output name).
    module_identity = _module_identity(module_name, _parent)

    stmts = module_statements(source_path)
    if not stmts and os.path.isfile(source_path):
        # `module_statements` swallows a parse failure the way it swallows an
        # unreadable file, because its other callers have a better message for
        # each case. A dependency that does not PARSE is a different fact and
        # it is fatal here — this module cannot be built at all — so it is
        # recovered here, by asking the parser for the reason.
        try:
            with open(source_path) as f:
                F.Parser(F.py_tokenize(f.read())).with_filename(
                    source_path).parse_module()
        except SyntaxError as e:
            raise ImportBuildError(f"{source_path}: parse error: {e}")

    # Its imports, first, so we know what this module needs.
    depends = []
    for mod in imported_modules(stmts):
        dep_path = resolve_module_path(mod, relative_to=source_path,
                                       project_root=project_root or source_path)
        if dep_path is None:
            # A HOST module is a different answer from a typo. `import os` in
            # a Python-superset language names the CPython standard library,
            # which has no Mojo source to compile and no symbol this backend
            # could bind; that is a property of the target, not a resolution
            # failure, and saying so keeps it from reading as one. It stays an
            # error either way — the file genuinely cannot be built here — but
            # it is the file's use of the host stdlib, not a broken module
            # path, and lumping the two together buries the real failures.
            # The wording is `unresolvable_import_error`'s, shared with
            # formal/build.py so the two sites cannot drift.
            raise ImportBuildError(unresolvable_import_error(source_path, mod))
        depends.append((mod, dep_path))
    # Build the dependencies first, and keep their dylibs: they go on THIS
    # library's link line, both so cross-module calls get the right exported
    # spelling and so the load commands that let dyld bind them exist.
    #
    # THIS module's own demands for ITS dependencies are computed here, from
    # THIS module's source, and are one level of the closure rather than a
    # fixpoint: a demand is a fact about one file's call sites, so each level
    # answers for its own and the recursion carries the rest down. That is what
    # makes `main → pkg → lib` work — `pkg`'s use of `lib`'s template is written
    # in `pkg`'s source and only `pkg` can see it, so a set computed once at the
    # top would miss it. The two sets are merged by path and the merge is
    # idempotent, so the same demand reached by two routes is still one.
    below = dict(demands or {})
    for other, wanted in instantiation_demands(
            source_path, module_source_text(source_path),
            project_root=project_root or source_path,
            own_templates=MM.template_names(module_source_text(source_path))
            ).items():
        merged = dict(below.get(other) or {})
        for tmpl, args in wanted.items():
            merged[tmpl] = sorted(set(merged.get(tmpl, [])) | set(args))
        below[other] = merged
    dep_dylibs = []
    for _mod, dep_path in depends:
        d = build_module_dylib(_mod, dep_path, out_dir, arch,
                               project_root=project_root or source_path,
                               _stack=_stack + (os.path.abspath(source_path),),
                               _parent=module_identity, demands=below)
        if d:
            dep_dylibs.append(d)

    os.makedirs(out_dir, exist_ok=True)
    # The library's identity is the module NAME the importer used, not the
    # file's basename: a package resolves to `<pkg>/__init__.mojo`, and two
    # packages would otherwise both be `_init_`.
    #
    # A RELATIVE name has to be qualified by the module that spelled it, or
    # it is not an identity at all. `pkg/__init__.mojo` saying `from .sub
    # import x` means `pkg.sub`; taken literally the name is `.sub`, which
    # normalizes to `_sub` — and then `a/__init__.mojo` and `b/__init__.mojo`
    # each importing their own `.sub` both write `_sub.dylib` into the SAME
    # directory, and whichever built second replaces the other's library. Two
    # packages' symbols, silently interchangeable. `_parent` carries the
    # importing module's own resolved identity down the recursion, which is
    # what turns `.sub` into `pkg.sub`.
    #
    # The architecture is part of the file NAME too, not only of the
    # directory: `out_dir` is per-arch (so the two do not overwrite each
    # other in the CAS), but a caller can pass any directory it likes, and a
    # name that collides across architectures would reintroduce the same
    # overwrite one level up.
    #
    # The SOURCE DIGEST is in the name as well, and that closes the last
    # overwrite. `(arch, module name)` is not an identity: two builds of a
    # module called `helper` — two checkouts, two temp trees, two concurrent
    # jobs in one `-j18` bucket — took the same path, so whichever finished
    # last replaced the other's library, and a program could be linked against
    # a dylib built from different source. It showed up as an intermittent
    # failure in test_formal_sweep.py's dyld-probe cases, which read a dylib
    # back off this shared path while other jobs were writing it.
    #
    # Hashing the source is what makes sharing safe rather than merely rare:
    # two builds whose sources agree produce byte-identical libraries, so
    # writing the same path is then harmless, and two that disagree get
    # different paths. Nothing has to take a lock, so a concurrent build
    # neither blocks nor blocks on it — the same bargain the CAS makes
    # everywhere else. The digest is the module's own source, so editing it
    # invalidates the path rather than leaving a stale library reachable
    # under a name that looks current.
    # `model.abi_module_name`, not a second `re.sub` of the same rule: the
    # prefix here is what the manifest keys every export by, and
    # `dylib_export_module` is what a caller writing `os.path.join` resolves
    # the qualifier through. Two copies of the substitution are two chances for
    # them to disagree, and the disagreement is a link error in the last image
    # built rather than in either of the two functions.
    prefix = _model.abi_module_name(module_identity)
    with open(source_path, "rb") as f:
        src_digest = cas.hash_parts(f.read())[:12]
    # …and the DEMAND DIGEST is in the name too, which is the same argument one
    # level over: two builds of one source that were asked for different
    # instantiations produce libraries with different exported symbols, so they
    # are two artifacts. Omitted entirely when there are no demands, so every
    # module that does not use a generic template keeps the path it had.
    dkey_part = f".{dkey}" if mine else ""
    out = os.path.join(out_dir,
                       f"{prefix}.{src_digest}{dkey_part}.{arch}.dylib")
    # The CONTAINER is `default_format(arch)`, not `fmt="macho"`. It used
    # to be hardcoded, which meant a Linux host built Mach-O module
    # libraries that no ELF loader can open: the module was compiled,
    # audited (its symbols are `provided`, so `_audit_bound_symbols`
    # passes) and then put NOWHERE, and the program died at load with an
    # unresolved symbol for a function its own source imports -- a
    # finding the symbol audit could not see, because the audit asks "does
    # something on this link line DECLARE this name" and the question that
    # mattered was "will the loader OPEN that library". Both emitters exist
    # now (`formal.macho_linker.build_macho_dylib` and
    # `formal.elf.build_elf_dylib`) and both are handed the same export
    # table, so the container is the host's and nothing else.
    # Serialise the write to this exact path.
    #
    # The digest above already separates two builds whose SOURCES differ, so
    # the only remaining collision is two builds of the SAME source onto one
    # path — and that is the common case, not a rare one: `-j18` over a bucket
    # where several jobs import the same stdlib module, or one
    # `make check-formal-sweep` beside another. Their content agrees, so
    # sharing is fine; writing it in place is not, because a reader can
    # observe the file part written.
    #
    # A lock, not a staging path with a rename. Renaming looked like the tidier
    # fix and is wrong here: a dylib's install name is derived from its output
    # path, and it is baked into the load command of everything that links it,
    # so a file built as `.../staging/foo.dylib` and moved afterwards no longer
    # matches the path its dependents were told to load. The lock leaves the
    # path — and therefore the identity — exactly as it was.
    with _dylib_lock(out):
        try:
            # The INSTANTIATIONS this module is asked for, as extra sources of
            # this same compile unit and under this module's OWN ABI prefix.
            #
            # Generated source rather than a new emitter path, and the reason is
            # that everything downstream already knows how to do this: the
            # export table (`reflect.collect_exports_src` now finds a CONCRETE
            # `Pair_Int` and its methods, where before it found only the excluded
            # template), `no_public_api_reason`'s gate (a module with an
            # instantiation has a boundary symbol, so the gate is not reached),
            # `model.abi_method_symbol`'s naming and `_method_exports` all read
            # an ordinary StructDef. A separate path for "monomorphized
            # definitions" would have had to agree with every one of those, and
            # the failure mode of disagreeing is a call that binds a symbol the
            # library never emitted — so it goes through them instead.
            extra_sources, extra_prefixes = _instantiated_sources(
                source_path, mine, prefix)
            result = compile_formal_dylib(
                [source_path] + [p for _t, _m, _a, p in extra_sources],
                output=out, prove=False, check=False,
                module_prefixes=dict(
                    {source_path: prefix}, **extra_prefixes),
                link_dylibs=dep_dylibs, arch=arch,
                fmt=default_format(arch),
                reexports=_qualified_reexports(
                    reexported_names(
                        stmts, {m: declared_kinds(p) for m, p in depends}),
                    module_identity))
        except (FormalBuildError, CodegenError) as e:
            raise ImportBuildError(f"{os.path.basename(source_path)}: {e}")
        # Record the dependencies in the manifest so a program can link them
        # without re-deriving this module's imports, each with the demands
        # digest IT was built with, because `dylib_chain` looks a dependency up
        # in `_BUILT` by (arch, path, digest) and a lookup that missed would
        # leave the library off the link line altogether — see that function's
        # own docstring for the measurement and for why the old claim that a
        # miss was harmless was false.  This module's OWN digest is recorded
        # beside them and read by whoever links against IT.
        _record_depends(
            _manifest_path(out),
            [(m, p, _manifest_instantiations(d)) for (m, p), d
             in zip(depends, dep_dylibs) if d],
            dkey)
    _BUILT[key] = out
    return out


def _instantiated_sources(source_path: str, wanted: dict, prefix: str) -> tuple:
    """`([(mangled, args, path), …], {path: prefix})` — the instantiated
    definitions `source_path` is asked to publish, written into the CAS.

    A demand that cannot be satisfied is DROPPED here rather than raised, and
    that is the design's whole error story rather than a shortcut: the two
    readers of a missing instantiation both have a better question to ask about
    it than this one does. `no_public_api_reason` can name the shape of the
    module that asked for it (and its generic branch now says what would make
    the symbol appear — an importer spelling the type argument), and
    `formal/build.py`'s bracketed-callee check can name the call. Raising here
    would report a demand's failure in place of both, which is the "a message
    that is false about the file" defect `bugs/FORMAL_known_limits.md` opens
    with — and it would do it on a module that HAS a concrete API and is
    refused for a specialization of one line of it.

    So a dropped demand lands the module exactly where it was before this
    existed: refused, or built without that symbol and refused at the CALL that
    wanted it. Neither is a silent wrong answer, because the mangled name a
    dropped demand would have published is the name the importer would have
    bound — so nothing can bind a body that was never emitted.
    """
    from formal import monomorph as MM            # lazy — pulls the middle tier
    if not wanted:
        return [], {}
    made, _failed = MM.instantiate_all(module_source_text(source_path), wanted)
    return made, {p: prefix for _t, _m, _a, p in made}


def imported_instantiations(source_path: str, stmts: list,
                            project_root: str = None,
                            linked_paths=()) -> dict:
    """`{mangled name: StructDef}` for every generic template this file
    instantiates out of a module it reaches — and REWRITES the call sites that
    asked, in `stmts`.

    **The declaration and the rewrite come from ONE table, and that is the whole
    design.**  An importer writes `Pair[Int]()`; the boundary symbol it has to
    bind is `prefix_Pair_Int___init__`, which is the symbol of a CONCRETE struct
    named `Pair_Int`.  So the call has to reach the emitter spelled as a struct
    this build has a declaration for, or it is a bracketed callee this unit does
    not compile and is refused (`formal/build.py`'s bracketed scan).  Computing
    the two separately would make it possible for the rewrite to name a struct
    the declaration list does not have — a call lowered to a constructor nothing
    declares — and for the declaration list to have a struct no call reaches,
    which is merely waste.  One table, produced once, is what makes the two
    agree by construction rather than by review.

    The rewrite is on the AST and not on the TEXT, so `Pair[Int]` inside a
    comment, a docstring or an MLIR literal is untouched: the parser has already
    thrown those away, and a textual rewrite would have had to re-implement the
    tokenizer's knowledge to avoid corrupting them.

    A demand whose template cannot be instantiated leaves both halves out
    together — no declaration and no rewrite — so the call site keeps its
    brackets and is refused by the bracketed scan with the sentence that is true
    of it (`formal/model.py::specialization_call_refusal`, or
    `imported_callee_refusal` where the export rule is the real reason).  That
    is the same "drop both or neither" rule `_instantiated_sources` follows on
    the exporting side, and the two halves of one feature refusing at the same
    demand for the same reason is the property that makes a partial failure
    diagnosable.

    `linked_paths` are libraries handed over with `--link-dylib`, which reach
    declarations no import statement names (`formal/build.py::_imported_structs`
    walks them for exactly this reason).  They are searched the same way, and a
    template is attributed to whichever module declares it first, which is the
    same precedence `_imported_structs` applies to the declarations themselves.
    """
    from formal import monomorph as MM            # lazy — pulls the middle tier
    consumer = module_source_text(source_path)
    if not consumer:
        return {}
    paths = []
    for mod in imported_modules(stmts):
        dep = resolve_module_path(mod, relative_to=source_path,
                                  project_root=project_root or source_path)
        if dep:
            paths.append(dep)
    paths.extend(linked_paths or ())
    if not paths:
        return {}
    demap: dict = {}
    out: dict = {}
    for dep in paths:
        for owner, wanted in instantiation_demands(
                dep, consumer, project_root=project_root or source_path).items():
            made, _failed = MM.instantiate_all(module_source_text(owner), wanted)
            for base, mangled, args, gen_path in made:
                demap.setdefault((base, args), mangled)
                if mangled in out:
                    continue
                # The census is attached from the INSTANTIATED module's own
                # statements, for `imported_struct_defs`'s reason: the evidence
                # is "what does this unit write into a field", so the unit that
                # has to answer is the one that declares the struct.
                for st in module_struct_defs(gen_path,
                                             project_root or source_path):
                    _attach_declared_census(st, gen_path)
                    out.setdefault(st.name, st)
    if demap:
        MM.rewrite_instantiation_calls(stmts, demap)
    return out


def _record_depends(manifest_path: str, depends: list,
                    instantiations: str = "") -> None:
    """Record this module's resolved imports in its own manifest, plus the
    demands digest its own library was built with.

    `instantiations` is `formal/monomorph.py::demands_key`'s answer for the
    instantiations of generic templates THIS library publishes, and each entry
    of `depends` is a `(module, source, instantiations)` triple carrying the same
    field for the DEPENDENCY — read out of that library's own manifest by
    `_manifest_instantiations` rather than recomputed, because `_BUILT` is keyed
    on it and a digest the reader had to recompute from source it may not have is
    a digest that can disagree with the build it is looking for.  `""` is a real
    value, not an absence — it is the digest of the empty demand set, and it is
    what every module that declares no generic template writes.

    Through `formal.build.update_dylib_manifest`, like every other manifest
    write, so the read-modify-write is atomic: this is the fourth of the four
    that used to truncate the file in place, and a program linking this dylib
    reads it with no lock at all — a reader in the truncation window gets
    `json.decoder.JSONDecodeError: … (char 0)`, which is not an `OSError`, so
    none of the `except OSError` around these reads catches it
    (40 % of concurrent reads of a real manifest landed in the truncation
    window, measured against the old code).
    """
    from formal.build import update_dylib_manifest

    def _record(payload):
        payload["depends_on"] = [
            {"module": m, "source": p, "instantiations": k}
            for m, p, k in depends]
        payload["instantiations"] = instantiations

    update_dylib_manifest(manifest_path, _record)


def _manifest_instantiations(dylib_path: str) -> str:
    """The demands digest `dylib_path`'s manifest records, or "".

    "" for a manifest that is missing, unreadable or written before the field
    existed, and every one of those is the same answer for a different reason: a
    digest nobody recorded is a digest nobody looked up by, so the fallback in
    `_built_lookup` is what has to carry it.
    """
    import json
    try:
        with open(_manifest_path(dylib_path)) as f:
            return json.load(f).get("instantiations") or ""
    except (OSError, ValueError):
        return ""


def dylib_chain(dylib_path: str, _seen=None) -> list:
    """`dylib_path` plus every dylib its module depends on, dependencies first.

    A dependency has to be on the link line before the module that needs it is
    bound, so the order is the post-order of the dependency graph. A cycle
    terminates because `_seen` stops the walk.

    The architecture is recovered from `dylib_path` (the `.N.dylib` suffix
    `build_module_dylib` writes) to look dependencies up in `_BUILT`, whose key
    is (arch, path, demands digest). Reading it back off the name rather than
    threading it through every call is safe because the name is the only thing
    that decides which library this is.

    **The DEMANDS DIGEST comes from the manifest, not from the name**, and the
    reason is that `_BUILT` is keyed on it and a lookup that missed would drop a
    dependency from the link line.  It did, measured: adding the digest to
    `_BUILT`'s key left this function's 2-tuple lookup finding nothing, so
    `main → pkg → pairlib` linked `pkg` alone and the image bound
    `Pair_Int_get_first` with nothing to bind it to.  Its docstring claimed the
    miss was harmless — "an omitted dependency, which is the same behaviour as a
    manifest with no `depends_on`, not a wrong one" — and that was false: a
    manifest with no `depends_on` describes a module that imports nothing, while
    this is a module that imports something and is being linked without it, which
    is the one thing the link line exists to prevent.  So the manifest now
    records the digest its build was made with, and a miss is a fallback rather
    than a silent omission (see `_built_lookup`)."""
    _seen = set() if _seen is None else _seen
    key = os.path.abspath(dylib_path)
    if key in _seen:
        return []
    _seen.add(key)
    arch = _arch_of_dylib(dylib_path)
    import json
    depends = []
    try:
        with open(_manifest_path(dylib_path)) as f:
            depends = json.load(f).get("depends_on") or []
    except OSError:
        depends = []
    out = []
    for dep in depends:
        # Each dependency carries ITS OWN demands digest, not this module's:
        # `_BUILT` is keyed on the digest of the module being looked up, and in
        # one recursion every level computes a different set from its own
        # source.  So the parent records what the child recorded, which is why
        # the field sits on the dependency's entry rather than beside them.
        dep_dylib = _built_lookup(arch, dep["source"],
                                  dep.get("instantiations") or "")
        if dep_dylib:
            out.extend(dylib_chain(dep_dylib, _seen))
    out.append(dylib_path)
    return out


def _built_lookup(arch: str, source: str, dkey: str = ""):
    """The dylib `_BUILT` holds for (arch, source) under `dkey`, or None.

    The exact key first, which is the normal case: the manifest of the library
    that names this dependency records the same demands digest its own
    dependency was built with, because the two are built in one recursion from
    one set.  Then a UNIQUE fallback, because a manifest written before the
    digest was recorded — or one whose build used a different demand set, which
    is possible when two programs share a CAS directory — must not silently lose
    a library from the link line.  With more than one candidate built for the
    same module, there is no answer here that is not a guess, so it returns None
    and the image's own symbol audit reports the dangling reference, which is a
    true statement about a link line that is missing a library.  The alternative
    — picking one — is the failure this whole function is arranged to avoid.
    """
    here = os.path.abspath(source)
    hit = _BUILT.get((arch, here, dkey))
    if hit is not None:
        return hit
    candidates = {v for (a, p, _k), v in _BUILT.items()
                  if a == arch and p == here}
    return candidates.pop() if len(candidates) == 1 else None


def _arch_of_dylib(dylib_path: str) -> str:
    """The architecture in a `<prefix>.<src-digest>.<arch>.dylib` name, or "".

    `rsplit(".", 1)` splits on the LAST dot, so the digest field in the middle
    needs no parsing of its own and this is unchanged by it.
    """
    base = os.path.basename(dylib_path)
    if base.endswith(".dylib"):
        parts = base[:-len(".dylib")].rsplit(".", 1)
        if len(parts) == 2:
            return parts[1]
    return ""


# ImportBuildError is defined in formal/build.py (a FormalBuildError subclass,
# so an unresolvable import reaches the user as "build: ..." and not a
# traceback) and re-exported here for callers that import it from either
# place.
