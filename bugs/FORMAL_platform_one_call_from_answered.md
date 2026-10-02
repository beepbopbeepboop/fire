# FORMAL_platform_one_call_from_answered: `platform()` is one composition away, and two of its pieces are not ours

**Status: OPEN, filed 2026-10-01 by the `construct:x86-byte-read-and-platform`
claim, which wrote `platform.architecture` and the `read(2)` it needed. Not a
defect: every piece below answers today, and this doc is the exact next step for
the one that does not.**

## What is left, and why it is not just a string join

CPython's `platform(aliased=False, terse=False)` on macOS, after `uname()`:

```python
    system, node, release, version, machine, processor = uname()
    if machine == processor:
        processor = ''
    if aliased:
        system, release, version = system_alias(system, release, version)
    if system == 'Darwin':
        macos_release = mac_ver()[0]
        if macos_release:
            system = 'macOS'
            release = macos_release
    ...
    else:                                   # the generic handler, which macOS takes
        if terse:
            platform = _platform(system, release)
        else:
            bits, linkage = architecture(sys.executable)
            platform = _platform(system, release, machine, processor, bits, linkage)
```

Four pieces, and three of them are already functions in
`formal/hostmods/platform.mojo`:

| CPython | here | state |
|---|---|---|
| `uname()` | `system()` / `release()` / `machine()` / `uname_processor()` | present |
| `mac_ver()[0]` | `mac_ver_release()` | present |
| `system_alias()` | `system_alias_system()` / `_release()` / `_version()` | present |
| `architecture(sys.executable)` | `architecture_bits()` / `architecture_linkage()` | present, but they need a PATH |
| `_platform(*parts)` | — | not written |
| `sys.executable` | — | not available |

## The two things to decide, in order

### 1. `sys.executable`: `_NSGetExecutablePath`, or a parameter?

`architecture` is called with no argument, so `platform()` must supply a path,
and this image has no `sys.executable` — `formal/hostmods/sys.mojo` documents
`sys.argv`, `sys.path` and the stream objects as the one missing capability, and
an executable's own path is the same capability (there is no `argv[0]`).

libSystem answers it: `_NSGetExecutablePath(buf, bufsize)` writes the running
image's path into a buffer and returns 0 or -1, and it is an ordinary extern on
this path — the same shape as `fs_getcwd`, which `os/_syscalls.mojo` already
wraps. So the choice is:

* **wrap it** (`fs_exe_path()` in `_syscalls.mojo`, beside `fs_getcwd`), and
  `platform()` becomes the faithful composition; or
* **give `platform` a parameter** — but a default argument is not applied across
  a dylib boundary (`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`),
  so that means `platform_for(path)`, `platform_terse()` and
  `platform_aliased()` as three names, which is a different API from CPython's.

The first is the honest one and it is small. **Not measured yet**: whether the
x86-64 image under Rosetta gets the same path CPython's `sys.executable` reports
for the arm64 process (it should — it is the path of the image being run, which
differs between the two builds anyway, and that difference is the same fact
`platform.machine()` already reports per image).

### 2. `_platform(*parts)`: the cleanup is most of the function

```python
def _platform(*args):
    platform = '-'.join(x.strip() for x in filter(len, args))
    platform = platform.replace(' ', '_').replace('/', '-') ...
    platform = platform.replace('unknown', '')
    while True:                       # fold '--'
        cleaned = platform.replace('--', '-')
        if cleaned == platform: break
        platform = cleaned
    while platform and platform[-1] == '-':
        platform = platform[:-1]
    return platform
```

Eleven steps, and on macOS only two of them can ever fire: `mac_ver_release()`
is `26.6.2`, `machine()` is `arm64`, `architecture`'s answers are `64bit` and
`Mach-O`, and none of those six parts contains a space, a slash, a colon or the
word `unknown`. Which means a transcription that implements only the join would
be **indistinguishable from a correct one on this platform** — and would be
wrong the moment a node name or a release string carried one.

So the two steps to get right are the ones that are not exercised here:

* `x.strip()` PER PART, before the join — CPython strips each part, so a part
  with trailing whitespace does not produce a doubled `-`;
* `replace('unknown', '')` — EVERY occurrence, anywhere, including inside a
  word, which is why it is a substring replace rather than a test for the word.

The `--` fold and the trailing-`-` strip only matter if two adjacent parts are
empty or a part ends in `-`, and `filter(len)` already drops empty parts, so the
fold is reachable only through a part that ENDS in `-` (e.g. a release string
`"5-"`). A `str_replace_all(s, from, to)` helper is the one piece of machinery
this needs, and it is the same helper `bugs/FORMAL_fnmatch_translate_absent.md`'s
§2 describes for a different caller — worth writing once.

### The expected answers, so the next person can check without reading CPython

Measured on this host (`sw_vers` 26.6.2, Darwin 25.6.0, arm64):

    platform()              'macOS-26.6.2-arm64-arm-64bit-Mach-O'
    platform(terse=True)    'macOS-26.6.2'
    platform(aliased=True)  'macOS-26.6.2-arm64-arm-64bit-Mach-O'   (same)
    platform._platform('macOS', '26.6.2', 'arm64', '', '64bit', 'Mach-O')
                            'macOS-26.6.2-arm64-64bit-Mach-O'

**The last line is the one this module can produce and the first three are not,
and the difference is `processor` and nothing else.** CPython's `uname()` on
macOS resolves `processor` by running `uname -p`, which answers `arm` here; this
path has no subprocess, so `uname_processor()` answers `""` — which is CPython's
OWN spelling of "cannot be determined" (`_unknown_as_blank`), already pinned by
`test_formal_platform.py`'s `processor` group. So the oracle for `platform()` is

    platform._platform(system, mac_ver_release(), machine(), "", bits, linkage)

built from this module's own functions, and NOT
`platform.platform()`, which would differ by exactly the `arm` that no subprocess
can produce. A test that compared against `platform.platform()` would be testing
`uname -p`, not `platform()`.

### What to test when it is written

`test_formal_platform.py` has the harness: a `platform_default` /
`platform_terse` / `platform_aliased` group, each building an image that prints
the string and comparing it with `platform._platform(...)` over the pieces above.
`absent` loses `platform` from its list at the same moment, which is what keeps
the omission pinned as a refusal rather than read as an implementation.

## The sweep number for this, measured rather than quoted

`bugs/FORMAL_platform_reachable_row_measured.md` §2 measured the thirty files
that stopped on `platform` and found all thirty land on a PERMANENT fact
(`subprocess` x28, `shutil` x2) — the row's ceiling is 0 and `platform()` does
not change it. Nothing in this doc is about moving files; it is about one CPython
function being answerable where it currently is not.