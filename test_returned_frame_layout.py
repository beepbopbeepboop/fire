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

# Three frame-returning calls whose results are NOT bound to a name, which is
# the case the landed version walked past.
UNBOUND_RESULTS = """\
class Point:
    def __init__(self):
        self.x = 7
        self.y = 9

def make():
    p = Point()
    return p

def take(v):
    return v

def main():
    take(make())
    print(make().x)
    return make()
"""

# One path returns a frame and the other ends the body, which is the shape
# `returns_on_every_path` has to say no to.
MIXED_RETURN = """\
class Point:
    def __init__(self):
        self.x = 7
        self.y = 9

def make(c):
    p = Point()
    if c:
        return p
    print(c)
"""


def _returns(callee_names, struct_by_name):
    """A `returns_frame` predicate over the callees that return a frame.

    Deliberately a closure supplied by the caller, because that is the
    contract `struct_returned_frame_sites` documents: the build pass's fixpoint
    decides this, and a second answer to the same question inside the
    model is the disagreement that produces a wrong number instead of a
    refusal.

    TWO arguments, because the model's contract is two: `(callee, bound_name)`.
    The bound name is what tells `dict.get` — whose second parameter is a
    DEFAULT — from this predicate, and handing `dict.get` over makes a missing
    callee answer with the bound name, so every call in the module is treated as
    returning a frame.  See `model.frame_returning_predicate`, which is where
    the real one is built and carries the measurement; `b2cec6f0` is the commit
    that found it.

    The bound name is IGNORED here, and deliberately: the function now reserves
    a block for EVERY call of a frame-returning callee, so a position that binds
    no name is covered too.  A one-argument closure would pass the cases below
    and then raise a `TypeError` on the first call, which is why this comment
    exists rather than the signature being the obvious one."""
    def _p(callee, _bound_name=None):
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
    #
    #    The pinned name is `struct_constructor_site_bytes`, not
    #    `struct_frame_block_bytes`, and the difference is the point rather than
    #    a rename: the emitters need the bytes ONE SITE reserves, which is not
    #    the struct's block — a one-field struct whose sole field holds a frame
    #    reserves the nested block alone, because there is no object, the value
    #    IS the nested frame's address. `struct_constructor_site_bytes` is the
    #    one reader that answers that (it is the function
    #    `struct_constructor_sites` advances its own layout cursor by), so
    #    pinning it keeps the property this case is about — one site can never
    #    be reserved one amount and laid out another — instead of pinning a
    #    name the consolidation deliberately stopped calling.
    for backend, fname in (('formal/arm64_codegen.py', '_frame_recv_bytes'),
                           ('formal/x86_64_codegen.py', '_frame_recv_bytes')):
        path = os.path.join(HERE, backend)
        with open(path) as fh:
            src = fh.read()
        check(f'{os.path.basename(backend)}_shares_the_frame_layout',
              'M.struct_constructor_sites' in src
              and 'M.struct_constructor_site_bytes' in src,
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

    # 7. The budget is SIX, and it is six because of the HIDDEN WORD rather than
    #    because of a callee's arity.  Both ABIs now put arguments past the
    #    register file in the caller's frame (`_MAX_INCOMING_ARGS` in both
    #    backends), so "the argument budget" is no longer six and reading this
    #    row that way would be reading a number that stopped meaning what its
    #    name says: what is six is the number of words the hidden block address
    #    can travel in, because both backends read it by the REGISTER path and
    #    neither has a stack convention for it.  Pinned because the number is a
    #    shared decision with a one-machine reason behind it, and a reader who
    #    "fixes" it to eight makes the two backends answer differently about one
    #    program.
    check('the_budget_is_the_smaller_register_file',
          M.returned_frame_convention_refusal('make', 6) != ''
          and M.returned_frame_convention_refusal('make', 5) == '',
          'the hidden word needs an argument register, and x86-64 passes six')
    check('the_budget_matches_x86_64_argument_registers',
          M.RETURNED_FRAME_MAX_ARGS == 6,
          f'got {M.RETURNED_FRAME_MAX_ARGS}')
    # …and it is a number of REGISTERS rather than of arguments, stated as a
    # fact about both backends rather than as a comment.  Each emitter moves the
    # hidden word home by naming the argument register it arrived in, and
    # neither has a path that would find it in the caller's frame: the stack-area
    # convention is `_load_home_from_stack`, and the hidden word does not go
    # through it.  A future change that gives the hidden word a stack slot has to
    # move these two lines AND `RETURNED_FRAME_MAX_ARGS` together, and this is
    # what fails first if it moves one of them — the failure being a budget that
    # quotes six while the backend is handing out twenty-four.
    for backend, line in (
            ('formal/arm64_codegen.py',
             'self._load_home_from_reg(_SRET_LOCAL, sret_arg)'),
            ('formal/x86_64_codegen.py',
             'self.asm.emit(encode_mov_r64_r64(Reg.R11, ARG_REGS[sret_arg]))')):
        with open(os.path.join(HERE, backend)) as fh:
            src = fh.read()
        check(f'{os.path.basename(backend)}_reads_the_hidden_word_from_a_register',
              line in src
              and '_load_home_from_stack(_SRET_LOCAL' not in src,
              'the hidden word is no longer read out of an argument register in '
              'this backend, so RETURNED_FRAME_MAX_ARGS is no longer its budget '
              'and this check — which exists to catch exactly that — has to '
              'move with it')

    # 8. A call whose result is NOT bound to a name still needs a block, and
    #    this is the change from the landed version.  `return make()`,
    #    `make().x` and `f(make())` are all frames the caller dereferences
    #    immediately, which is exactly the lifetime the block is sound for;
    #    leaving them out meant a callee copying into a register it had been
    #    handed by accident.
    stmts = parse(UNBOUND_RESULTS)
    structs = structs_of(stmts)
    main_fn = [f for f in funcs_of(stmts) if f.name == 'main'][0]
    ret = _returns({'make'}, {'make': structs['Point']})
    sites = M.struct_returned_frame_sites(main_fn, structs, ret)
    check('an_unbound_result_still_gets_a_block',
          len(sites) == 3, f'got {len(sites)} site(s), expected 3')
    offs = sorted(v[1] for v in sites.values())
    want3 = M.struct_frame_block_bytes(structs['Point'], structs)
    check('unbound_blocks_advance_by_the_block',
          offs == [0, want3, 2 * want3], f'offsets {offs}')

    # 9. One block's INTERNAL layout, which is what the copy re-points the
    #    nested frames through, and which has to be the same arithmetic the
    #    constructor uses.  A two-field struct has no nested frame, so the
    #    list is empty and the block is exactly the frame.
    nested, block = M.struct_frame_block_layout(structs['Point'], structs)
    check('a_flat_struct_block_is_its_frame',
          nested == [] and block == M.struct_frame_bytes(structs['Point']),
          f'nested {nested}, block {block}')

    # 10. `returns_on_every_path` is the strict answer and is the only one the
    #     returned-frame decision consults: a body that returns a frame on one
    #     path and ends on another leaves the caller's block uninitialised.
    stmts = parse(TWO_CALL_SITES)
    funcs = funcs_of(stmts)
    make_fn = [f for f in funcs if f.name == 'make'][0]
    main_fn = [f for f in funcs if f.name == 'main'][0]
    check('a_body_that_ends_in_a_return_always_returns',
          M.returns_on_every_path(make_fn.body) is True,
          f'body {[type(s).__name__ for s in make_fn.body]}')
    check('a_body_with_no_return_does_not',
          M.returns_on_every_path(main_fn.body) is False
          and M.returns_on_every_path([]) is False,
          'main has no return and an empty list has no path')

    stmts = parse(MIXED_RETURN)
    make_fn = [f for f in funcs_of(stmts) if f.name == 'make'][0]
    check('an_if_without_else_can_fall_off_the_end',
          M.returns_on_every_path(make_fn.body) is False,
          'the `if` has no else, so one path ends the body')

    print(f'\n{_PASS} passed, {_FAIL} failed')
    return 1 if _FAIL else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
