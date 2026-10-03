# FORMAL_libc_call_whose_name_starts_with_an_underscore: two places eat the first character of a C identifier that legitimately begins with `_`

**Status 2026-10-03 (`work/formal13-4`): BOTH FIXES LANDED, and the blocker §3 names
is GONE — there was a second, harmless C function to verify them against.**

§3 filed this rather than fixing it because the only C function on this target
that reaches either site is `_NSGetExecutablePath`, and it faults inside libSystem
(four ways, including from CPython), so "landing a change to
`formal/macho_linker.py` on the strength of a call that crashes would be exactly
the 'a verification whose verifier never ran' failure". The escape from that is
that the population is not one function: **`_exit` is also there**, it is in
libSystem, and it is harmless — so the two one-line fixes could be measured
end to end on both architectures, with an observable that is not a crash.

## What `_exit` measures, and why it is the right instrument

`_exit(3)` and `exit(3)` differ in exactly one observable: POSIX `_exit`
terminates **without flushing open streams**. stdout is a pipe under the test
harness, so it is block-buffered and the flush is the only thing that can put
buffered text out. That is a differential against the C library itself, on a
function that cannot fault:

```python
def bail(status: Int) -> Int:
    _ = external_call["_exit", Int32](Int32(status))
    return 0

def main(n: Int) -> Int:
    printf("flushed")
    return bail(3)
```

| | exit status | stdout |
|---|---|---|
| before, arm64 and x86-64 | 3 | `flushed` — **`exit` ran** |
| after, arm64 and x86-64 | 3 | *(nothing)* — **`_exit` ran** |

Before the fix both ends of the pipeline ate the underscore, and the two mistakes
composed into a false pass: `formal/model.py::libc_source_name` asked `dlsym`
about `exit`, which libSystem has, so the audit was satisfied; and
`formal/macho_linker.py::_bind_info` dropped one leading underscore before
writing the name dyld looks up, so the loader bound `exit` too. A program that
asked to die without flushing flushed. Pinned by
`test_formal_external_call.py`'s `c_identifier_beginning_with_an_underscore_binds_that_function`,
whose expectation is the empty stdout, and by four new rows in
`test_formal_link_accounting.py::test_libsystem_provider` — including the
anti-rot one, that `NSGetExecutablePath` (no leading underscore) is still NOT in
libSystem, so the fix is not a blanket accept.

**`_is_libsystem('_printf')` is now False, and that assertion moved.** The old row
said "the Mach-O spelling (leading underscore) is handled", which was true of the
defect: a Mach-O spelling is not what reaches this function. It is the inverse of
`model.target_libc_symbol`, so it is asked what the SOURCE spelled, and `_printf`
as a source spelling is a C function libSystem does not export. A Mach-O spelling
that really does arrive — a linked module's export — is accounted for earlier, by
`_audit_bound_symbols`' `provided` set against the manifest, which
`test_bind_audit`'s `_pkg_helper` row already pinned. Measured, so this is not a
hypothesis: a program calling `os.path.join` binds
`['os_path_join_2dbb98', 'printf']`, neither of them underscore-prefixed.

**`test_formal_libc_symbol.py`'s table asserted the defect in three of its seven
rows** (`_readdir` → `readdir`, `_printf` → `printf`,
`_os_syscalls_readdir_9f63a2` → `os_syscalls_readdir_9f63a2`) and now asserts the
corrected answers, with the `$INODE64` rows — the only case the strip exists for —
unchanged.

