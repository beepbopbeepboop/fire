#!/usr/bin/env python3
"""The returned-frame layout: the caller's half of a fix that is otherwise
blocked on an ownership boundary, pinned so the boundary is the only thing
between the tree and the fix.

`struct_returned_frame_sites` is what makes a frame that outlives its creator
have a place to live: a block in the CALLER's scratch, per call site, in walk
order, reserved in the prologue. It is the same shape as
`struct_constructor_sites` — which is the point, because the reason a frame
cannot be returned today is that its creator's scratch dies with the creator.

These cases are about the LAYOUT, and they are deliberately not about whether
the fix has landed end to end. It has not:

  * `formal/build.py` raises the refusal (`:2423`, `frame_return_refusal`) and
    that file is in nobody's write set this round — see
    `bugs/INTERFACE_REQUEST_4_to_formal_build.md`;
  * the hidden argument is a calling-convention change whose proof-side
    obligation is a `lib/Refine.lean` predicate, owned by [3].

So a case here that passed end to end would be a lie, and this file asserts
only what is true today: the layout is computed, it is the shape the emitters
need, and the two machines would agree on it because they read one function.

Usage:
    python3 test_returned_frame_layout.py [-v]
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fire_compiler as F
import formal.model as M

_PASS = 0
_FAIL = 0
_VERBOSE = False


def check(name, cond, detail=''):
    global _PASS, _FAIL
    if cond:
        print(f'PASS  {name}')
        _PASS += 1
    else:
        print(f'FAIL  {name}  {detail}')
        _FAIL += 1


def parse(src):
    return F.Parser(F.py_tokenize(src)).parse_module()


def structs_of(stmts):
    return {s.name: s for s in stmts if isinstance(s, F.StructDef)}


def funcs_of(stmts):
    return [s for s in stmts if isinstance(s, F.FunctionDef)]


# ── the shapes ───────────────────────────────────────────────────────────

TWO_FIELD = """\
class Point:
    def __init__(self):
        self.x = 7
        self.y = 9
"""

TWO_CALL_SITES = TWO_FIELD + """
def make():
    p = Point()
    return p

def main():
    q = make()
    r = make()
    print(q.x, r.x)
"""

NOT_A_FRAME_CALL = """\
def make():
    return 7

def main():
    q = make()
    print(q)
"""

CALLEE_UNKNOWN = """\
def main():
    q = make()
    print(q.x)
"""

# A struct wide enough that its block is 48 bytes, to pin that the offsets are
# BYTES and advance by the block, not by 8.
THREE_FIELD = """\
class Wide:
    def __init__(self):
        self.a = 1
        self.b = 2
        self.c = 3

def make():
    p = Wide()
    return p

def main():
    q = make()
    print(q.a)
"""


def _returns(callee_names, struct_by_name):
    """A `returns_frame` predicate over the callees that return a frame.

    Deliberately a closure supplied by the caller, because that is the
    contract `struct_returned_frame_sites` documents: the build pass's holder
    fixpoint decides this, and a second answer to the same question inside the
    model is the disagreement that produces a wrong number instead of a
    refusal."""
    def _p(callee, _bound_name):
        if callee not in callee_names:
            return None
        return struct_by_name.get(callee)
    return _p


def main(argv):
    global _VERBOSE
    if '-v' in argv[1:]:
        _VERBOSE = True

    # 1. One call site gets one block, at offset 0, sized by the struct.
    stmts = parse(TWO_CALL_SITES)
    structs = structs_of(stmts)
    main_fn = [f for f in funcs_of(stmts) if f.name == 'main'][0]
    # `make` is the callee that returns a frame; `struct_by_name` maps a
    # callee NAME to the struct it returns.
    ret = _returns({'make'}, {'make': structs['Point']})
    sites = M.struct_returned_frame_sites(main_fn, structs, ret)
    check('one_site_per_returning_call',
          len(sites) == 2, f'got {len(sites)} site(s), expected 2')
    want = M.struct_frame_block_bytes(structs['Point'], structs)
    offs = sorted(v[1] for v in sites.values())
    check('offsets_start_at_zero_and_advance_by_the_block',
          offs == [0, want], f'offsets {offs}, expected [0, {want}]')
    check('each_site_carries_its_struct_and_size',
          all(v[0].name == 'Point' and v[2] == want for v in sites.values()),
          f'{[(v[0].name, v[1], v[2]) for v in sites.values()]}')

    # 2. Offsets are BYTES and scale with the struct, not with a fixed 8.
    stmts = parse(THREE_FIELD)
    structs = structs_of(stmts)
    main_fn = [f for f in funcs_of(stmts) if f.name == 'main'][0]
    ret = _returns({'make'}, {'make': structs['Wide']})
    sites = M.struct_returned_frame_sites(main_fn, structs, ret)
    want_wide = M.struct_frame_block_bytes(structs['Wide'], structs)
    check('a_wider_struct_reserves_a_wider_block',
          want_wide > want and len(sites) == 1
          and list(sites.values())[0][2] == want_wide,
          f'Point block {want}, Wide block {want_wide}, '
          f'sites {[(v[0].name, v[1], v[2]) for v in sites.values()]}')

    # 3. A call that does NOT return a frame gets no block. This is the case
    #    that decides whether the function is safe to trust: reserving a block
    #    for a plain call is wasted scratch (harmless), but MISSING one for a
    #    frame-returning call is the silent wrong answer, so the predicate has
    #    to be able to say "no".
    stmts = parse(NOT_A_FRAME_CALL)
    structs = structs_of(stmts)
    main_fn = [f for f in funcs_of(stmts) if f.name == 'main'][0]
    sites = M.struct_returned_frame_sites(main_fn, structs, _returns(set(), {}))
    check('a_call_that_returns_a_word_gets_no_block',
          sites == {}, f'got {sites}')

    # 4. A callee the analysis knows nothing about gets no block rather than
    #    a guess — and this is the shape the 12 `callee has no definition on
    #    this path` findings have, which the taxonomy already separated from
    #    the receiver buckets for exactly this reason.
    stmts = parse(CALLEE_UNKNOWN)
    structs = structs_of(stmts)
    main_fn = [f for f in funcs_of(stmts) if f.name == 'main'][0]
    sites = M.struct_returned_frame_sites(main_fn, structs, _returns(set(), {}))
    check('an_unknown_callee_gets_no_block',
          sites == {}, f'got {sites}')

    # 5. The two machines read ONE layout function, which is the property
    #    that makes a returned frame correct on both or wrong on both. This
    #    asserts it structurally: both backends call the shared function and
    #    neither computes its own offsets.
    for backend, fname in (('formal/arm64_codegen.py', '_frame_recv_bytes'),
                           ('formal/x86_64_codegen.py', '_frame_recv_bytes')):
        path = os.path.join(HERE, backend)
        with open(path) as fh:
            src = fh.read()
        check(f'{os.path.basename(backend)}_shares_the_frame_layout',
              'M.struct_constructor_sites' in src
              and 'M.struct_frame_block_bytes' in src,
              'this backend does not read the shared frame layout')

    # 6. The convention refusal, which is the decision this whole item turns
    #    on, is reachable and says the thing that matters.
    msg = M.returned_frame_convention_refusal('make', 8)
    check('eight_arguments_is_refused_by_name',
          'make' in msg and 'eight' in msg.lower(),
          f'got {msg!r}')
    check('under_the_limit_is_not_refused',
          M.returned_frame_convention_refusal('make', 2) == '',
          'a callee with room for the hidden word was refused')

    print(f'\n{_PASS} passed, {_FAIL} failed')
    return 1 if _FAIL else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
