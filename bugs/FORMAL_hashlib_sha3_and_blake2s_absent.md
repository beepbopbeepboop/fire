# FORMAL_hashlib_sha3_and_blake2s_absent: seven of CPython's fourteen guaranteed algorithms are missing, and each would be a from-scratch implementation

**Status: OPEN, and a scoping decision rather than a defect. It is the reason
`blake2s`, `sha3_224`, `sha3_256`, `sha3_384`, `sha3_512`, `shake_128` and
`shake_256` are ABSENT from `formal/hostmods/hashlib.mojo` rather than
approximated, and `test_formal_hashlib.py`'s `absent` group asserts each one
is refused with a message naming itself.** Found while writing `hashlib`
(2026-09-29, the `module:hashlib` claim). Nothing here is a backend defect;
the next step is a decision about how much specification-checking a module
should carry.

---

## What I ran

Asked of libSystem, which is what a formal image links and nothing else:

```console
$ python3 - <<'PY'
import ctypes
lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
for n in ["CC_MD5","CC_SHA1","CC_SHA224","CC_SHA256","CC_SHA384","CC_SHA512",
          "CC_SHA3_224","CC_SHA3_256","CC_SHA3_384","CC_SHA3_512",
          "CC_SHAKE128","CC_SHAKE256","blake2b_init","CC_blake2b","_blake2b_init"]:
    try: getattr(lib, n); print("YES", n)
    except AttributeError: print("no ", n)
PY
YES CC_MD5
YES CC_SHA1
YES CC_SHA224
YES CC_SHA256
YES CC_SHA384
YES CC_SHA512
no  CC_SHA3_224
no  CC_SHA3_256
no  CC_SHA3_384
no  CC_SHA3_512
no  CC_SHAKE128
no  CC_SHAKE256
no  blake2b_init
no  CC_blake2b
no  _blake2b_init
```

**Six of the fourteen, and no SHA-3, no SHAKE and no BLAKE2 in any spelling.**

## What that costs, measured against CPython

```console
$ python3 -c "import hashlib; print(sorted(hashlib.algorithms_guaranteed))"
['blake2b', 'blake2s', 'md5', 'sha1', 'sha224', 'sha256', 'sha384',
 'sha3_224', 'sha3_256', 'sha3_384', 'sha3_512', 'sha512',
 'shake_128', 'shake_256']
```

So this module covers **6 of 14 guaranteed** (md5, sha1, sha224, sha256,
sha384, sha512) plus blake2b, which is computed here because one real caller
wants it. That is 7 of 14, and the 7 missing are all in two families:

| family | names | what implementing it needs |
|---|---|---|
| SHA-3 / Keccak | `sha3_224`, `sha3_256`, `sha3_384`, `sha3_512` | FIPS 202, and the sponge construction on top of it |
| SHAKE | `shake_128`, `shake_256` | FIPS 202 **plus an extendable output** |
| BLAKE2s | `blake2s` | RFC 7693 §3, a different word width and round count from the `b` variant already here |

## Why they are absent rather than approximate

**SHAKE is the one that is genuinely out of reach, and it is out of reach for
a reason that is not about the algorithm.** `shake_128(digest_size=n)` returns
`n` bytes for an `n` the CALLER chooses, so it is a run-time-length sequence —
and a run-time-length sequence is exactly what this path cannot build: a
list's capacity is the number of `append` SITES in the function that builds it
(`bugs/FORMAL_listdir_no_run_time_sequence.md`, measured). A SHAKE with a
compile-time-known output length would be implementable; a SHAKE API would
not, and an API that silently truncated to whatever the call sites happened to
add is worse than an absent one.

**SHA-3 and BLAKE2s are a cost judgement, and the judgement is arguable.**
BLAKE2s is the closest call: it is RFC 7693, this file already has the G
function, the sigma table and the parameter block, and the differences are a
32-bit word width, 10 rounds instead of 12, and a different IV. It is
probably half a day. It is absent because **nobody in this tree calls it**,
and writing an unrequested second digest is how a module stops being a mirror
of something and starts being an implementation of somebody's preferences.

SHA-3 is further away: Keccak-f[1600] is a different shape of computation
from anything here, and it would be the module's largest piece of arithmetic
written with no caller to check it against except CPython.

## What I expect

A decision, recorded, about how far a host module goes past its callers. The
two defensible answers:

1. **Caller-driven** (what this module does). Write what the tree uses, check
   it against CPython, and name the rest. `py314_cache.py` needs blake2b, so
   blake2b exists; nothing needs blake2s, so it does not. The cost is that
   `algorithms_guaranteed` cannot be implemented, and the module says so.
2. **Spec-driven.** Implement everything CPython guarantees, so the module is a
   complete mirror and a program ported from CPython runs unchanged. The cost
   is real: FIPS 202 and RFC 7693 §3 from scratch, with no caller, checked
   only against CPython — and the two families that break the value model
   (SHAKE) still cannot be done at all, so even (2) is 13 of 14.

Either is coherent. What is not coherent is a module that implements some of
the absent ones for aesthetic reasons and leaves the rest, because then the
set is nobody's decision.

## The exact next step

1. **Ask who needs what, before writing anything.** The cheapest version of
   this question is a sweep: `grep -rn "sha3_\|blake2s\|shake_" --include=*.py
   --include=*.mojo .` over the tree. If the answer is nobody, (1) stands and
   this document is the record. If something needs one, that something is the
   specification of record and the work is scoped by it.

2. **If blake2s is wanted, it is cheap and should reuse what is here.** The
   pieces that carry over are `b2_g`'s structure, `sigma_table` (the same ten
   rows — BLAKE2s uses the same permutation) and the parameter block. What
   does NOT carry over is the word width: 32-bit words throughout, a
   64-byte block of 16 words instead of 128, 10 rounds instead of 12, and a
   different IV. On this path that also means the arithmetic moves to 32-bit
   words, which is a different masking discipline and is where a transcription
   goes wrong — so "half a day" is optimistic and the test has to be as
   thorough as the BLAKE2b one is now (1,128 cases, every length 0..139,
   checked byte for byte).

3. **Do not implement SHAKE, on this target, in any spelling.** Not as a bug
   to be fixed later: the run-time-length sequence is a property of the value
   model and closing it is Phase 6 work (a real allocator), which is
   `bugs/CODEGEN_bootstrap_resource_blowup.md`'s neighbourhood. If a SHAKE is
   ever needed, the honest answer on this target is a fixed-length output with
   the length in the function's name, and that is a decision to make when
   someone needs it rather than now.

4. **A test for whatever gets added**, in `test_formal_hashlib.py`'s existing
   shape: the digest compared with CPython's, over the same input set the
   BLAKE2b group uses. The group is already parameterised enough that a new
   algorithm is a new entry in a table and a new length list, not a new file.