**§4's checks, run:** `test_formal_link_accounting.py` 235/235,
`test_formal_libc_symbol.py` 7/7 (`binding` and the table green on both
architectures; `dirent`/`stat` on arm64 are killed with SIGKILL about half the time
and are equally flaky with both fixes reverted — three baseline runs gave 5/7, 6/7,
5/7, so it is this machine's memory pressure and not this change),
`test_formal_runtime_link.py` 133/133 (it reads the bind stream),
`test_formal_external_call.py` 46/46, `test_formal_dylib.py` 19/19,
`test_formal_os.py` 5/5, `test_re_formal.py` 1188/1188, `test_formal_stat.py` 4/4,
`test_formal_hashlib.py`, `test_formal_fcntl.py`, `test_formal_small_hosts.py` — all
green.

**§3's population count is corrected by the same measurement:** of the candidates
probed by `dlsym` against `/usr/lib/libSystem.B.dylib` on this host, six are
present — `_exit`, `_setjmp`, `_longjmp`, `__error`, `_NSGetExecutablePath`,
`__sysctlbyname` — and `_exit` is the first of them that is both harmless to call
and expressible in this value model (one `Int` in, no result used).
`_NSGetExecutablePath` remains unusable end to end, and that no longer matters:
it is no longer the only instrument.

**Status (original, 2026-10-02): OPEN, latent, pre-existing, NOT FIXED — and
deliberately not fixed here, for a reason that is in §3 and is not "it was
hard".** Found 2026-10-02
while answering `platform()` (`bugs/FORMAL_platform_one_call_from_answered.md`,
now fixed), whose `_NSGetExecutablePath` call is the one function on this target
that would have reached either of these.

Two one-line defects, in two files, with the same shape: a C identifier may
begin with an underscore, and both places assume it may not.

## 1. What was run, and what it saw

`formal/model.py`'s `libc_source_name` is asked, by
`formal/build.py::_is_libsystem`, whether the C library provides an extern. It
opens by stripping leading underscores:

```python
bare = symbol.lstrip("_")          # formal/model.py, `libc_source_name`
```

and then `dlsym`s the result. libSystem's running-image-path function is spelled
`_NSGetExecutablePath`, and the leading underscore is part of the NAME. So:

```python
>>> import formal.build as B
>>> B._is_libsystem('_NSGetExecutablePath')
False            # it asked dlsym about `NSGetExecutablePath`
```

and a program that calls it is refused at build time:

```
$ python3 fire.py build --formal --no-prove -o .tmp/plat/probe .tmp/plat/probe.mojo
build: probe.mojo: the image would bind 1 symbol(s) that nothing provides, so it
  could not be loaded: _NSGetExecutablePath. … (Provider check: asked the C
  library (dlsym).)
```

The diagnostic blames the LINK LINE and names the symbol libSystem does export,
which is the wrong half of the story twice over: the cause is in the audit, and
the spelling in the message is the one the assembler produces for a C name that
has no leading underscore.

**The second place is the mirror image, and it is only reachable once the first
is past.** `formal/macho_linker.py:468`, in `_bind_info`, normalised the classic
bind stream the same way:

```python
out += (sym[1:] if sym.startswith("_") else sym).encode()
```

The paragraph immediately above it says the opposite — "The stream carries the
bare C name; dyld prepends the Mach-O underscore when it forms the symbol it
looks up … `"printf"` binds … while `"_printf"` gets `Symbol not found:
__printf`" — so the expression contradicts the measurement recorded next to it.
With the audit's `lstrip` removed by hand, the image now LINKS and then dies in
the loader, which is the second measurement and the one that localises this:

```
$ ./.tmp/plat/probe
dyld[68011]: Symbol not found: _NSGetExecutablePath
  Referenced from: … .tmp/plat/probe
  Expected in:     … /usr/lib/libSystem.B.dylib
```

Verified against the system, so the name is not a guess:

```
$ nm -u .tmp/plat/e | grep -i exec     # a C program declaring
__NSGetExecutablePath                   #   extern int _NSGetExecutablePath(char*, unsigned int);
$ python3 -c "import ctypes; print(hasattr(ctypes.CDLL('/usr/lib/libSystem.B.dylib'), '_NSGetExecutablePath'))"
True                                    # dlsym is happy …
$ …  hasattr(…, '__NSGetExecutablePath')
False                                   # … and dyld is not
```

The `dlsym`/`dyld` disagreement is the whole hazard: the shared cache answers
`dlsym` for `_NSGetExecutablePath`, and the loader does not, so an audit that
asks `dlsym` about a name the loader would reject is exactly the check that
cannot catch this.

## 2. The two fixes, as measurements

Neither was landed when this was written; both were one line, and both are stated
as text so whoever takes this can apply them without re-deriving anything. Both
landed on 2026-10-03 — the second with `libc_source_name` rather than a literal
strip, which is the same decision asked in the model's own terms.

**`formal/model.py::libc_source_name`** — strip the assembler's underscore only
when there is a `$INODE64` to remove after it, which is the only case the strip
exists for (`_readdir$INODE64` → `readdir`):

```python
    bare = symbol
    if bare.startswith("_") and bare.endswith(INODE64_SUFFIX):
        bare = bare[1:]
    if bare.endswith(INODE64_SUFFIX):
        return bare[:-len(INODE64_SUFFIX)]
    return bare
```

Verified against both directions before being reverted:
`readdir$INODE64` → `readdir`, `_readdir$INODE64` → `readdir`,
`_NSGetExecutablePath` → itself, and `_is_libsystem` then answers `True` for
`_NSGetExecutablePath`, `getcwd`, `readdir$INODE64`, `strstr`, `_exit`, `exit`.

**`formal/macho_linker.py::_bind_info`** — write the name the codegen handed
over, because that is the C name and dyld prepends the underscore:

```python
    out += sym.encode()
```

The `_export_trie` normaliser twelve hundred lines below has the same shape and
the same reasoning error (`export["symbol"] if … startswith("_") else "_" + …`),
but it is unreachable for this: a leading-underscore name in an export map is a
`def _foo`, and `reflect.export_exclusions` denies every one of those
(`test_formal_platform.py`'s `exports` group asserts it for all seventeen host
modules).

## 3. Why this was filed rather than fixed, which is a real answer (superseded —
## the blocker was one function, and there was a second)

**The one C function on this target that a formal program could reach this way
faults inside libSystem**, so neither fix can be verified end to end here:

```
$ cc -O0 -o .tmp/plat/e .tmp/plat/e.c && ./.tmp/plat/e          # SIGSEGV
$ cc -O1 -o .tmp/plat/e1 .tmp/plat/e.c && ./.tmp/plat/e1       # SIGSEGV
$ cc -O1 -o .tmp/plat/e2 .tmp/plat/e2.c && ./.tmp/plat/e2       # SIGSEGV, static 64 KiB buffer
$ python3 -c "… ctypes … _NSGetExecutablePath(buf, 65536)"     # SIGSEGV, from CPython
```

Four ways, including one that is not this compiler at all. And the population is
almost empty: of a dozen plausible candidates, `dlsym` on libSystem says
`_strlcpy`, `_strlcat`, `_memcpy`, `_memset`, `_strlen`, `_index`, `_rindex`,
`_ffs`, `_bzero`, `_bcopy`, `_stat`, `_lstat`, `_sigaction`, `_posix_spawn` are
all **absent**, and the two that exist (`_setjmp`, `__sysctlbyname`) are not
expressions a formal value model can use.

So landing a change to `formal/macho_linker.py` — the file every Mach-O image in
the tree goes through — on the strength of a call that crashes would be exactly
the "a verification whose verifier never ran" failure
`bugs/FORMAL_per_export_contracts.md` §"The retraction" is written about. The
fixes are recorded, the measurements that pin them are recorded, and the blocker
is named. `platform`'s own decision does not depend on either: its
`_NSGetExecutablePath` call FAULTS on this host (that same SIGSEGV, four ways),
so `platform(exe, aliased, terse)` takes the executable path as a PARAMETER —
which is the doc's decision #2, reached by measurement rather than by
preference. Both that and the `glob`/`fnmatch` accounting stay open in
`bugs/FORMAL_platform_reachable_row_measured.md`.

## 4. What a taker should check

1. `python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_link_accounting.py`
   (170 checks) and `test_formal_runtime_link.py` — the bind stream is what both
   of those read, and the change is in it.
2. `test_formal_platform.py`, because its `exports`/`architecture` groups are the
   ones that build images with a non-trivial extern set.
3. Whether a `_`-leading libc call is reachable on the TARGET rather than on this
   host. On macOS it is not (measured above), which is why this is latent here
   and might not be on a Linux/ELF image — where `formal/build.py`'s ELF path has
   its own symbol spelling and `libc_source_name` is not consulted.