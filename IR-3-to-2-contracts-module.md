INTERFACE REQUEST  from=[3]  to=[2]  file=formal/lean.py

STATUS: `lib/Contracts.lean` is written, builds clean, and has **0 admitted
holes**. It is not yet *used* by anything, because two things outside my write
set stand between it and the Done-when. This request covers the first; a second
one (not yet written) covers the second.

WHAT — 1: register the module.

  `formal/lean.py`'s

      LIBRARY_MODULES = ("ProofLib", "X86", "work", "Refine")

  is what `ensure_library` builds and what `library_census` reports, so a new
  `lib/*.lean` is invisible to both until it is listed. `lib/Contracts.lean`
  currently builds and is not registered, which means the honest library census
  is still 0 and says nothing about it.

  The one-line change:

      -LIBRARY_MODULES = ("ProofLib", "X86", "work", "Refine")
      +LIBRARY_MODULES = ("ProofLib", "X86", "work", "Refine", "Contracts")

  Order matters and is not arbitrary: `Contracts` imports `ProofLib` and
  `Refine`, so it must come after them. `ensure_library` iterates in order, so
  this is also the build order.

  `formal/lean.py` is in **nobody's** write set this round, which is why it is a
  request rather than an edit. If the integrator would rather register it at
  merge time than hand it to [2], that is the better call — the change is
  mechanical and carries no judgement.

  I checked what breaks if it is NOT registered: nothing. `ensure_library`
  ignores an unlisted module, and the generated proofs import only
  `ProofLib`/`work`/`Refine`. So this is purely about the module becoming
  visible and buildable by the toolchain, not about a failure.

WHY:

  FORMAL.md §11.2 [3] asks for "at least one real export [to carry] a spec that
  is not the identity function, and a caller [to discharge] its obligation
  against it". The machinery for that is what `lib/Contracts.lean` is; without
  registration the machinery is real but unbuilt by the project, and a module
  that is never built is a module that rots.

BLOCKS:

  Nothing of mine — `Contracts.lean` is complete as a library and I have
  verified it compiles against the repo's own `lib/*.olean`. This blocks only
  the *project* building and censusing it, and the generator importing it
  (request 2).

  Measured and unchanged by any of this: the four registered modules still
  report **0 admitted sorries** between them, and the x86-64 and arm64
  executable proof paths are untouched.
