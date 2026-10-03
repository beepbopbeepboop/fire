# FORMAL_a_bare_c_call_returning_a_32_bit_int_is_compared_as_a_zero_extended_word

**A C library entry point that returns C's `int` arrives in this backend's
return register with its high 32 bits UNSPECIFIED, and every bound does not
know that, so `f(...) == -1` and `f(...) < 0` are FALSE for a `-1` the host
actually returned.** Measured on both architectures, 2026-10-03, on
`work/formal12-hostmods-subprocess` while writing `formal/hostmods/tempfile.mojo`.

Not a `formal/model.py` value-model premise and not a hostmod question: it is
the AArch64 and x86-64 C ABI's rule that the upper half of the return register
is unspecified for a 32-bit return, applied to a callee whose C signature this
path never learns.

## 1. What was run

```sh
export PATH=/opt/homebrew/bin:$PATH
cat > .tmp/tf/dbgD.mojo <<'EOF'
from os._syscalls import str_dup
def main() -> int:
    b = str_dup("/tmp/nodirXXXX/x")
    printf("direct=%d\n",  mkstemps(b, 0) == -1)
    printf("direct2=%d\n", mkstemps(b, 0) < 0)
    printf("direct3=%d\n", mkstemps(b, 0) == 4294967295)
    printf("direct4=%d\n", mkstemps(b, 0) != 0)
    printf("direct5=%d\n", mkstemps(b, 0) == 18446744073709551615)
    return 0
EOF
python3 tools/memslot.py --gb 8 --label tf -- \
  python3 fire.py build --formal --no-prove --backend=arm64 \
  -o .tmp/tf/dbgD.out .tmp/tf/dbgD.mojo && .tmp/tf/dbgD.out
```

```
direct=0          <-- WRONG.  mkstemps returned -1.
direct2=0         <-- WRONG.
direct3=1         <-- THE SMOKING GUN: the value IS 0x00000000FFFFFFFF.
direct4=1
direct5=0
```

The same program with `--backend=x86_64` prints the same five numbers, so it is
not an AArch64 artefact.

**`printf("%d", r)` prints `-1` while `r == -1` is false.** That is the whole
shape of it: the print path reads the low 32 bits and formats them signed; the
comparison path compares the whole 64-bit register, whose high half the callee
never wrote.

## 2. Which callees are affected, measured

Six int-returning libSystem calls, all on a path that does not exist, all
called bare (no `external_call[...]` declaration):

| callee | returns | `== -1` | `== 4294967295` |
|---|---|---|---|
| `mkstemps(p, 0)` | `int` | **0 — wrong** | **1** |
| `access(p, 2)` | `int` | 1 | 0 |
| `chmod(p, 511)` | `int` | 1 | 0 |
| `mkdir(p, 511)` | `int` | 1 | 0 |
| `truncate(p, 0)` | `int` | 1 | 0 |
| `unlink(p)` / `rmdir(p)` | `int` | 1 | 0 |
| `close(999)` | `int` | 1 | 0 |
| `mkdtemp(p)` | `char *` | — | `== 0` **1 — right** |

**So the exposure is per-CALL-SITE and not per-shape.** `mkstemps` is affected;
`access` with the identical signature (`char *`, `int` → `int`) is not. Both are
in libSystem; the difference is which of the two implementations of the arm64
system call sequence writes `W0` (which zero-extends) and which writes `X0`.
That is a property of the host library, which is exactly why it cannot be
predicted from the source: **the only sound answer is to normalise every bare
C call's return, not to enumerate the callees that happen to need it.**

## 3. Where the normalisation that already exists stops

`formal/arm64_codegen.py::_emit_extern_return` (and `x86_64_codegen.py`'s copy
of it) is the right mechanism and its docstring states the rule exactly:

> The ABI puts the low `bits` of a narrow integer return in X0 and leaves the
> rest unspecified, and a W-register write zero-extends on AArch64 […] So this is
> the conversion, not tidying.

**It runs only for a call the SOURCE declares** — `external_call["sym", T]`,
through `formal/model.py::external_call_return_kind` and `EXTERN_RETURN_INTS`.
A BARE call, which is how every `formal/hostmods/os/_syscalls.mojo` wrapper
reaches libSystem (`return mkdir(p, mode)`), has no declared type, so
`ext_return` is `None` and `_emit_extern_return` returns immediately. That is the
gap: the same word, from the same register, with no normalisation, whenever the
caller did not spell a type.

## 4. The exact next step

**Normalise the return of every BARE C call, in both emitters, and measure it.**

The candidate instruction is `sxtw x0, w0` (arm64) / `movslq %eax, %rax`
(x86-64), and it is correct for every value this target actually produces:

* a C `int` / `short` / `char` — the case that is broken now;
* a **pointer**, because no macOS user-space address has bit 31 set (user space
  is below `0x0000_8000_0000_0000`) and `NULL` sign-extends to `0`, which is
  what `getcwd(b, n) == 0` in `fs_cwd` and `mkdtemp(b) == 0` already rely on;
* a 64-bit integer whose value fits in 32 bits — unchanged.

The risk is a 64-bit integer return with bit 31 set, and it is a real one, so
the fix is not "sign-extend everything": the narrow instruction belongs where
the C `int` return is, which is the whole of §3's gap. A callee-by-callee
`EXTERN_RETURN_INTS` entry for the handful of libSystem names a hostmod calls
would be the conservative version and is what §2 argues against.

Whatever the shape, the test has to pin the ANSWER and not the instruction:

```sh
cat > .tmp/tf/ret32.mojo <<'EOF'
def main() -> int:
    r = truncate("/tmp/nodirXXXX/z", 0)
    printf("v=%d eqm1=%d lt0=%d eq32=%d\n", r, r == -1, r < 0, r == 4294967295)
    return 0
EOF
```

on both backends, plus the `mkstemps` row of §2 — which is the one that
currently fails and the one that must stop failing.

## 5. What is blocked on it, and what is not

**`formal/hostmods/tempfile.mojo`'s `mkstemp` is not written because of this.**
`mkdtemp(3)` returns `char *`, so `== 0` is sound and `mkdtemp` ships;
`mkstemps(3)` returns `int`, so its only failure check (`< 0`) is the one
comparison this bug makes false, and writing it anyway would put a known-wrong
runtime check into a module 111 sweep files are refused on. `mkstemp` is three
call sites (`test_import_integration.py`, `test_formal_sweep.py`, `py314_harness.py`)
and it is absent from the model with this doc as the reason — which is the
absence `bugs/` exists to record, rather than a silent `""` for a call that
failed.

`mkdtemp`'s own name is a second, narrower question the same measurement raises
and this doc does not claim to have answered: `mkdtemp(3)` substitutes the last
six bytes and nothing else, so `prefix + "XXXXXX" + suffix` is taken LITERALLY
when a suffix follows it (measured through libc on this host:
`mkstemp("/tmp/xXXXXXX.txt")` creates `/tmp/xXXXXXX.txt` and leaves the template
alone). `mkstemps(3)` is the entry point that takes a suffix length and
substitutes the six bytes before it, so `mkdtemp` with a suffix needs
`mkstemps(b, len(suffix))` too — and `mkstemps` is exactly the callee §2 shows
is mis-compared. **`tempfile.mkdtemp(suffix=…)` is therefore correct only for
the empty suffix, and `test_formal_tempfile.py` pins that** rather than leaving
it to be discovered by a file that passes one.