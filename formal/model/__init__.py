"""Formal model package"""

"""The formal backends' shared value model and calling convention.

The two formal targets (arm64 and x86-64) are separate code generators, but
they are ONE language implementation: the same Mojo program must mean the same
thing whichever one compiles it. Everything that decides *what a value is* —
rather than *which instruction computes it* — therefore lives here, and each
backend is left with instruction selection only.

What belongs here, and what does not:

  * HERE: the in-memory layout of a container, the rules for comparing and
    scanning keys, the order of incoming arguments, which operators exist at
    all, and the source constructs that are no-ops in the value flow.
  * PER-BACKEND: the registers, the encoders, the instruction forms, and the
    number of argument registers the platform's ABI has.

Why it matters, concretely: if arm64 scanned a dict's membership at stride 8
while x86-64 scanned at stride 16, the same `k in d` would answer differently
per architecture — a silent divergence between two backends of one compiler,
which is the failure mode this project cannot have. The same applies to the
argument order of a generic function: a callee's comptime parameters are
leading arguments on BOTH paths, so the caller and callee must agree on that
order in one place, not twice.
"""

import dataclasses
from dataclasses import field
import os
import re
from typing import NamedTuple

import fire_compiler as F
from formal.types import (BOOL_TYPE_NAMES, DTYPE_TYPE_NAMES,
                          FLOAT_TYPE_NAMES, STRING_TYPE_NAMES, TYPE_NAMES)
from formal.diagnostics import (CodegenError, MATCH_REFUSED_KINDS, spelled,  # noqa: F401
                                    match_pattern_kind, match_pattern_refusal,
                                    _flat_callee)




# The value types a key element can have and still compare equal as a raw
# 64-bit word: interned string literals and integers.
CANONICAL_ELEM_TYPES = (F.IntLiteral, F.BoolLiteral, F.StringLiteral)



# ── The package hub ───────────────────────────────────────────────────────
#
# The implementation lives in the sibling modules, split out of what was one
# `formal/model.py`: aggregate layout, the CFG and its fixpoint, string and
# value models, the builtins and the call model, and so on.  Each of those
# modules begins `from . import *`, so every module shares THIS namespace, and
# everything that used to reach `model.<name>` still does.
#
# **The import order is a dependency order, not an alphabetical one.** A module
# reads its neighbours' names through `from . import *`, which captures only the
# names defined BEFORE it runs, and some tables are built at module load from a
# sibling's kind constants — `structs.FRAME_KIND` from `cfg`, `calls.list_kind`
# from `builtins`, `types.BLOB_TYPE_CTORS` from `values`.  `cfg` therefore comes
# first (it depends on no sibling at load time) and every other line below names
# a module whose load-time dependencies are already imported.  Two modules,
# `frames` and `layout`, have no load-time cross-dependencies and sit last.
from .cfg import *          # noqa: F401,F403
from .methods import *      # noqa: F401,F403
from .values import *       # noqa: F401,F403
from .strings import *      # noqa: F401,F403
from .structs import *      # noqa: F401,F403
from .builtins import *     # noqa: F401,F403
from .calls import *        # noqa: F401,F403
from .types import *        # noqa: F401,F403
from .init import *         # noqa: F401,F403
from .frames import *       # noqa: F401,F403
from .module import *       # noqa: F401,F403
from .layout import *       # noqa: F401,F403

# **Finishing the shared namespace, private helpers included.**  `from . import *`
# copies names at import time and SKIPS names that start with an underscore, but
# the pieces of this model call each other's underscore helpers constantly
# (`_offset_scale`, `_sentence`, `_fold_literal_expr`, `_declared_note`, …) and
# the rest of the tree reads some of them as `model._flat_callee`.  Two things
# are therefore done once every module is loaded:
#
#   * every module's full namespace — the shared header's own names plus each
#     module's definitions, private ones included — is collected into `_names`;
#   * `_names` is merged back into the package and into every module, so a name
#     a function will look up when CALLED is present in the module that calls it
#     no matter which module defined it or which loaded first.
#
# `setdefault` everywhere keeps each module's own definitions — the exact objects
# re-exported above — as the ones that win.
import sys as _sys

_MODULES = ("cfg", "methods", "values", "strings", "structs", "builtins",
            "calls", "types", "init", "frames", "module", "layout")

_this = _sys.modules[__name__]
_names = {_k: _v for _k, _v in vars(_this).items() if not _k.startswith("__")}
for _name in _MODULES:
    for _k, _v in vars(_sys.modules[__name__ + "." + _name]).items():
        if not _k.startswith("__"):
            _names.setdefault(_k, _v)

for _k, _v in _names.items():
    _this.__dict__.setdefault(_k, _v)
for _name in _MODULES:
    _mod = _sys.modules[__name__ + "." + _name]
    for _k, _v in _names.items():
        _mod.__dict__.setdefault(_k, _v)
