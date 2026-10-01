# Moved from gimple_gen_infra.py - gimple C/GIMPLE backend (mojo/backend_gimple).
# Shared analysis lives in mojo/middle/*; this file is emission.
"""GimpleGen infrastructure: emit/temps/coercion/const-eval/strings/comprehensions.

Function-extraction architecture: former GimpleGen methods as
module-level functions taking `gen` first; delegates remain on
the class; cross-module references are qualified.
"""
from __future__ import annotations

import os
import re

from fire_compiler import (
    IntLiteral, FloatLiteral, StringLiteral, TstringLiteral, BoolLiteral,
    EllipsisLiteral, NoneLiteral,
    IdentExpr, BinaryOp, CompareChain, UnaryOp, CallExpr, MemberExpr,
    SubscriptExpr, SliceExpr, TernaryExpr, WalrusExpr, LambdaExpr,
    ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension,
    VarDecl, AssignStmt, AugAssignStmt, MultiAssignStmt,
    ReturnStmt, RaiseStmt,
    BreakStmt, ContinueStmt, PassStmt, AssertStmt, ExprStmt,
    ImportStmt, FromImportStmt,
    IfStmt, WhileStmt, ForStmt,
    FunctionDef, TryStmt, WithStmt,
    ComptimeIfStmt, ComptimeForStmt, ComptimeVarStmt,
    GlobalStmt, NonlocalStmt, DelStmt, MatchStmt,
    StructDef, TraitDef,
    YieldExpr, YieldFromExpr, AwaitExpr,
    Parser, py_tokenize, _as_str, _as_set, _as_int, _pair_key, _ptr_slot_in_range,
    _as_ident_node, _as_member_node,
)
import regex_compile
import mlir
import mojo.backend_gimple.device_glue as _gmi_glue
import mojo.middle.types as gimple_ctypes
import mojo.middle.lambdareduce as gimple_lambdareduce
import mojo.middle.comptime as comptime_eval
import mojo.middle.solvers as gimple_solvers
import mojo.middle.exprtypes as gimple_exprtypes
import gimple_codegen
import mojo.backend_gimple.emit_methods as gmp
import mojo.backend_gimple.emit_calls as ggc
import ownership_destruct
# `from X import Y` works under this project's own self-hosted compile
# (used throughout this codebase — e.g. gimple_codegen.py's `from
# module_loader import load_module, get_symbol_type`), but `from X import
# Y as Z` (a RENAMED single-name import) does not: found for real via
# `make check-native-dumpfull` reporting "_owned_block_terminates:
# unavailable in compiled mode (imported from an unresolved external/
# relative module)" — grep confirms this file was the only place in the
# entire tree using that aliased form. No other local module import uses
# `as` this way; don't reintroduce it here or elsewhere.
from ownership_check import _block_terminates

# Re-export shared helpers from mojo.middle.infra_infer via explicit imports.
# (Was globals().update(dir(_shared)); self-hosted globals() is a
# weak stub returning NULL — see runtime/fire_runtime.c _globals.)
from mojo.middle.infra_infer import *  # noqa: F401,F403
from mojo.middle.infra_infer import (
    _FC_SEP, _POINTER_CTOR_NAMES, _as_ident_node, _as_int, _as_member_node, _as_set,
    _as_str, _block_terminates, _closure_info_for_ident, _collect_return_types, _build_analysis_funcs, _build_analysis_structs, _build_fresh_returning, _string_uses_ok, _key_views_ok, _list_elements_ok, _lambda_owned, _compute_closure_candidates, _compute_scoped_closure_candidates, _compute_owned_free_candidates, _compute_scoped_free_candidates, _compute_int_keyed_dicts, _scope_decl_name, _is_ctor_display, _empty_ctor_ctype,
    _function_has_reachable_fallthrough, _infer_param_types, _infer_return_type, _is_free_eligible_function, _is_known_field, _known_field_type,
    _pair_key, _prepass_list_elem, _ptr_slot_in_range, _resolve_member_expr_type, _resolve_type, _scan_container_elems,
    _seed_addressed_locals, _type_of
)
# `user_dunder_repr_call` is the SHARED dunder lookup behind both the
# `repr()` route (`_repr_value`, in emit_resolve.py) and the `str()`/`%s`/
# f-string route (`_stringify_value`, below), so the two spellings of "ask
# this object to describe itself" cannot disagree about which dunder wins.
from mojo.middle.calls_shared import user_dunder_repr_call
from mojo.middle.stmts_shared import _annotation_container_elem_type

# Separator for `function_calls`' `name<sep>index` composite strings — see
# `analyze_param_usage`. U+001F (ASCII Unit Separator): never appears in a
# function identifier or a decimal integer, and unlike NUL it survives
# `mojo_str_cat` on the self-hosted path.

def _exc_type_id(gen, name: str) -> int:
    """The tag for an exception class name: a hash of the name, not a
    first-seen-order counter. Stdlib compilation runs many GimpleGen
    instances (parallel process pool, one per module) and a plain
    incrementing counter would assign a different id to the same name
    depending on which process visits it first — same logical program,
    different generated C, which defeats the CAS content-cache (every
    build looks like new content, forcing a full stdlib rebuild every
    time instead of a cache hit)."""
    if name not in gen._exc_type_ids:
        # `_crc32_str`, NOT `zlib.crc32` — the compiled backend stubs zlib,
        # so every exception class got the id `1`. See `_crc32_str`.
        gen._exc_type_ids[name] = (gimple_ctypes._crc32_str(name) & 0x7fffffff) or 1
    return gen._exc_type_ids[name]


def _is_exc_class_name(gen, name: str) -> bool:
    """Whether `name` is confidently an exception *class*, not a local
    variable — a user-defined struct (naturally exception-shaped or not;
    struct_field_types has no notion of inheritance) or a known builtin."""
    return name in gen._KNOWN_EXCEPTION_NAMES or name in gen.struct_field_types


def _reset_func(gen, body: list = None, params: list = None,
                allow_lambda_reduction: bool = True):
    # The enclosing AST body, kept so a later pass can answer "how is this
    # local USED?" — specifically the lambda beta-reduction, which may only
    # inline a `lambda`'s body at its call sites when the local holding it
    # is used for NOTHING ELSE (an escaping lambda would be captured at
    # creation but read at some other call, where there is no call site to
    # inline into). Cheap: a reference, and the body is already alive for
    # the whole function.
    gen._cur_func_body = body
    # The enclosing function's PARAMETER names, for the same reason the body
    # is kept. `mojo/middle/lambdareduce` uses this to refuse inlining a
    # lambda that captures a PARAMETER: a parameter's ctype is the least
    # reliable one in the compiled path (self-hosting shows the backend's own
    # `gen` parameter — a GimpleGen struct pointer — degrade to a plain
    # `int64_t`), so a body inlined over it is typed against a type that is
    # not the variable's real one. Only the NAMES are needed, and only
    # during the reduction, so this is a reference-cheap set built once.
    gen._cur_func_params = set()
    # NOT `for _p in (params or ()):` -- `params: list = None` makes the
    # `or`'s left operand a MojoList*-or-None union against a real MojoList
    # (the `()` literal) on the right. Self-hosted, mixed-type `or`/`and`
    # unification has already been found to mistype the combined boolean as
    # a bare MojoList* and feed the WRONG operand's raw value into a later
    # `mojo_list_len` truthiness check (see emit_methods.py's `_n_kwargs`
    # comment for the `mojo_list_len(0x1)` crash from the identical pattern,
    # and CRASH.md for this exact call site: `_reset_func`'s param scan
    # SIGSEGV'd on `mojo_list_len(l=0x1)` for `main()`'s params, which are a
    # real empty list, not None). An explicit `is not None` check never
    # participates in that unification.
    if params is not None:
        for _p in params:
            gen._cur_func_params.add(_p[0] if isinstance(_p, (tuple, list)) else _p)
    # The lambda beta-reduction's cache is keyed by body IDENTITY (see
    # mojo/middle/lambdareduce.reducible_lambdas), so it deliberately
    # SURVIVES `_reset_func` — a lifted closure resets too, and a one-slot
    # cache would then be overwritten mid-function. The scan is still kicked
    # off eagerly here, because it needs only the body (its ctype lookups
    # fall back to a placeholder) and doing it now guarantees every
    # qualifying lambda is STAMPED before any of them is reached, which is
    # how `_lower_LambdaExpr` recognises one.
    #
    # `allow_lambda_reduction` is False for a COROUTINE BODY (see
    # `gen_func`'s call site and coro.py's `_mojo_coro_body` marker). The
    # reduction is only sound where the ENCLOSING scope can represent the
    # captured values' real types, and a coroutine body's lowering
    # deliberately cannot: the C++ coroutine body model is scalar-only
    # (`_infer_simple_expr_ctype` returns None, and the caller defaults to
    # int64_t). Inlining a `lambda: some_string` there turned the captured
    # pointer into an int64_t, which printed as the pointer's bit pattern
    # and, under -Werror=int-conversion, failed the whole self-host build.
    # Skipping the scan leaves such a lambda on the pre-existing lifted
    # path — still wrong, but unchanged and separately documented — instead
    # of making it wrong in a NEW way inside a pass that cannot represent it.
    #
    # NOT `if body and allow_lambda_reduction:` -- `body` is MojoList*-typed
    # and `allow_lambda_reduction` is bool/int64_t-typed, and self-hosted
    # this mixed-type `and` was mistyped as MojoList*: the codegen tested
    # `mojo_list_len(body)`, then (since body was truthy) CSEL-selected
    # `allow_lambda_reduction` -- the `and`'s real second operand -- and fed
    # THAT (a bare 0/1) into a SECOND `mojo_list_len` call to get the
    # overall truth value, SIGSEGV'ing on `mojo_list_len(l=0x1)` (see
    # CRASH.md and emit_methods.py's `_n_kwargs` comment for the identical
    # pattern). Two separate, single-operand truthiness tests never enter
    # that unification, and are equivalent to the original `and` (both
    # operands still falsy-checked, `body`'s empty-list case included).
    if allow_lambda_reduction:
        if body:
            gimple_lambdareduce.reducible_lambdas(gen)
    gen.bb_counter   = 2
    gen.temp_counter = 0
    # The TEMP tables are reset HERE rather than left to the feature-level
    # resets because `temp_counter` is: temp names repeat across functions, so
    # an entry a previous function left behind is read as THIS function's, and
    # an entry that says "this value is fresh and nobody else can name it" is
    # what makes a consumer FREE it — a stale one is a wrong free, not a
    # missed one. The one table that was already reset per function
    # (`_cstr_key_src`) says so in its own comment; these are the same shape.
    #
    # A LIFTED CLOSURE runs this too, in the middle of its parent, so this
    # also drops the parent's not-yet-consumed temps. That loses frees (the
    # safe direction) and cannot add one. The per-FUNCTION ownership state
    # (`_owned_free_candidates`, `_scope_*`, and the element/closure tables in
    # `_reset_scope_state`) is deliberately NOT touched here, because the
    # parent's has to survive the closure's lowering intact.
    gen._fresh_vals = set()
    gen._fresh_str_tmps = set()
    # `_boxed_vals` is this same shape — a set of TEMP NAMES — and was
    # missing from the reset list above, which is exactly the bug the list's
    # own comment describes: `temp_counter` restarts at 0 for every
    # function, so a name an earlier function registered as "this int64_t
    # may be a box, resolve it with mojo_box_int/mojo_box_double first" is
    # the SAME SPELLING as an unrelated temp this function is about to
    # allocate, and the stale entry is read as this function's.
    # `_to_int64`'s `val in gen._boxed_vals` branch is where it bites, and
    # it bites hardest when the collided temp is not even an int64_t:
    # `mojo_box_int (int64_t)` then received a `MojoList *` /
    # `mojo_box_double` a `char *`, four `-Werror=int-conversion` failures
    # in the self-host closure (`_generator_to_list`,
    # `_apply_fstring_spec`, `_maybe_lower_mlir_op`, `_gen_for_dict` —
    # each reading a name `mojo_backend_gimple_emit_infra__emit_call`
    # had boxed, or `gen_for_enumerate` before it).
    #
    # Every writer and every reader of this set is inside ONE function's
    # lowering (`_boxed_vals.add` in emit_calls' subscript accessor and in
    # emit_loops' for-target; the reads in emit_exprs/emit_infra), so
    # per-function is not merely safe, it is the only scope in which the
    # name means anything.
    gen._boxed_vals = set()
    gen.decls:       list[str]         = []
    gen.body_lines:  list[str]         = []
    gen.var_types:   dict[str, str]    = {}
    # This function's higher-order parameters whose declared default names
    # a compiled generator of this compile — `{param: generator api}`.
    # Per-FUNCTION, like every other map here (and reset HERE, not left to
    # `gen_func`, because a lifted closure's body runs `_reset_func` too and
    # would otherwise read the enclosing function's entries for a parameter
    # name that means something else here). `_lower_fnptr_call` reads it to
    # type the result of `walk(root)`; `gen_func` seeds it right after this
    # call, once `param_defaults` is in hand. See
    # `calls_shared._callable_param_generator_apis`.
    gen._callable_param_gen_api: dict[str, dict] = {}
    # `{mut}`-capture-spec preloaded pointer temps (see _gen_lifted_
    # closure) -- reset per function so a stale entry from a
    # previously-compiled closure can never leak into an unrelated
    # function's body.
    gen._gimple_mut_ptr: dict[str, str] = {}
    gen._struct_field_owners.clear()
    # ENCLOSING function's own locals that some nested closure captures
    # BY REFERENCE (name -> pointee ctype) -- see _seed_mut_captured_
    # local_types's docstring for why these are "boxed" (heap-
    # allocated, the local itself declared as a POINTER) rather than
    # plain stack locals whose address is taken: `-fgimple` rejects a
    # stack local's address being taken anywhere in the function if
    # that same local is also the target of a cast-assignment or the
    # direct operand of a `return` statement elsewhere (confirmed via
    # a hand-reduced repro -- "non-register as LHS of unary operation"
    # / "invalid operand in return statement"), which real stdlib code
    # doing exactly that (std/memory/span.mojo's `Span.count`, hit
    # during this fix's own stdlib-dylib regression check) triggers
    # immediately. Boxing sidesteps the restriction entirely: the
    # local is a plain, never-address-taken pointer variable from
    # first declaration, so ordinary GIMPLE rules apply to IT, and
    # only its (separately allocated) pointee is ever accessed
    # in-place.
    gen._boxed_mut_locals: dict[str, str] = {}
    # PARAMETERS of this function that some nested closure captures BY
    # REFERENCE (mojo-level name -> the C identifier the incoming
    # parameter is actually declared under) -- see
    # `_plan_mut_captured_params`. Populated BEFORE the parameter list
    # is turned into a C signature (that is the whole point: the
    # parameter must be declared under a different C name so the
    # heap-boxed pointer local can carry the source-level name).
    # Reset per function for the same reason as the two dicts above.
    gen._mut_boxed_param_c: dict[str, str] = {}
    # Scalar locals/parameters whose address gets taken somewhere in this
    # function via `UnsafePointer(to=x)` / `Pointer(to=x)` (see
    # `_lower_call`'s handling of that plain-call keyword shape) --
    # pre-populated by name (no type needed -- `_lower_IdentExpr` already
    # computes ctype itself at read time) via `_seed_addressed_locals`
    # BEFORE any statement in the body compiles, mirroring `_seed_mut_
    # captured_local_types`'s identical whole-body-first-pass shape.
    # Reset per function so a stale entry can never leak into an
    # unrelated function's body. Every READ of a name in this set
    # (`_lower_IdentExpr`) is materialized through a fresh register temp
    # instead of handing back the now-addressable C variable directly --
    # see that branch's own docstring for why (`-fgimple` rejects a
    # stack local's address being taken anywhere in the function if that
    # same local is also directly `return`ed/cast-assigned/read-without-
    # materializing elsewhere -- confirmed to apply regardless of
    # whether that other use is BEFORE or AFTER the address-of in
    # program order, since GCC's addressability analysis is whole-
    # function, not flow-sensitive: std/collections/list.mojo's SIMD
    # `extend` reads `value.size` textually BEFORE its own `UnsafePointer
    # (to=value)` a few lines later, and marking `_addressed_locals`
    # only AT the address-of statement itself left that earlier read
    # unprotected -- a real regression this whole-body pre-pass fixes).
    gen._addressed_locals: set = set()
    # Locals bound to a TAGGED nested generator-tuple slot (see
    # _emit_generator_tuple_unpack's nested path). Reset per function.
    gen._tagged_gen_tuple_locals: set = set()
    # name -> (tagged_box_cvar, pos_literal): a destructured element of a
    # tagged nested generator tuple whose STATIC type is genuinely unknown
    # (`name`/`fromlist`/`level` all land in slot 0 across Lib/modulefinder's
    # yield sites). Reads of the name dispatch at RUNTIME via the tag stored
    # in the box (see emit_exprs._lower_IdentExpr + the mojo_tagged_* callers).
    gen._tagged_dyn_src: dict = {}
    # temp-name -> (box, pos) for reads of a _tagged_dyn_src local, consulted
    # by use-site dispatch (_tagged_dyn_read / print). Reset per function.
    gen._tagged_dyn_vals: dict = {}
    # key-temp -> the int64_t local it was converted from, for a dict key /
    # comparison operand `_char_to_cstr(..., transient=True)` heap-formatted:
    # `_emit_call` frees it right after the one call that consumes it. Temp
    # names repeat across functions, so this MUST reset per function (a stale
    # entry would free a temp that never owned anything). See doc/MEMORY.html.
    # Emptied IN PLACE, not rebound to a new container (the four below exist
    # from GimpleGen.__init__): a dropped container is only garbage under
    # CPython; self-hosted, each function leaked its old set/dict and every
    # temp-name string in it (2.7M strings on `--dump-full fire.py`).
    gen._cstr_key_src.clear()
    gen._kw_key_src.clear()
    # Same reason as the two above: temp names repeat across functions, so a
    # stale entry would mark some other function's `_t3` as a known integer.
    # A miss here is harmless (the value falls back to the runtime's own
    # discriminator, i.e. today's behaviour) which is what makes this table
    # safe to seed only where the answer is provable.
    gen._int_word_vals.clear()
    gen._fresh_vals.clear()   # per function: temp names repeat across functions
    # The four the ownership work added are ASSIGNED here rather than cleared,
    # and the difference is not a style choice: they are not in
    # `GimpleGen.__init__`, so this is where they come into existence, and a
    # `.clear()` on an attribute that does not exist yet raises.  The three
    # above are cleared instead because `__init__` creates them and a rebind
    # there is a leak on the self-hosted path (see the note above).
    #
    # The subset of `_fresh_vals` whose value is a list that owns its own
    # string elements (see `_OWNS_STR_ELEMS`). A temporary that gets freed by
    # its consumer uses the same distinction, so it lives here rather than
    # being re-derived. A stale entry would make an unrelated list of
    # BORROWED strings be freed as if it owned them.
    gen._owned_str_elem_vals: set = set()
    # The NAMES (not temps) of owned locals whose value owns its string
    # elements; the free is emitted for the name at the scope exit.
    gen._owned_str_elem_names: set = set()
    # The values (not names) that are a CLOSURE — a bound method whose `self`
    # is the malloc'd environment emit_calls' constructor paired with it, so
    # both are one allocation unit and one free.
    gen._closure_vals: set = set()
    # The NAMES of owned locals bound to a closure; the free is emitted for the
    # name at the scope exit.
    gen._owned_closure_names: set = set()
    # Names of values whose per-slot element kinds are recorded ON THE VALUE
    # (`struct.unpack` of a mixed format, and a local bound from one) — the
    # marker that makes a read with no compile-time slot index (iteration, a
    # computed subscript) lower as a BOXED read. Per-function by DESIGN, and
    # that is what `_infer_return_maybe_kinds`'s own docstring says: "inside
    # one function the marker rides along on the local name"; the cross-
    # function half is `_return_maybe_kinds`, keyed by CALLEE name, precisely
    # because a temp name cannot survive a return.
    #
    # So it has to be reset here, and did not used to be: `temp_counter`
    # restarts at 0 in every function's prologue (two lines above), so every
    # function's temps are `_t1.._tN` again, while this set accumulated one
    # entry per NAME for the whole module. A function whose loop-iterable temp
    # then reused a name an earlier function had registered read that list
    # through `mojo_list_get_boxed` instead of the accessor its element type
    # calls for. Measured on this tree, on a change to build_stdlib_dylib.py
    # that shifted nothing but temp numbering: both
    # `for e in reflect.collect_runtime_exports_h(...)` loops (in
    # `runtime_export_entries` and `build_stdlib`) stopped compiling with
    #
    #     error: assignment to 'char *' from 'long long int' makes pointer
    #            from integer without a cast [-Wint-conversion]
    #
    # because the runtime-dispatched DICT arm had already declared the shared
    # target `char * e` and the LIST arm then stored a box into it. The
    # hand-reduced form is in test_gimple.py's
    # `kinds_marker_does_not_leak_into_a_later_function`: same program, one
    # extra `s = 'ab'` in the second function, and the emitted C goes from one
    # `mojo_list_get_boxed` (the one the mixed literal earns) to two. On a
    # plain int list the two accessors return the same word, so that case is a
    # C-shape divergence only — which is the other reason not to leave it: a
    # divergence nobody can see is one nobody looks for.
    gen._maybe_kinds_vals: set = set()
    # Temps holding a heap string THIS function's own concatenation lowering
    # just built (`_emit_str_cat`) and that nothing else can hold yet. The
    # parent concatenation that consumes one as a direct operand frees it.
    # Same per-function reset requirement as `_cstr_key_src`.
    gen._fresh_str_tmps.clear()
    gen.loop_stack:  list[tuple[str,str]] = []
    gen.exc_depth    = 0
    # Entry `len(loop_stack)` of each currently-open `try` body. A
    # `break`/`continue` that targets a loop already open at try-entry
    # must emit a `mojo_exc_pop()` first (see
    # `_emit_try_loop_exit_exc_pops`); the former `gen._emit` nested-
    # closure interception that used to do this was not run by the
    # self-hosted backend.
    gen._try_loop_protect: list = []
    # The `finally` BODY list of each currently-open `try`, in the same
    # order as `_try_loop_protect` (None for a try with no finally). A
    # `break`/`continue` that jumps out of a try-with-finally has to RUN
    # that finally before the jump — see
    # `_emit_try_loop_exit_exc_pops`.
    gen._try_finally_bodies: list = []
    # Set True by _gen_stmt_TryStmt / the with-__exit__ path in
    # _gen_stmt_WithStmt whenever THIS function's own body (not a
    # nested closure's — those get their own _reset_func/flag) emits a
    # real `setjmp(...)`. Consulted by _gen_struct_method /
    # _gen_lifted_closure when emitting their C signature: a
    # `__GIMPLE`-tagged function's body bypasses gcc's normal
    # frontend gimplification pass, which is what marks a
    # setjmp-containing function's CFG with the special "returns-
    # twice" abnormal-edge handling real setjmp/longjmp semantics
    # require -- confirmed via a hand-reduced, Mojo-independent C
    # repro that `longjmp` into a `__GIMPLE`-tagged function's
    # `setjmp` frame reads back all-zero and segfaults. See
    # bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md's
    # "Segfault root-caused" section. gen_func (free functions) has
    # always deliberately been non-`__GIMPLE` (LENIENT) already, so
    # this flag only matters for the two `__GIMPLE`-tagged code
    # paths.
    gen._func_used_setjmp: bool = False
    gen.func_ret_type: str             = ''
    gen._last_was_terminal: bool       = False
    # Computed once, reused for both the _elem_types and _dict_val_types
    # seeds just below -- see _locally_bound_names' own docstring.
    _reset_locally_bound = gen._locally_bound_names(body, params)
    # Container / layout state.
    # Seeded from self._global_elem_types (populated once by gen_module's
    # Phase 1.7 pre-scan, never reset) rather than starting empty -- a
    # module-level global container's element type means the same thing
    # in every function, so it must survive this per-function reset the
    # same way _field_elem_types already does for struct fields. Without
    # this seed, EVERY read of a global list/dict inside any function
    # (not just _toplevel) silently defaulted to int64_t, even though
    # Phase 1.7 had already correctly inferred the real type moments
    # earlier — a genuine, silent wrong-value bug, not a compile
    # failure. See bugs/hard/CODEGEN_reset_func_wipes_global_container_
    # type_inference.md.
    #
    # Names LOCALLY bound anywhere in this function's own body (per
    # _locally_bound_names, real Python scoping: any assignment target
    # anywhere in the function makes that name local for the WHOLE
    # function) are excluded from the seed entirely -- confirmed via a
    # real segfault otherwise: a local `path_separators = [42, 43]`
    # shadowing the global `path_separators: list[str]` inherited the
    # seeded char* element type for its OWN static return-type
    # inference (which runs as an early syntactic pre-pass, before any
    # of the function's own assignments are actually processed, so it
    # has no notion of "this name gets reassigned partway through" —
    # only "is there currently an entry for this bare name"). The
    # existing per-assignment write sites (e.g. _gen_stmt_AssignStmt)
    # DO correctly overwrite _elem_types once the body is actually
    # generated statement-by-statement, but a static pre-pass reading
    # the table before that point would otherwise see the wrong,
    # global-seeded entry for a name Python itself treats as local
    # for this entire function.
    # explicit loop + `_as_str`, NOT `{k: v for k, v in
    # gen._global_elem_types.items() if ...}`: a dict comprehension with a
    # 2-tuple `.items()` target boxes both k and v on the self-hosted
    # path, so `_elem_of(name)` later returned a boxed/garbage value that
    # `_declare_var`'s `mojo_str_cat` ran `strlen()` on — a hard segfault
    # on the single-TU `--dump myinterpreter.py` (list comprehension over
    # a container with a seeded element type).
    gen._elem_types = {}   # container var → element C type
    for _gek in gen._global_elem_types:
        _gek_s = _as_str(_gek)
        if _gek_s not in _reset_locally_bound:
            gen._elem_types[_gek_s] = _as_str(gen._global_elem_types[_gek])
    gen._nested_elem_types: dict[str, str] = {}
    # Per-function, keyed by C temp/value NAMES (`_t40`, ...) which repeat
    # across functions — so a stale entry (e.g. `_dict_items_val_elems
    # ['_t40'] = 'int'` from a `sorted(d.items())` in an earlier function)
    # otherwise poisons the NEXT function's identically-named temp
    # (`_t40 = node->elifs` -> `for _, eb in _t40` decided slot 1 was
    # `int`, truncating a list pointer to 32 bits -> SEGV in the compiled
    # `_collect_return_elems`).
    gen._dict_items_val_elems: dict[str, str] = {}
    gen._dict_items_int_keys: set = set()
    gen._dict_item_int_key_vars: set = set()
    gen._int_key_loop_vars: set = set()
    gen._tuple_slot_types: dict[str, list] = {}
    # NOTE: `gen._return_slot_types` (the name-keyed, CROSS-function half of
    # per-slot tuple types, written at a return and read at a later call
    # site) is deliberately NOT re-created here. It is initialized once per
    # MODULE in gimple_codegen.py's setup, next to `_return_elem_types` —
    # resetting it per function would discard every callee whose body was
    # emitted before the caller's.
    gen._dict_item_pair_vars: dict[str, str] = {}
    # `it = iter(<list>)` inside ordinary codegen (incl. an A3 stack-switch
    # generator body): C-name of the iterator local -> {'list','cursor','elem'}.
    # `next(it)` advances the shared int64_t cursor temp; a following
    # `for x in it:` resumes from it (single-pass Python iterator semantics).
    # Mirrors gimple_cpp_core.py's `_cpp_list_iter_cursor` for the old cpp
    # coroutine path. Reset per function like the other body-local tables here.
    gen._list_iter_cursor: dict = {}
    gen._span_mut_params: dict[str, bool]  = {}  # param/var name → literal Span/StringSlice mut=True/False
    # NOTE: _field_elem_types is intentionally NOT reset here — it stores
    # per-struct metadata that must persist across function boundaries
    # (set during __init__ field assignments, read at any later field
    # access site).  Initialized once in __init__.
    # Actual type of int64_t-boxed pointers, keyed by temp/var name. MUST reset
    # per function: temp names (_tN) recycle, so a stale entry from one function
    # would mis-type a same-named temp in the next (e.g. an open() file handle
    # read as a leftover MojoSet*, emitting MojoSet_read).
    gen._actual_types:    dict[str, str]   = {}
    # Flow-sensitive `isinstance()` narrowing. Inside the then-branch of
    # `if isinstance(E, SomeStruct):` (and `and`-chains of such tests),
    # every read of E is known to be a `SomeStruct *` — the guard the
    # source already wrote. Key: "i:<name>" for an IdentExpr E, or
    # "m:<obj>.<member>" for a MemberExpr E with an IdentExpr base. Value:
    # (ctype, c_value). _lower_IdentExpr / _lower_MemberExpr consult this
    # before their generic type-erased handling; _gen_stmt_IfStmt sets and
    # restores it around each guarded body. Reset per function like every
    # other per-body table here.
    gen._narrowed_exprs:  dict             = {}
    # Function PARAM name -> the bare struct name its Mojo annotation
    # names, when that annotation's base is a known struct (e.g.
    # `downgrade: ArcPointer[Self.T]` → 'ArcPointer'). The ABI can box
    # such a param to a generic scalar/pointer (`int64_t`/`int64_t *`)
    # that loses the struct identity entirely, so _lower_MemberExpr
    # consults this map to recover the real struct-pointer type to cast
    # to before a `->member` access. Reset per function: param names
    # recycle and struct identity must never leak across functions.
    gen._param_struct_types: dict[str, str] = {}
    # MojoBoundMethod* var/temp name -> the bound method's real return
    # type, so a later call through the value (_lower_bound_method_call)
    # narrows the result correctly instead of always assuming int64_t.
    # Reset per function for the same reason _actual_types is: temp
    # names (_tN) recycle across functions. See _lower_bound_method_value.
    gen._bound_method_ret_types: dict[str, str] = {}
    # Any callable VALUE (a lambda's `_funcptr_X` static, a bound-method
    # handle, a struct method taken as a value) -> that callee's real return
    # type. The `mojo_fnptr_call_N` / `mojo_maybe_bound_call_N` helpers are
    # the homogenized `int64_t` convention — the RIGHT thing for the box they
    # hand back — but the CALLEE is the one that knows the type, so a `_Bool`,
    # a `double` or a `char *` came back widened: `e = lambda: False;
    # print(e())` printed `0` and `e = lambda: "hi"; print(e())` printed its
    # own pointer decimal. Recorded where the value is materialized (see
    # `_lower_LambdaExpr`) and read by `_lower_fnptr_call_value`.
    # Reset per function for the same reason _bound_method_ret_types is: temp
    # names (_tN) recycle across functions.
    gen._callable_ret_types: dict[str, str] = {}
    # A DICT's lowered value -> the SINGLE callable return type stored into
    # it, or '' for "more than one distinct type, so no answer". The rule is
    # the same unanimity-or-nothing rule every other inference in this file
    # follows, and it is applied HERE, at the store, where the store site
    # actually knows what it just stored — so the consumer (the one
    # `d[k](...)` call site) is a plain `or 'int64_t'`. A dict is the one
    # container whose value type is a single slot, so a per-key table does not
    # exist; the single agreed return ctype is enough, because the consumer
    # only uses the answer when it is UNANIMOUS. A dict holding callables of different return
    # types records '' (ambiguous) and the consumer keeps the old int64_t
    # answer, which is the pre-existing behaviour — never a new wrong one.
    # Without any of this, `d['k'] = lambda: False; print(d['k']())` printed
    # `0`: the callable's return type was lost at the store, exactly as it
    # was at the call before `_callable_ret_types` existed.
    #
    # The value type is `str`, not `set`. This used to be a set of every
    # ctype stored, with the consumer doing `next(iter(_seen))` when the set
    # had one element — and that spelled two defects the self-host closure
    # then failed on. (a) A struct field set by attribute assignment has no
    # StructDef `type_ann` for `_annotation_dict_val_type` to read, so
    # `.get()` on this field came back `int64_t`, not `MojoSet *`: `len()`
    # then guessed "a list", the for-loop guessed "a dict", and `next()`
    # matched no lowering at all and emitted a call to a `next` symbol that
    # does not exist — `fire.py --dump-full` compiled clean and then died at
    # `ld: undefined _next`, out of `_lower_call`. (b) A `dict[str, str]`
    # field DOES have a working accessor (`_callable_ret_types` right above
    # is read with `mojo_dict_get_str`), so keeping the agreed type as the
    # value removes the inference gap instead of working around it. The
    # unanimity rule is unchanged and is now enforced where the value is
    # stored, where the store site actually knows.
    # Reset per function for the same reason as the maps above.
    gen._dict_callable_ret: dict[str, str] = {}
    # Builtin-container method bound as a first-class VALUE (`append =
    # l.append`, the classic accumulator-aliasing idiom) — key: the C
    # name of the temp/var holding the boxed value; value: (receiver
    # ctype, receiver hidden-local C name, method name). A later call
    # through the stored value (_lower_named_call / _gen_stmt_ExprStmt's
    # statement-level twin) lowers as a DIRECT container-method call on
    # the recorded hidden receiver local, reusing _lower_list_method/
    # _lower_dict_method/_lower_set_method verbatim — so per-call-site
    # int/str element dispatch behaves exactly like the direct
    # `l.append(x)` spelling. The receiver is captured into its own
    # void* hidden local at the reference site, so rebinding the source
    # variable afterwards can't redirect an already-taken bound method.
    # Reset per function for the same reason _bound_method_ret_types is:
    # temp names (_tN) recycle across functions. See
    # _lower_builtin_method_value.
    gen._builtin_method_values: dict[str, tuple] = {}
    # Local variable names that have been assigned a `MojoBoundMethod *`
    # value at least once but whose DECLARED C type is not
    # `MojoBoundMethod *` (the var-type-inference join with another
    # branch's plain function-pointer / lambda value collapsed it to
    # `void *`/`int64_t`). A call through such a name must dispatch
    # dynamically (mojo_maybe_bound_call_N) — a bound method needs its
    # `self` re-supplied, a plain fnptr must NOT. Reset per function:
    # local names recycle. See _lower_maybe_bound_call.
    gen._bm_tainted_locals: set = set()
    # Pre-seed known global dicts with their value types so .get() uses the right function.
    # Also seeded from self._global_dict_val_types (Phase 1.7, never
    # reset) for the same reason _elem_types is seeded from
    # _global_elem_types just above — same shadowing exclusion too.
    gen._dict_val_types:  dict[str, str]   = {
        '_BIN_OPS': 'char *', '_GD_BIN_OPS': 'char *',
        **{k: v for k, v in gen._global_dict_val_types.items()
           if k not in _reset_locally_bound},
    }  # dict var → value C type
    # dict var/temp → the value C type of the dicts held AS this dict's
    # values (one nesting level down); mirrors _nested_elem_types for lists.
    gen._dict_nested_val_types: dict[str, str] = {}
    gen._struct_layout:   dict[str, str]   = {}  # var_name → STACK|HEAP
    gen._layout_hint:  str             = gimple_solvers.LayoutSolver.HEAP  # for struct constructors
    gen.current_func_name: str         = ''
    gen._loop_depth:   int             = 0   # nesting depth for freq annotations
    # Closure state (set when generating a lifted inner function)
    gen._captures:   dict[str, str]    = {}  # captured var → ctype
    gen._env_param:  str               = ''  # name of env pointer ('_env')
    # Active env pointers for this outer function (inner_name → env_var)
    gen._closure_envs: dict[str, str]  = {}
    # Original inner function name for recursive call detection (set in _gen_lifted_closure)
    gen._inner_func_name: str          = ''
    # C keyword renaming: Python name → C name (for vars that clash with C keywords)
    gen._c_names:    dict[str, str]    = {}
    # Names currently bound by an `except <ExcType> as <name>:` clause in
    # this function (see _emit_except_handler, which adds/removes as it
    # enters/leaves each handler body — mirrors the had_c_name/
    # restore_c_name save-restore convention right next to it so nested/
    # shadowed except-as bindings and sequential try/except blocks in the
    # same function behave correctly). A caught exception object is
    # lowered as a bare `char *` message string (see _gen_stmt_RaiseStmt/
    # _emit_except_handler), not a real struct — so ordinary MemberExpr
    # field dispatch (which keys off `ot`, the C type) can never resolve
    # it. This set lets a MemberExpr's write/read lowering recognize
    # "this receiver is genuinely an except-as-bound exception object"
    # SYNTACTICALLY (the identifier's name, not its `char *` C type) and
    # route it through the dynamic-attribute dispatch machinery, without
    # broadening the type-keyed dispatch condition to match `char *` in
    # general (which is used pervasively for ordinary strings — see
    # bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md's
    # "Residual gap: caught exception objects" section for why that
    # broader fix was rejected as too risky).
    gen._except_as_names: set          = set()
    # Names declared `global` inside this function — reads/writes route to module struct
    gen._func_declared_globals: set    = set()
    # Names declared `nonlocal` inside this function. Same scoping discipline as
    # `_func_declared_globals` (save/restore around a nested body, or a
    # declaration inside an inner function would leak into its parent), but the
    # consequence is different: the names must be captured FROM the enclosing
    # function rather than from the module.
    gen._func_declared_nonlocals: set = set()
    # True only while generating a module's own _toplevel()/_{module}_toplevel()
    # body (see _gen_toplevel) — distinguishes genuine module-scope statements
    # (whose assignments must persist to that module's globals struct) from a
    # real Python function's body (current_func_name is ALSO non-empty there,
    # e.g. '_cas_toplevel', so current_func_name alone can't tell them apart).
    gen._in_toplevel_gen: bool          = False


def _record_sys_path_inserts(gen, source: str, base_dir: str = None) -> None:
    """Statically scan `source` for literal sys.path.insert(N, "...") calls
    and remember each target directory in self._extra_search_paths (highest
    priority in _compile_imported_module). A relative literal is resolved
    against `base_dir` (the file the source came from) — matching how the
    interpreter's actual sys.path.insert call at run time would resolve a
    relative path against the process CWD at that point, approximated here
    at compile time by the importing file's own directory.

    Deliberately `.findall()`, not `for m in PATTERN.finditer(source):
    m.group(1)` — that shape (a `.finditer()` loop over a *named*
    compile-time pattern, called from inside a class method with `self`
    in scope) hits an unrelated, still-unfixed self-hosting codegen gap
    in _gen_for_regex_iter/_gen_for_iter: gcc rejected the self-hosted
    gimple_codegen.py's own compiled output with a parse error even for
    a trivial empty loop body and even substituting an already-proven
    pattern (_TOKEN_RE) — so the break isn't specific to this pattern or
    this body, only to that (method-scope regex-finditer-loop) combination.
    `.findall()` returns a plain list of the captured strings directly
    and goes through ordinary list iteration instead, sidestepping the
    gap entirely; `.group(n)` with an argument isn't self-host-supported
    either way (see _gen_for_regex_iter's docstring), so `.findall()`
    loses nothing here — this pattern only has the one capture group."""
    # `sys.path.insert(...)` is a module-init statement — always in the first
    # few KB of a file, never buried deep. Bound the regex scan to a head
    # slice: a cheap `path.insert` substring gate skips it entirely for the
    # (vast) majority of modules, and the slice keeps the recursive (CPS)
    # regex matcher — `re_match_cont`/`re_match_node`, which recurses per
    # input position / per quantifier repetition — from being run over
    # 100-250KB of a big compiler module (gimple_codegen.py etc.) on the
    # self-hosted compiled path, where that recursion depth blows the 8MB
    # main-thread stack (EXC_BAD_ACCESS on the guard page). Any real
    # `sys.path.insert` past 8KB is already outside every observed shape.
    _head = source if len(source) <= 8192 else source[:8192]
    if 'path.insert' not in _head:
        return
    source = _head
    for p in gimple_codegen._SYS_PATH_INSERT_RE.findall(source):
        if base_dir and not gimple_ctypes.os.path.isabs(p):
            p = gimple_ctypes.os.path.join(base_dir, p)
        if p not in gen._extra_search_paths:
            gen._extra_search_paths.append(p)
    # The os.path.dirname(__file__) shape: `__file__` at compile time IS
    # `base_dir`'s file, so os.path.dirname(__file__) == base_dir itself;
    # a trailing relative literal (e.g. "..") joins onto that. No literal
    # at all (bare `os.path.dirname(__file__)`) means base_dir unchanged.
    if base_dir:
        for rel in gimple_codegen._SYS_PATH_INSERT_DIRNAME_RE.findall(source):
            p = gimple_ctypes.os.path.normpath(gimple_ctypes.os.path.join(base_dir, rel)) if rel else base_dir
            if p not in gen._extra_search_paths:
                gen._extra_search_paths.append(p)


def _compile_link_inline_cpp_unit(gen, cpp_code: str):
    """Compile a transitively-imported module's own self-contained
    `generated_cpp` (a plain, non-generic top-level generator/async
    function's C++20 coroutine translation unit -- see
    `_compile_imported_module`'s call site, link mode's `_link_inline_
    modules` fallback) to a CAS-cached object with g++, and return its
    path (or None on any failure -- link-mode's own convention: never
    let a companion-object build failure abort the whole compile, the
    caller already checks for None).

    Mirrors driver.py's `_build_client_cpp_object` (the root module's
    OWN companion .cpp) and monomorphize.instantiate's identical per-
    instantiation cpp build (an elaborated generic's own coroutine
    unit) -- same "compile this self-contained generated_cpp text to
    an object" operation, a third call site for it rather than a
    fourth independent reimplementation (CLAUDE.md: consolidate, don't
    duplicate) -- kept as its own small method (not literally imported
    from driver.py) only because driver.py imports FROM gimple_codegen.
    py already (compile_linked), so the reverse import would be
    circular; the CAS key scheme, flags, and g++ invocation are
    deliberately identical to driver.py's version so the two draw from
    (and populate) the exact same CAS entries for byte-identical cpp
    text."""
    try:
        import cas
        import subprocess
        import tempfile
        from build_config import find_gxx
    except Exception as e:
        gimple_ctypes._debug_note('cannot compile link-mode inline-module cpp unit '
                    '(import failure)', e)
        return None
    try:
        gxx = find_gxx()
        runtime_dir = gimple_ctypes.os.path.join(gimple_ctypes.os.path.dirname(gimple_ctypes.os.path.abspath(__file__)), 'runtime')
        cpp_flags = ('-std=c++20', '-fPIC', f'-I{runtime_dir}')
        key = cas.module_key(cpp_code, [], gxx, cpp_flags)

        def _build_fn():
            wd = tempfile.mkdtemp(prefix='mojo_linkmod_cpp_')
            cf = gimple_ctypes.os.path.join(wd, 'link_inline_module.cpp')
            of = gimple_ctypes.os.path.join(wd, 'link_inline_module.o')
            with open(cf, 'w') as f:
                f.write(cpp_code)
            subprocess.run([gxx, *cpp_flags, '-c', '-o', of, cf], check=True,
                           capture_output=True)
            with open(of, 'rb') as f:
                return f.read()

        obj, _hit = cas.get_or_build(key, '.o', _build_fn)
        return obj
    except Exception as e:
        gimple_ctypes._debug_note('failed to compile link-mode inline-module cpp unit', e)
        return None


def _emit_stdlib_import_externs(gen, stmts) -> None:
    """Scan from-import stmts and emit extern declarations for concrete
    functions found via load_module (text-only extraction — no dylib builds,
    no recursion). Populates _link_import_decl_list and registers types so
    call sites lower correctly. Safe to call for any module; no-ops if a
    symbol is already registered."""
    seen = set(gen.func_return_types.keys()) | set(gen.imported_symbols.keys())

    # Determine the package prefix for resolving relative imports (e.g.
    # `._swisstable` → `std.collections._swisstable` when compiling
    # `std/collections/dict.mojo`).
    _pkg_prefix = ''
    if gen._current_filename:
        from module_loader import STDLIB_PATH
        # Avoid runtime 'import os' — the compiled binary can't resolve
        # Python's os module.  Use string ops instead of os.path.relpath.
        _fn = gen._current_filename
        _sp = STDLIB_PATH
        # Normalize trailing separators
        if _fn.endswith('/') or _fn.endswith('\\'):
            _fn = _fn[:-1]
        if _sp.endswith('/') or _sp.endswith('\\'):
            _sp = _sp[:-1]
        if _fn.startswith(_sp + '/') or _fn.startswith(_sp + '\\'):
            rel = _fn[len(_sp)+1:]
            parts = rel.replace('\\', '/').split('/')
            if len(parts) > 1:
                _pkg_prefix = '.'.join(parts[:-1]) + '.'

    # Names that conflict with GCC built-ins or C stdlib declarations — skip
    # emitting externs for these even if load_module finds them.
    _C_BUILTINS = frozenset({
        'abort', 'atof', 'atoi', 'atol', 'atoll', 'exit', '_exit',
        'fclose', 'fopen', 'fread', 'fwrite', 'fseek', 'ftell', 'fflush',
        'fma', 'fmaf', 'pow', 'powf', 'sqrt', 'sqrtf',
        'sin', 'sinf', 'cos', 'cosf', 'tan', 'tanf',
        'exp', 'expf', 'log', 'logf', 'log2', 'log2f', 'log10', 'log10f',
        'ceil', 'ceilf', 'floor', 'floorf', 'round', 'roundf',
        'abs', 'fabs', 'fabsf', 'fmod', 'fmodf',
        'trunc', 'nan',
        'malloc', 'free', 'realloc', 'calloc',
        'pclose', 'popen', 'dlclose', 'dlopen', 'dlsym', 'dlerror',
        'printf', 'fprintf', 'sprintf', 'snprintf', 'scanf', 'sscanf',
        'strlen', 'strcpy', 'strncpy', 'strcmp', 'strncmp',
        'strcat', 'strncat', 'strstr', 'strchr', 'strrchr',
        'memcpy', 'memmove', 'memset', 'memcmp',
        'stat', 'lstat', 'fstat', 'open', 'close', 'read', 'write',
        'max', 'min', 'chr', 'ord',
        'fdopen', 'fileno', 'tmpfile', 'tmpnam',
        'getenv', 'setenv', 'unsetenv', 'putenv',
        'isatty', 'getuid', 'getpid', 'getppid',
        # Linux-specific libc wrappers that collide with GCC declarations
        'get_errno', 'set_errno', '_getpw_linux', '_lstat_linux_x86_64',
        '_stat_linux_x86_64', '_fstat_linux_x86_64',
    })

    def _resolve_relative(mod, pkg_prefix):
        """Resolve relative import: count leading dots, go up that many levels."""
        if not mod.startswith('.'):
            return mod
        dots = len(mod) - len(mod.lstrip('.'))
        rest = mod.lstrip('.')
        parts = pkg_prefix.rstrip('.').split('.')
        # dots=1 → current package (no level up), dots=2 → parent, etc.
        up = dots - 1
        if up > 0:
            parts = parts[:-up] if up < len(parts) else []
        base = '.'.join(parts)
        return (base + '.' + rest) if (base and rest) else (base or rest)

    for stmt in stmts:
        if not isinstance(stmt, gimple_ctypes.FromImportStmt):
            continue
        mod = stmt.module
        # Resolve relative imports: '._foo' → 'std.pkg._foo', '.._foo' → 'std.parent._foo'
        if mod.startswith('.'):
            mod = _resolve_relative(mod, _pkg_prefix)
        # A bare `from <name> import ...` naming one of the compiler's own
        # `.py` sibling modules (build_config, gimple_codegen, ...) — not a
        # stdlib/test module. `load_module` raises "Only stdlib and test
        # imports supported" for those, and the compiled backend's
        # try/except around this call does NOT reliably catch a raised
        # ValueError, so `./mojoc --dump fire.py` died on
        # `from build_config import ...`. Pre-filter: those siblings carry
        # no stdlib externs anyway.
        # Guard BEFORE calling, not just try/except around the call: this
        # codegen's compiled `try`/`except` does not reliably catch a
        # raised exception, so a real (non-mojo-stdlib) Python import —
        # `from dataclasses import dataclass`, real stdlib source
        # myinterpreter.py itself uses — reached module_loader's `raise`
        # UNCAUGHT and crashed the whole `MOJO_NO_SHIM=1 --dump` compile.
        # See ModuleLoader.can_resolve_module_path's docstring.
        import module_loader as _mlmod0
        if not _mlmod0.can_resolve_module_path(mod):
            continue
        try:
            exports = gimple_ctypes.load_module(mod)
        except Exception as e:
            gimple_ctypes._debug_note(f'load_module({mod!r}) failed; skipping import', e)
            continue
        if not exports:
            continue
        for _fip9 in (getattr(stmt, 'name_alias_strs', None) or []):
            name = gimple_ctypes._fi_name(_fip9)
            alias = gimple_ctypes._fi_alias(_fip9)
            sym = alias if alias else name
            # Record this function's home module (SB-1 fix, _func_qualifier)
            # UNCONDITIONALLY — deliberately BEFORE the `sym in seen`
            # early-exit below. `seen` (and func_return_types, which
            # seeds it) is SHARED across every nested temp_gen a
            # do_imports=True build spins up (_compile_imported_module:
            # `temp_gen.func_return_types = self.func_return_types`), so
            # by the time a SECOND module's own FromImportStmt scan for
            # the SAME bare name runs, `sym in seen` is already true
            # (some earlier module already registered it) and an early
            # `continue` here would skip this registration entirely —
            # exactly the bug that made _own_imported_func_home stay
            # empty for beta_wrapper.mojo's own compile in the repro
            # below, silently leaving its call site to fall through to
            # the shared, first-registered-wins _imported_func_home
            # fallback (alpha_module's qualifier) instead of its own
            # correct one. This registration is independent of `exports`/
            # `info`/`sig` (needs only `mod` + `sym`) and setdefault-safe,
            # so computing it before the early-exit is always correct.
            # Resolved via module_loader's OWN resolve_module_path (the
            # exact resolution `load_module(mod)` below just used to find
            # this module's exports) rather than self._parsed_import/
            # imports' process-global Resolver singleton: that
            # singleton's search path is mutated by whichever test/build
            # last called imports.reset_resolver(path=...) and is NOT
            # necessarily scoped to this compile, so resolving through it
            # here was observed to silently return no path (test order-
            # dependent — a prior test's reset_resolver(path=[some other
            # tempdir]) left the global resolver unable to find a
            # runtime/-relative sibling module like 'corolike'),
            # producing an unqualified qualifier that disagreed with the
            # defining module's own (correctly qualified) compile and
            # broke the link. module_loader's resolve_module_path has no
            # such global mutable state — it's a pure function of
            # STDLIB_PATH/TEST_PATH.
            import module_loader as _mlmod
            _imp_path = _mlmod._module_loader.resolve_module_path(mod)
            if _imp_path and gimple_ctypes.os.path.exists(_imp_path):
                _qual = _mlmod.module_name_for_path(_imp_path)
                if _qual:
                    # _own_imported_func_home (per-instance, see its own
                    # comment): THIS module's own FromImportStmt is
                    # authoritative for this bare name within this
                    # module's own body — must win over any OTHER
                    # module's claim on the same bare name in the shared
                    # _imported_func_home fallback.
                    gen._note_own_func_home(sym, _qual)
            if sym in seen or sym in _C_BUILTINS or (
                    sym in gen._LIBC_DECLARED
                    and sym not in gen._NEEDS_SELF_EXTERN):
                continue
            info = exports.get(name)
            if not info:
                continue
            sig = info.get('signature')
            if not sig:
                continue
            ret = info.get('c_return_type', 'int64_t')
            c_params = info.get('c_parameters') or []
            ptypes = [' '.join(cp.split()[:-1]) if len(cp.split()) > 1 else cp
                      for cp in c_params]
            # A name in _NEEDS_SELF_EXTERN has ONE true C prototype, pinned in
            # _LIBC_SIGS. The export-derived signature (module_loader maps the
            # exporting Mojo wrapper's Int64-level types to int64_t text) can
            # disagree with that pin — e.g. std.sys._libc's `def dup(oldfd:
            # c_int)` exports `int64_t dup (int64_t oldfd)`, while every bare-
            # call site records the pinned `extern int dup (int);` into
            # _external_protos via _ensure_libc_self_extern — leaving TWO
            # conflicting declarations of the same libc symbol in one TU (hard
            # gcc "conflicting types for 'dup'/'pipe'" in the stdlib dylib's
            # std_io_io/std_os_process units). Pin the recorded + emitted
            # signature to the same libc truth so every declaration path for
            # these names agrees.
            if sym in gen._NEEDS_SELF_EXTERN:
                _pin = gen._LIBC_SIGS.get(sym)
                if _pin:
                    ret = _pin[0]
                    ptypes = list(_pin[1])
                    sig = f"{ret} {name} ({', '.join(ptypes)})"
            gen.func_return_types[sym] = ret
            gen.func_param_types[sym] = ptypes
            gen.imported_symbols[sym] = {
                'module': mod, 'original_name': name,
                'c_return_type': ret, 'signature': sig,
            }
            # When imported with an alias, replace the original name in the sig
            # so the extern matches the alias name used at call sites.
            if alias and name != alias:
                sig = gimple_ctypes._replace_first_ident(sig, name, alias)
            # Overload-mangle the imported function's name in the extern so it
            # matches the (mangled) call sites and the defining module's symbol.
            # Only for genuinely mangled functions — reserved renames (pipe →
            # mojo_pipe) are handled by other decl paths and must not change here.
            if gen._func_mangleable(sym):
                _csym = gen._func_csym(sym)
                if _csym != sym:
                    sig = gimple_ctypes._replace_first_ident(sig, sym, _csym)
            # Guard the extern with #ifndef so the pre-defined stubs (which use
            # the same guard macro _MOJO_STUB_<NAME>) don't produce a second
            # conflicting declaration. If the extern is emitted here, the stub
            # will see the macro already defined and skip itself.
            #
            # ONLY for genuine `std`/`std.*` modules, NOT a bare test-path
            # sibling (`from test_helper import ...`). `can_resolve_module_path`
            # accepts both (stdlib, or a module under TEST_PATH =
            # `os.path.join(HERE, 'runtime')`), but `HERE` is
            # `dirname(abspath(__file__))` — the SCRIPT's dir for the python3
            # reference vs the process CWD for the self-hosted binary. So a
            # `stage2`-CWD build has TEST_PATH=`stage2/runtime`, `can_resolve`
            # is False for `test_helper`, and this block was skipped natively
            # while the python3 reference (TEST_PATH=repo/runtime) emitted it —
            # a real stage1-vs-stage2 `make bootstrap` divergence
            # (example_imports.mojo). The block is REDUNDANT for such a
            # sibling anyway: `_register_sym`'s own `/* from <mod> */` extern
            # (emitted for every resolved FromImportStmt) already declares the
            # same symbol. Restricting to `std` makes both paths agree; the
            # `_own_imported_func_home`/`func_return_types` bookkeeping above
            # still runs for every module.
            if mod == 'std' or mod.startswith('std.'):
                guard = gimple_ctypes._stub_guard_name(sym)
                decl = f'#ifndef {guard}\n#define {guard}\nextern {sig};\n#endif'
                gen._link_import_decl_list.append(decl)
            seen.add(sym)


def _emit_imported_global_accessors(gen, stmts) -> None:
    """Bare `from X import <module_scope_var>` — BUG-2026-009. See
    `_imported_global_accessors`'s own docstring and module_loader.py's
    'kind': 'global_var' export entries (module_loader._VAR_GLOBAL_RE)
    for the full picture; this is the consuming half.

    Resolution mirrors gen_module's own "Process imports" sibling
    handling (module_loader.load_module for stdlib/test modules,
    falling back to `_local_sibling_module_exports` for a local project
    sibling file — the exact shape `mojo dylib`'s per-module-
    independent compile needs, since a local sibling like box.3d/
    game's `engine_world.mojo` is never in module_loader's tracked
    stdlib/test set). Safe to call unconditionally (like
    `_emit_stdlib_import_externs`, right next to which this runs): a
    module with no `global_var`-kind import is an untouched no-op.
    """
    for stmt in stmts:
        if not isinstance(stmt, gimple_ctypes.FromImportStmt):
            continue
        # `_as_str`: a bare `.module` FIELD read used unguarded below in
        # string concatenation (`mod + '.py'`) and as a resolver
        # argument — the established self-hosted trap (working `==` but
        # corrupted downstream string ops) for AST struct-field reads.
        mod = _as_str(stmt.module)
        # A bare `from <name> import ...` naming a compiler `.py` sibling
        # (build_config, ...): `load_module` raises "Only stdlib and test
        # imports supported" and the compiled backend's `except Exception`
        # around it does not reliably catch a raised ValueError. Route
        # straight to the local-sibling path (which the fallback below
        # would reach anyway).
        _is_py_sibling = ('.' not in mod and not mod.startswith('std')
                          and gimple_ctypes.os.path.isfile(gimple_ctypes.os.path.join(
                              gimple_codegen._SELFHOST_DIR, mod + '.py')))
        import module_loader as _mlmod
        # A genuine non-mojo-stdlib Python import (e.g. `dataclasses`,
        # real stdlib source myinterpreter.py itself uses) is neither a
        # `.py` sibling nor mojo-stdlib-resolvable — GUARD before calling
        # `load_module`/`resolve_module_path` rather than relying on the
        # try/except below, which (see the comment above) does not
        # reliably catch a raised exception on the compiled backend.
        if _is_py_sibling or not _mlmod.can_resolve_module_path(mod):
            exports, qual = gen._local_sibling_module_exports(mod)
        else:
            try:
                exports = gimple_ctypes.load_module(mod)
                qual = None
                _imp_path = _mlmod._module_loader.resolve_module_path(mod)
                if _imp_path and gimple_ctypes.os.path.exists(_imp_path):
                    qual = _mlmod.module_name_for_path(_imp_path)
            except Exception:
                exports, qual = gen._local_sibling_module_exports(mod)
        if (not exports or not qual):
            # Self-host bootstrap: `from gimple_codegen import _C_RESERVED_
            # FUNCS` names a sibling `.py` compiler module that neither
            # module_loader (stdlib/test only) nor imports.resolve_source
            # (.mojo only) can resolve. Scan it directly for its
            # frozenset/set module globals so a re-exported set doesn't fall
            # to the codegen "undeclared -> (int64_t)0" NULL-set crash.
            # Scoped to global_var consumption below — no fn/struct/overload
            # signature is taken from this path.
            import module_loader as _mlmod2
            # `gimple_codegen._SELFHOST_DIR`, not `_mlmod2.__file__`: a
            # compiled-in module object has no `__file__` attribute, so
            # `os.path.abspath(_mlmod2.__file__)` raised `AttributeError:
            # __file__` and killed the whole `./mojoc --dump fire.py`
            # self-compile. `_SELFHOST_DIR` is the same sibling directory
            # (it's `dirname(abspath(gimple_codegen.__file__))`, and every
            # compiler `.py` lives in one directory) and is already the
            # value the rest of the self-host machinery keys off.
            _sd = gimple_codegen._SELFHOST_DIR
            # Plain `+` concatenation, NOT `os.path.join(_sd, ...)`: the
            # os.path.join RETURN VALUE itself came back with a working
            # `os.path.isfile()`/`open()` (content intact) but a
            # corrupted `len()` self-hosted — a real, independently
            # confirmed bug (fixed here), though NOT the cause of the
            # `exports.get(name)` misses documented just below: that
            # symptom is UNCHANGED with this fix applied, so its root
            # cause is deeper still (see the tracking doc).
            _cand = _sd + '/' + mod.split('.')[-1] + '.py'
            if gimple_ctypes.os.path.isfile(_cand):
                exports = _mlmod2._module_loader.load_module_from_path(_cand)
                qual = _mlmod2.module_name_for_path(_cand)
        if not exports or not qual:
            continue
        # `exports.get(name)` misses for a stable, reproducible SUBSET
        # of gimple_ctypes.py's real `global_var` exports self-hosted
        # (confirmed via aside/bside on gimple_exprtypes.py --dump: 2 of
        # 6 imported names always miss, the same 2 every run) even
        # though: `name` is byte-correct (`_fi_name` verified via
        # `len()`), rewriting `_fi_name` to build the string via
        # character-by-character concatenation instead of slicing made
        # no difference, and fixing the `os.path.join` corruption above
        # made no difference either. Root cause NOT YET FOUND — likely
        # inside `module_loader.py`'s own regex-based export scan or its
        # `_path_cache` dict, not in this function. See bugs/CODEGEN_
        # selfhost_actual_types_identifier_field_key.md for the full
        # investigation trail and how to continue it (the aside/bside +
        # MOJO_DEBUG-gated `_debug_note` technique used to find this).
        for _fip10 in (getattr(stmt, 'name_alias_strs', None) or []):
            name = gimple_ctypes._fi_name(_fip10)
            alias = gimple_ctypes._fi_alias(_fip10)
            info = exports.get(name)
            if not info or info.get('kind') != 'global_var':
                continue
            sym = alias if alias else name
            if sym in gen._imported_global_accessors:
                continue
            ctype = info.get('c_return_type', 'int64_t')
            # A re-exported global (`from gimple_codegen import _C_RESERVED_
            # FUNCS`, itself `from gimple_ctypes import ...`) is accessed
            # through the accessor its TRUE defining module emits — use the
            # home path the scanner recorded, not the module named in this
            # `from` statement.
            _home_qual = qual
            _hp = info.get('home_module_path')
            if _hp:
                import module_loader as _mlmod_g
                _home_qual = _mlmod_g.module_name_for_path(_hp) or qual
            accessor_csym = (f'{gimple_ctypes._c_field_name(_home_qual)}__mojo_global_get_'
                              f'{gimple_ctypes._c_field_name(name)}')
            gen._imported_global_accessors[sym] = (ctype, accessor_csym)
            guard = gimple_ctypes._stub_guard_name(accessor_csym)
            decl = (f'#ifndef {guard}\n#define {guard}\n'
                    f'extern {ctype} {accessor_csym} (void);\n#endif')
            gen._link_import_decl_list.append(decl)


# Runtime functions that ALWAYS return a container they just allocated and
# keep no other reference to. Each was checked against its source in
# runtime/fire_runtime.c (every `return` yields a value created by
# mojo_{list,dict,set}_new/_copy in the same function). NOT here:
# mojo_set_sorted (one return is a call whose result ownership is unclear), any
# in-place sort that returns its argument, and anything that may hand back a
# stored container.
_FRESH_CONTAINER_RETURNS = frozenset([
    'mojo_list_slice', 'mojo_list_copy', 'mojo_list_concat', 'mojo_list_repeat',
    'mojo_reversed', 'mojo_str_split', 'mojo_str_splitlines', 'mojo_range',
    'mojo_range3', 'mojo_dict_copy', 'mojo_set_copy', 'mojo_dict_keys',
    'mojo_dict_values', 'mojo_dict_items', 'mojo_dict_items_int', 'mojo_zip', 'mojo_set_union',
    'mojo_set_intersection', 'mojo_set_difference',
])


# The subset of `_FRESH_CONTAINER_RETURNS` whose result is a list that SOLELY
# owns its string ELEMENTS — every one freshly allocated by that function, and
# nothing else holding a pointer to any of them. Those elements are invisible
# to `mojo_list_free`, which releases the container and leaves them behind
# (`mojo_list_append_str` stores the pointer it is given and never copies it),
# so an owned list built by one of these is torn down with
# `mojo_list_free_owned_strs` instead. Membership is read off each function's
# source, not inferred from its result type; a function not named here keeps
# the plain free, which is the safe direction (a missed free leaks, a wrong
# one frees a string literal).
#
# `mojo_str_rsplit` is deliberately absent: it hands its result the very same
# pointers its own scratch list holds (see its comment in fire_runtime.c), so
# it is not a sole owner. Neither is any list built by `extend` or by reading
# a key back out of a dict, which is the common case and is borrowed.
_OWNS_STR_ELEMS = frozenset([
    'mojo_str_split', 'mojo_str_splitlines',
])


# Runtime functions that ALWAYS return a string they just allocated. Unlike the
# container list this one is EARNED, not assumed: a mechanical pass over every
# `char *`-returning function in runtime/fire_runtime.c kept only those whose every
# `return` is a value allocated by malloc/calloc/strdup in that same function.
# Notably absent, because they return their own argument or a static string in
# an edge case (a free() of either would crash): string_upper, string_lower,
# string_strip, mojo_str_rstrip, mojo_str_lstrip_chars, mojo_str_expandtabs,
# _str_pad, mojo_str_join (returns "" for an empty list), mojo_repr_float
# ("nan"/"inf"). mojo_repr_int is absent too (its comment says it reuses a buffer).
# mojo_char_to_str is absent on purpose: it returns one of 256 shared IMMORTAL
# one-character strings (a malloc per character of every string scan was the
# bulk of the self-hosted tokenizer's memory), so a free() of it would crash.
_FRESH_STRING_RETURNS = frozenset([
    'mojo_str_cat', 'mojo_str_from_int', 'mojo_cstr_slice',
    'mojo_cstr_repeat', 'mojo_cstr_reverse', 'mojo_repr_str',
    'mojo_hex', 'mojo_oct', 'mojo_bin',
    # The str methods: each returns a copy the caller owns, never its receiver
    # (runtime/fire_runtime.c, `_str_fresh_copy`).
    'string_upper', 'string_lower', 'string_strip', 'mojo_str_lstrip',
    'mojo_str_rstrip', 'mojo_str_lstrip_chars', 'mojo_str_rstrip_chars',
    'mojo_str_rjust', 'mojo_str_ljust', 'mojo_str_center',
    'mojo_str_expandtabs', 'mojo_str_join',
])


def note_fresh_result(gen, t: str) -> None:
    """A container-display lowering (`[...]`, `{...}`, a comprehension) calls
    this with the temp it is about to return: the display always builds a new
    container, so the value is fresh for whoever consumes it next."""
    gen._fresh_vals.add(t)


def is_fresh_container_operand(gen, node, val: str) -> bool:
    """True iff `val`, the lowered value of operand expression `node`, is a
    value NOTHING else can reference — a container or a string — so the code
    that consumes it may free it. Two conditions, both required:
      - `node` is a kind of expression that produces a value (a display, a
        call, a slice, a `+`) — never an identifier or a field read, which
        merely name a value somebody else owns; and
      - `val` is a value a fresh-producing action created and that no consumer
        has claimed yet (`_fresh_vals`). A temp is never bound to a name or
        stored by the code that produces it, and a consumer removes it from the
        set the moment it frees or claims it.
    Freeing a value that fails either test would be a use-after-free, so the
    default answer is False."""
    if val == '' or val not in gen._fresh_vals:
        return False
    return isinstance(node, (ListExpr, DictExpr, SetExpr, Comprehension,
                             CallExpr, SubscriptExpr, SliceExpr, BinaryOp,
                             TstringLiteral))


def owned_free_fn_for(gen, val: str, ctype: str) -> str:
    """The free for ONE value, not for one type: a list built by a function in
    `_OWNS_STR_ELEMS` also owns the strings in it, and they are invisible to
    `mojo_list_free`; and a fresh STRING is a plain malloc block, so the
    container table's blank answer for `char *` is not "nothing to free".
    Every place that emits a free for a specific lowered value goes through
    here so the choice is made in exactly one spot."""
    if ctype == 'MojoList *' and val in gen._owned_str_elem_vals:
        return 'mojo_list_free_owned_strs'
    if ctype == 'char *':
        # Every producer that puts a `char *` in `_fresh_vals` allocates it:
        # `_FRESH_STRING_RETURNS` (each read off the runtime's own source), a
        # module function `analyze_returns_fresh` proved returns a fresh
        # string, and `_char_replace_impl` (always a copy). None of them can
        # return its own argument, which is the case a `free` would crash on,
        # and none of them is a string LITERAL (those are in `_slit_N` and
        # never reach here — a literal is not the lowered value of a call).
        return 'free'
    return _owned_free_runtime_fn(ctype)


def owned_push_fn_for(gen, val: str, ctype: str) -> str:
    """The cleanup thunk that matches `owned_free_fn_for` — the two must name
    the same teardown or an exception would unwind a value differently from the
    normal path."""
    if ctype == 'MojoList *' and val in gen._owned_str_elem_vals:
        return 'mojo_cleanup_push_list_strs'
    return _owned_push_runtime_fn(ctype)


def free_fresh_container(gen, val: str, ctype: str) -> None:
    """Free a fresh container operand after its consumer has read it, and
    forget it so it can never be freed twice."""
    fn = owned_free_fn_for(gen, val, ctype)
    if fn != '':
        gen._emit(f"  {fn} ({val});")
        gen._fresh_vals.discard(val)
        gen._owned_str_elem_vals.discard(val)


def claim_loop_iterable_temp(gen, node, val: str, ctype: str) -> None:
    """`for x in <fresh container>:` — the iterable is consumed only by the
    loop, so it is a scoped entry that lives until the loop STATEMENT ends
    (`emit_statement_temp_frees`), which covers a normal exit, `break`, the
    `else:` clause and (via the live list) `return`. Registered at the OUTER
    loop depth, so a `break`/`continue` inside the loop body never frees it.
    Its cleanup thunk keeps an exception unwinding through the loop from
    leaking it."""
    if not is_fresh_container_operand(gen, node, val):
        return
    push_fn = owned_push_fn_for(gen, val, ctype)
    free_fn = owned_free_fn_for(gen, val, ctype)
    if push_fn == '' or free_fn == '':
        return
    gen._emit(f"  {push_fn} ({val});")
    _scope_register(gen, val, free_fn)
    gen._fresh_vals.discard(val)
    gen._owned_str_elem_vals.discard(val)


def emit_statement_temp_frees(gen, mark: int) -> None:
    """After a statement that may have registered temporaries (a `for`), free
    those still live beyond `mark` and forget them."""
    if len(gen._scope_live) > mark:
        _emit_scope_end(gen, mark)


def _new_bb(gen) -> str:
    gen.bb_counter += 1
    return f"bb_{gen.bb_counter}"


def _emit(gen, line: str):
    gen.body_lines.append(line)
    # Track values produced by a runtime call that always returns a brand-new
    # container (see `_FRESH_CONTAINER_RETURNS`). A consumer that receives
    # exactly such a value, from an operand node that can only have produced
    # it, may free it once it has read it.
    _fi = line.find(' = mojo_')
    if _fi < 0:
        _fi = line.find(' = string_')
    if _fi > 0:
        _rest = line[_fi + 3:]
        _pi = _rest.find(' (')
        if _pi > 0 and (_rest[:_pi] in _FRESH_CONTAINER_RETURNS
                        or _rest[:_pi] in _FRESH_STRING_RETURNS):
            gen._fresh_vals.add(line[:_fi].strip())
            if _rest[:_pi] in _OWNS_STR_ELEMS:
                gen._owned_str_elem_vals.add(line[:_fi].strip())
    # Track whether this is a terminal statement (can't have code after it)
    stripped = line.strip()
    if stripped.startswith('return ') or stripped.startswith('goto ') or stripped == 'return;':
        gen._last_was_terminal = True
    else:
        gen._last_was_terminal = False




def _elem_of(gen, name: str) -> str:
    """Element type for a container variable."""
    # First, check if this is an int64_t-stored pointer with tracked element type
    if name in gen._elem_types:
        _v = gen._elem_types[name]
        # On the self-hosted path a metadata writer can leave an erased
        # sentinel here (`-1` / a tiny value) — the slot was stored via
        # `mojo_dict_set_int` after its value type unified to int64_t, so
        # `mojo_dict_get_str` hands back a bogus `char *`. `_as_str` can't
        # fix a genuine `-1`; `_declare_var`'s `mojo_str_cat` would then
        # `strlen()` it (hard segfault on the single-TU `--dump
        # myinterpreter.py`). Range-check the raw value; `isinstance`-gate
        # keeps CPython (where `_as_int` is identity → a `str`) unaffected.
        if not _ptr_slot_in_range(_v):
            return 'int64_t'
        return _as_str(_v)
    # If no tracked element type, return default
    return 'int64_t'


def _dict_val_of(gen, name: str) -> str:
    """Value C type for a dict variable."""
    return gen._dict_val_types.get(name, 'int64_t')


_CAST_ONLY_RE = re.compile(r'^\(\s*[A-Za-z_][A-Za-z0-9_ ]*\*?\s*\)\s*\(?\s*'
                           r'([A-Za-z_][A-Za-z0-9_]*)\s*\)?$')


def _dict_val_of_expr(gen, expr) -> str:
    """The recorded dict VALUE type of an already-emitted operand EXPRESSION,
    or None when nothing is recorded for it.

    `_dict_val_of` keys on a source-level name, which is all a subscript's
    receiver ever is. A binary operator's operands are expressions — the
    `mojo_environ_dict ()` call, a cast of a variable to the dict pointer type
    — so unwrap the pointer casts the operator lowering wraps around them
    before giving up. Returns None rather than the `int64_t` default on
    purpose: "not recorded" and "recorded as int64_t" are different facts,
    and the caller (the dict-union value-type join) must not confuse them.
    """

    if not isinstance(expr, str):
        return None
    seen = expr
    for _ in range(4):
        hit = gen._dict_val_types.get(seen)
        if hit is not None:
            return hit
        m = _CAST_ONLY_RE.match(seen)
        if m is None:
            return None
        seen = m.group(1)
    return None


def _dict_union_val_type(gen, lv, rv) -> str:
    """Value C type of `lv | rv` when both operands are dicts, else ''.

    `a | b` allocates a NEW dict, so its value type is not recorded anywhere
    by the assignment that follows — and with no record, every later read
    dispatches to `mojo_dict_get_int` and hands back the stored pointer's bit
    pattern. That is why `merged.get(k)` on `env_defaults | os.environ |
    updates` printed an address while `merged[k]` (which reads the same slot
    through the SUBSCRIPT path, fed by the same `_dict_val_types` but keyed
    off the operand) printed the string.

    The join is deliberately NOT TypeLattice.join, which resolves
    int64_t-vs-char* to `char *` and would then truncate every integer the
    union inherited from the other side. Only an AGREEMENT propagates; a
    disagreement means the merged dict is genuinely heterogeneous (Python:
    `{'x': 1} | {'y': 's'}` has mixed value types), and this dict
    representation has one int64_t slot plus a `kind` tag and no static type
    for "either", so those stay unrecorded — the pre-existing behaviour —
    rather than becoming a new silent miscompile. See
    bugs/BUGFIX_ROADMAP.md item 2 for that remaining gap.
    """
    lvt = _dict_val_of_expr(gen, lv)
    if lvt is None:
        return ''
    if lvt == _dict_val_of_expr(gen, rv):
        return lvt
    return ''


def _scalar_arg_is_addressable_local(gen, aval) -> bool:
    """BUG-2026-016's discriminator for _emit_call's scalar->pointer
    coercion: True iff `aval` is a bare identifier that is positively
    known to be a declared LOCAL (or parameter/temp -- anything with a C
    declaration in this function body, which `var_types` tracks for
    exactly those) and is NOT tracked as an opaque pointer handle.

    The conservative exclusions are load-bearing:
      * `_actual_types` -- set precisely when codegen knows an
        int64_t-typed name really holds a struct/container pointer;
        such handles must keep the legacy by-value pass-through.
      * `_global_var_types` -- globals are excluded entirely: an
        int64_t global is the one place "holds a real FFI pointer"
        is common (the legacy branch's own cited case), and aliasing
        writes into a caller's global on behalf of an out-param was
        never the old behavior.
    Everything else reaching the coercion branch with a pointer-typed
    parameter is a genuine value argument -- today silently reinterpreted
    as an address (a near-NULL store -> segfault), per BUG-2026-016."""
    if not isinstance(aval, str):
        return False
    if aval in gen._actual_types or aval in gen._global_var_types:
        return False
    if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', aval) is None:
        return False
    # Codegen temps are excluded on purpose: a temp is where an arbitrary
    # EXPRESSION's value landed (a call result, a folded constant -- e.g.
    # std/collections/list.mojo's `__iter__` passing a null UnsafePointer
    # for `src` lowered to `_t10 = 0`, which must keep reaching the
    # callee AS NULL, not as the address of the dead temp). Only a name
    # that came straight from SOURCE -- a declared local/parameter the
    # user explicitly wrote as the out-param argument -- gets aliased.
    if re.fullmatch(r'_t\d+', aval) is not None:
        return False
    return aval in gen.var_types


def _addressable_to_target(gen, ctype: str, aval: str) -> bool:
    """`UnsafePointer(to=x)`'s discriminator (see `_lower_call`'s handling
    of that plain-call keyword shape in gimple_gen_calls.py) for whether
    `aval` is a bare declared local/parameter whose address can safely be
    taken. Deliberately NOT `_scalar_arg_is_addressable_local` (BUG-2026-
    016's out-parameter-aliasing check): that helper's `_actual_types`/
    `_global_var_types` exclusions exist to tell an opaque handle boxed
    as `int64_t` apart from a genuine numeric local, which only matters
    when `ctype == 'int64_t'` (the ambiguous erasure case) -- reusing it
    unconditionally rejected every well-typed scalar PARAMETER whose
    ctype isn't literally 'int64_t' (any UInt64/Float64/Int32/… param
    gets an `_actual_types` entry purely so OTHER dispatch sites can
    recover its real type -- see the param-registration comment in
    gimple_gen_funcs.py), silently falling through to a null pointer --
    confirmed via std/sys/_amdgpu.mojo's `hsa_signal_add(sig: UInt64,
    ...)`, `UnsafePointer(to=sig)`. A genuinely non-'int64_t' ctype can
    never be a disguised opaque handle in the first place, so the
    `_actual_types` exclusion only still applies for the ambiguous
    'int64_t' case; `_global_var_types` stays excluded unconditionally
    (a module global's own storage is the globals-struct FIELD, not a
    plain C variable -- `&aval` would take the address of a same-named
    but unrelated local shadow, not the real global)."""
    if not isinstance(aval, str):
        return False
    if aval in gen._global_var_types:
        return False
    if ctype == 'int64_t' and aval in gen._actual_types:
        return False
    # The former `re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', aval)` /
    # `re.fullmatch(r'_t\d+', aval)` guards are GONE: `re.fullmatch` is
    # unreliable on the self-hosted path (it returned None for a plain
    # identifier), so EVERY addressable scalar target was rejected and
    # `UnsafePointer(to=value)` emitted a null pointer. They were also
    # redundant — the final `aval in gen.var_types` membership already
    # restricts `aval` to a genuine declared local/parameter name (never a
    # `_tN` temp, which is not stored in `var_types`).
    return aval in gen.var_types


#: Scalar element types a boxed list may be packed into. Deliberately a
#: closed set rather than "anything that ends in ` *`": a `void *`, a `char *`
#: and a struct pointer all end in ` *` too, and none of them is an array of
#: numbers. Packing a list into a `char *` would compile, run, and be wrong in
#: a way no test in the tree would notice, so the gate is a list of names.
_LIST_MARSHAL_ELEMS = frozenset((
    'float', 'double', 'int', 'int32_t', 'int64_t',
    'uint16_t', 'uint32_t', 'uint64_t', 'int16_t', 'uint8_t', 'int8_t',
    '__fp16', '_Bool',
))


def _list_pack_name(elem: str) -> str:
    """The generated pack helper for `elem`. Lives in device_glue so the
    name is computed the same way by the call site and by the emitter that
    defines it -- a name spelled twice is a name that eventually drifts."""
    return _gmi_glue._c_helper_name(elem)


def _list_unpack_name(elem: str) -> str:
    return _gmi_glue._c_unpack_name(elem)


def _emit_call(gen, ret_type: str, result_var: str, fname: str, arg_pairs: list[tuple[str, str]]) -> None:
    """Emit a function call with GIMPLE-valid argument coercions.

    arg_pairs: list of (ctype, varname) for each argument.
    For each argument, if the declared parameter type differs from the
    passed type, emit an intermediate temp with the correct cast.
    """
    fname, arg_pairs = _apply_kw_keys(gen, fname, arg_pairs)
    # Rename certain C library functions to mojo_* wrappers with void* params
    fname = gen._CALL_RENAMES.get(fname, fname)
    sig = gen._KNOWN_SIGS.get(fname)
    if sig:
        param_types = sig[1]
    elif fname in gen._LIBC_SIGS:
        # Raw libc symbol (e.g. pclose): the canonical C signature wins over
        # func_param_types, which a same-named Mojo wrapper may have polluted.
        param_types = gen._LIBC_SIGS[fname][1]
    else:
        # Fall back to a same-file overloaded struct method/constructor's
        # own precomputed signature (Pass 2b-bis) for a call to a sibling
        # overload whose real definition hasn't been emitted yet — see
        # _mangled_signature_ctypes's own comment.
        param_types = gen.func_param_types.get(fname)
        mangled_sig = gen._mangled_signature_ctypes.get(fname)
        # A `*args`-taking method's func_param_types entry starts life
        # ending in the packing sentinel '...' (registered when its body
        # is generated) but gets overwritten with the concrete real
        # signature (e.g. [..., 'MojoList *']) right after, so forward
        # declarations can match exactly (see the "Store per-overload
        # param types" comment near where mangled/param_ctypes_only is
        # built). Every OTHER call site compiled afterwards then sees the
        # concrete signature and silently skips packing, casting the
        # first loose vararg straight to MojoList* instead — found via a
        # real crash: `self._is_kw("as")` (Parser__is_kw, fire_compiler.py)
        # reinterpreted the "as" string's raw pointer bits as a MojoList*
        # and segfaulted deep in mojo_list_contains_str. The sentinel form
        # survives untouched in _mangled_signature_ctypes (Pass 2b-bis
        # registers it for every method, not just overloaded ones), so
        # prefer it here whenever func_param_types's own copy lost it.
        if mangled_sig and mangled_sig[-1] == '...' and (
                not param_types or param_types[-1] != '...'):
            param_types = mangled_sig
        if param_types is None:
            param_types = mangled_sig or []


    # If function takes *args, pack variadic args into a MojoList*
    # '...' = free function varargs (pack all args)
    # [type, '...'] = method varargs (keep leading non-varargs args, pack rest)
    if param_types and param_types[-1] == '...':
        # Find how many leading args to keep (everything before the '...')
        n_fixed = len(param_types) - 1
        fixed_pairs = arg_pairs[:n_fixed]
        varargs = arg_pairs[n_fixed:]
        lst = gen._new_val('MojoList *', "mojo_list_new ()")
        for atype, aval in varargs:
            aval = gen._coerce_to_type(atype, 'int64_t', aval)
            gen._emit(f"  mojo_list_append_int ({lst}, {aval});")
        arg_pairs = fixed_pairs + [('MojoList *', lst)]
        param_types = list(param_types[:-1]) + ['MojoList *']

    # Buffers packed for this call, written back and freed once it is emitted.
    # Local, not on `gen`: `_emit_call` can be re-entered by a nested lowering
    # while a call is still being built, and a shared list would then write the
    # inner call's buffers back at the outer call's return.
    _pending_list_unpacks: list = []
    coerced_args = []
    for i, _apair in enumerate(arg_pairs):
        # `_as_str` on every unpacked slot — a `(ctype, varname)` tuple boxes
        # BOTH slots to int64_t on the self-hosted path, and `ctype` here is
        # C TYPE TEXT: an erased one reaches the `f'({ptype}){aval}'` casts
        # below as the string's own heap ADDRESS, so the emitted C carried
        # `_t34 = (33394789424 *)self;` for a `(Parser *)self` receiver cast
        # — invalid, and different on every run (ASLR). Same chokepoint idea
        # as `_new_temp`/`_safe_coerce_emit`/`_declare_var`, one level up at
        # the coercion loop that feeds them.
        atype = _as_str(_apair[0])
        aval = _as_str(_apair[1])
        ptype = _as_str(param_types[i]) if i < len(param_types) else atype
        # Check if int64_t actually contains a pointer (stored in _actual_types or _global_var_types)
        actual_atype = atype
        if atype == 'int64_t':
            if aval in gen._actual_types:
                actual_atype = gen._actual_types[aval]
            # Also check if it's a global variable that should be cast
            elif aval in gen._global_var_types:
                actual_atype = gen._global_var_types[aval]

        # Only pre-load non-slit globals like _BIN_OPS; slits are already char*.
        if aval in ('_BIN_OPS', '_GD_BIN_OPS'):
            temp = gen._new_val(atype, f'{aval}')
            aval = temp
        elif aval.startswith('_slit_'):
            # Pointer form (char *): direct load, no cast needed.
            temp = gen._new_val('char *', f'{aval}')
            aval = temp
        elif aval.startswith('"') and aval.endswith('"'):
            # Raw C string literal in GIMPLE call — convert to _slit_ variable
            slit_name = gen._str_literal_to_slit(aval)
            temp = gen._new_val('char *', f'{slit_name}')
            aval = temp
        if ptype == atype or ptype == '...':
            # Skip coercion only if C types match exactly
            coerced_args.append(aval)
        elif ptype == actual_atype and atype != ptype:
            # Semantic types match but C types differ (e.g., int64_t → MojoList *)
            # Still need to cast the underlying C type
            ip3 = gen._new_temp('int64_t')
            pp = gen._new_temp(ptype)
            aval_local = gen._ensure_local('int64_t', aval)
            gen._emit(f'  {ip3} = {aval_local};')
            gen._emit(f'  {pp} = ({ptype}){ip3};')
            coerced_args.append(pp)
        elif ptype == 'void *' and actual_atype in ('int', 'int64_t', '_Bool'):
            ip = gen._new_temp('int64_t')
            vp = gen._new_temp('void *')
            if actual_atype == 'int64_t':
                # GIMPLE: can't cast a global int64_t to int64_t (redundant cast fails)
                # Just load the value into a local temp directly
                aval_local = gen._ensure_local('int64_t', aval)
                gen._emit(f'  {ip} = {aval_local};')
            else:
                gen._emit(f'  {ip} = (int64_t){aval};')
            gen._emit(f'  {vp} = (void *){ip};')
            coerced_args.append(vp)
        elif ptype == 'void *' and actual_atype.endswith(' *'):
            vp = gen._new_val('void *', f'(void *){aval}')
            coerced_args.append(vp)
        elif ptype == 'int64_t' and (actual_atype in ('int', '_Bool', 'char *', 'void *') or actual_atype.endswith(' *')):
            ct = gen._new_temp('int64_t')
            if atype == 'char *':
                aval_local = gen._ensure_local('char *', aval)
                ip2 = gen._new_val('void *', f'(void *){aval_local}')
                gen._emit(f'  {ct} = (int64_t){ip2};')
            elif atype == 'void *':
                aval_local = gen._ensure_local('void *', aval)
                gen._emit(f'  {ct} = (int64_t){aval_local};')
            elif atype.endswith(' *'):
                # Any struct pointer → void * → int64_t
                aval_local = gen._ensure_local(atype, aval)
                vp = gen._new_val('void *', f'(void *){aval_local}')
                gen._emit(f'  {ct} = (int64_t){vp};')
            else:
                gen._emit(f'  {ct} = (int64_t){aval};')
            coerced_args.append(ct)
        elif ptype == 'char *' and atype in ('int', 'int64_t', 'char'):
            # A raw single char whose DECLARED type was widened to
            # int64_t (joining another assignment site in the same
            # function — e.g. `qch = stmt[i]` in fire_compiler.py's own
            # `_process_nested_tstrings`) still has its real type
            # tracked in _actual_types (actual_atype, resolved just
            # above) even though the bare `atype` check below can't see
            # it. Checking only `atype == 'char'` missed that case
            # entirely and fell to the `else` branch's raw void*
            # pointer-reinterpretation of the char's numeric byte value
            # — passing e.g. `(char *)0x22` (a garbage address built
            # from `"`'s ASCII code) to `_find_tstring_closing_quote`'s
            # `quote_ch: str` parameter, which then could never actually
            # match a real quote character, so `close` always came back
            # -1 and the caller silently fell through to its "no t/f-
            # string found" fallback. Confirmed via a from-scratch
            # instrumented stage1.ci build: `_find_tstring_closing_
            # quote_7a972f (stmt, i, _t42)`'s `_t42` was exactly this
            # `(char *)(void *)qch` cast, not a real 1-char string.
            if atype == 'char' or actual_atype == 'char':
                # `aval` itself is still C-declared as whatever `atype`
                # says (int64_t when widened) even though it's really a
                # char — cast it to a real `char` lvalue first so the
                # mojo_char_to_str call below isn't passing an int64_t
                # variable where GIMPLE expects an exact `char` match.
                cv = aval if atype == 'char' else gen._new_val('char', f'(char){aval}')
                sv = gen._call_expr('char *', 'mojo_char_to_str', [('char', cv)])
                coerced_args.append(sv)
            elif actual_atype.endswith(' *'):
                # A pointer the codegen POSITIVELY knows this value holds
                # (`_actual_types` / `_global_var_types` recorded a pointer
                # type), just spelled `int64_t` here. Round-trip the bits,
                # exactly as before: the value really is a pointer, so the
                # cast is the identity it has always been.
                vp = gen._new_temp('void *')
                cp = gen._new_temp('char *')
                if atype in ('int',):
                    ip = gen._new_val('int64_t', f'(int64_t){aval}')
                    gen._emit(f'  {vp} = (void *){ip};')
                else:
                    gen._emit(f'  {vp} = (void *){aval};')
                gen._emit(f'  {cp} = (char *){vp};')
                coerced_args.append(cp)
            else:
                # An UNTRACKED int64_t going into a `char *` parameter.
                #
                # `char *` IS this dialect's string slot: `_TYPE_MAP` maps
                # only `str`/`String` to it (`*UInt8` and friends resolve to
                # `uint8_t *`, `None` to `void *`), so a parameter spelled
                # `char *` is a STRING parameter and the callee will hand
                # the word to strlen/strcmp. The annotation is a static
                # PROMISE codegen used to take literally by bit-reinterpreting
                # whatever integer arrived: `Dialog(5)` on
                # `def __init__(self, widgetName: str)` emitted
                # `(char *)(void *)(int64_t)5`, and `mojo_print` then
                # `strlen`ed address 5 -- SIGSEGV, exit -11, no output at
                # all (bugs/CODEGEN_annotated_str_param_given_an_int_
                # segfaults.md). In Python a parameter annotation is
                # documentation, not a cast: `Dialog(5)` is legal and prints
                # `5`.
                #
                # So this is not a place the codegen may decide: in this
                # compiler's scalar body model an int64_t and a `char *` are
                # the same 64 bits, and an untracked word is genuinely
                # ambiguous -- it is a real string handle far more often
                # than not (a lambda parameter, an erased dict value, a
                # getattr result all arrive here with their pointer bits and
                # nothing recorded, and that by-value handle pass-through is
                # load-bearing for the self-host's own compilation).
                # `mojo_cstr_or_int_str` is the model's OWN answer to exactly
                # this question -- it is what `_char_to_cstr` already routes
                # every other int64_t-used-where-a-string-is-needed through --
                # and it is safe in BOTH directions rather than right in
                # only one: a real boxed `char *` comes back as the very same
                # address (the cast's own result), and a genuine integer
                # comes back as its decimal, which is what CPython prints.
                #
                # Deliberately NOT registered with `_cstr_key_src`, so the
                # `mojo_cstr_or_int_release` protocol does not reclaim it:
                # the callee may STORE the pointer (`self.widgetName =
                # widgetName`), and releasing a string the value kept is a
                # use-after-free. The int case therefore keeps its one
                # block, which is this runtime's documented no-free model for
                # a kept string (`mojo_str_from_int`'s own comment) and only
                # happens on the path that used to be a SIGSEGV.
                iv = (aval if atype == 'int64_t'
                      else gen._new_val('int64_t', f'(int64_t){aval}'))
                if aval in getattr(gen, '_int_word_vals', ()):
                    # ...unless the codegen PROVABLY knows this word is an
                    # integer, in which case there is no question to ask and
                    # `mojo_cstr_or_int_str`'s own range test must not be
                    # consulted at all: `mojo_boxed_is_str` calls every
                    # positive int64 in [2^31, 2^47) a pointer, so
                    # `Dialog(3000000000)` would still `strlen` address
                    # 3000000000. `mojo_str_from_int` is that function's own
                    # unconditional integer half, and the KEPT variant rather
                    # than the transient one because the callee owns this
                    # string (see the release note above).
                    sv = gen._call_expr('char *', 'mojo_str_from_int',
                                        [('int64_t', iv)])
                else:
                    sv = gen._call_expr('char *', 'mojo_cstr_or_int_str',
                                        [('int64_t', iv)])
                coerced_args.append(sv)
        elif ptype.endswith(' *') and (actual_atype in ('int', 'int64_t') or atype == 'int64_t'):
            # Parameter expects a pointer; the lowered argument is a plain
            # scalar-typed value. TWO unrelated situations reach this one
            # branch, and they need OPPOSITE handling (BUG-2026-016,
            # box.3d/game):
            #
            # (1) The argument names a real, declared local/temp of THIS
            #     function holding a genuine VALUE (e.g.
            #     `hopper_get_input(h, hin_id, hin_count)` where
            #     `hin_id: UInt64 = 0`): the old code reinterpreted the
            #     value's bits as a pointer (`(uint64_t *)_t2` from the
            #     value 0 -> NULL) and the callee's first store through it
            #     segfaulted. Auto-materialize the argument's ADDRESS
            #     instead (the bug report's option (a)): pass `&hin_id`
            #     so the callee's writes through the out-param land in
            #     the caller's own variable -- true aliasing/write-back,
            #     which is exactly what an out-parameter call means. A
            #     non-lvalue argument (call result temp, expression)
            #     gets the same treatment harmlessly: its temp is
            #     addressable memory, so the callee writes into a
            #     discarded temporary instead of crashing ("an
            #     addressable temporary", per the same report).
            # (2) The argument is an OPAQUE HANDLE boxed in an int64_t
            #     that genuinely must be passed through by value -- the
            #     convention this branch was written for (its comment
            #     cites globals). Those keep today's cast-through
            #     behavior unchanged: handles tracked by _actual_types,
            #     anything living in a global (_global_var_types -- the
            #     cited case, and the one place "int64_t holding a real
            #     FFI pointer" is common), any name we can't positively
            #     identify as a declared local, AND every parameter whose
            #     C type isn't pointer-to-numeric-scalar. That last
            #     exclusion is load-bearing: `char *` parameters are
            #     overwhelmingly STRING parameters in this dialect, and an
            #     int64_t-typed local holding a string handle passed to
            #     one must keep the by-value handle pass-through
            #     (confirmed via make check-selfhost: auto-addressing
            #     those regressed fire.py's own self-compilation with
            #     dozens of GIMPLE errors). Pointer-to-numeric-scalar
            #     (`*UInt64` -> 'uint64_t *', `*Int64` -> 'int64_t *',
            #     ...) is exactly the raw-pointer OUT-parameter spelling
            #     this dialect's FFI/helper surface uses (_mojo_type's
            #     own `*T` mapping), and the only shape BUG-2026-016
            #     reported.
            if (gen._scalar_arg_is_addressable_local(aval)
                    and gimple_ctypes._elem_type(ptype) in gimple_ctypes._PTR_OUT_PARAM_SCALAR_ELEMS
                    and aval in getattr(gen, '_scalar_annotated_locals', ())):
                _ap = gen._new_val(f'{atype} *', f'&{aval}')
                pp = gen._new_temp(ptype)
                gen._emit(f'  {pp} = ({ptype}){_ap};')
                coerced_args.append(pp)
            else:
                # If parameter expects pointer and we have int/int64_t, cast through void*
                # This handles cases where int64_t is an opaque pointer (e.g., from globals)
                ip3 = gen._new_temp('int64_t')
                pp = gen._new_temp(ptype)
                if actual_atype == 'int64_t' or atype == 'int64_t':
                    # GIMPLE: can't redundantly cast int64_t to int64_t when source is global
                    aval_local = gen._ensure_local('int64_t', aval)
                    gen._emit(f'  {ip3} = {aval_local};')
                else:
                    gen._emit(f'  {ip3} = (int64_t){aval};')
                gen._emit(f'  {pp} = ({ptype}){ip3};')
                coerced_args.append(pp)
        elif ptype == 'int64_t' and atype.endswith(' *'):
            # pointer passed where int64_t expected — cast via int64_t
            ip = gen._new_val('int64_t', f'(int64_t){aval}')
            coerced_args.append(ip)
        elif ptype == 'int' and atype in ('int64_t', '_Bool'):
            ct = gen._new_val('int', f'(int){aval}')
            coerced_args.append(ct)
        elif ptype == 'int' and atype.endswith(' *'):
            # char*/pointer passed where int expected — convert via int64_t
            ip = gen._new_temp('int64_t')
            it = gen._new_temp('int')
            gen._emit(f'  {ip} = (int64_t){aval};')
            gen._emit(f'  {it} = (int){ip};')
            coerced_args.append(it)
        elif ptype.endswith(' *') and atype == 'int':
            # int passed where pointer expected — convert via int64_t
            ip = gen._new_temp('int64_t')
            pp = gen._new_temp(ptype)
            gen._emit(f'  {ip} = (int64_t){aval};')
            gen._emit(f'  {pp} = ({ptype}){ip};')
            coerced_args.append(pp)
        elif ptype == 'char *' and atype == 'void *':
            # void* to char* conversion
            cp = gen._new_val('char *', f'(char *){aval}')
            coerced_args.append(cp)
        elif ptype == 'void *' and atype == 'char *':
            # char* to void* conversion
            vp = gen._new_val('void *', f'(void *){aval}')
            coerced_args.append(vp)
        elif ptype.endswith(' *') and atype == 'char *':
            # char* passed where other pointer type expected
            ip = gen._new_temp('int64_t')
            pp = gen._new_temp(ptype)
            gen._emit(f'  {ip} = (int64_t){aval};')
            gen._emit(f'  {pp} = ({ptype}){ip};')
            coerced_args.append(pp)
        elif ptype == 'ModuleLoader *' and atype in ('int', 'int64_t'):
            # Handle ModuleLoader* type coercions
            ip = gen._new_temp('int64_t')
            pp = gen._new_temp('ModuleLoader *')
            gen._emit(f'  {ip} = (int64_t){aval};')
            gen._emit(f'  {pp} = (ModuleLoader *){ip};')
            coerced_args.append(pp)
        elif (actual_atype == 'MojoList *' and ptype.endswith(' *')
                and ptype[:-2] in _LIST_MARSHAL_ELEMS):
            # A BOXED LIST where the callee declared a scalar-element pointer.
            #
            # This must never be a cast, and the branch below would make it one.
            # `MojoList` is a struct whose first field is a data pointer, so
            # `(float *)l` points at the struct HEADER and the callee reads
            # data/len/cap/the inline buffer as the array's contents. It
            # compiles, links, runs, and returns garbage at exit 0 -- measured
            # on `sumf([1.0, 2.0, 3.0], 3)`: the interpreter says 6.0, the
            # compiled path says 2.45e+26.
            #
            # So the list is packed into a real contiguous buffer, the call
            # runs against that, and the buffer is written back into the list
            # and freed afterwards. The write-back covers EVERY list-typed
            # pointer argument, not just the ones the callee writes: a
            # `T *` parameter does not say whether it is read-only, skipping a
            # write-back that was needed loses the result, and writing back an
            # argument the callee did not touch restores the values it already
            # held. Data loss is the worse of the two failures.
            #
            # `-1` for the count means "the whole list": the general call path
            # has no length argument, and the list's own length is the only
            # thing that can size the buffer. It cannot change during the call
            # -- the callee is handed a plain buffer and has no route back to
            # the list -- so the unpack side clamps to the same count.
            _elem = ptype[:-2]
            gen._list_marshalling_needed.add(_elem)
            _mb = gen._new_temp(f'{_elem} *')
            gen._emit(f'  {_mb} = {_list_pack_name(_elem)}({aval}, -1);')
            coerced_args.append(_mb)
            _pending_list_unpacks.append((aval, _mb, _elem))
        elif ptype.endswith(' *') and atype.endswith(' *') and ptype != atype:
            # Two different pointer types (e.g. MojoList * where MojoDict * is
            # declared, or a struct ptr vs Span *): cast via a temp rather than
            # forwarding an un-typed mismatched pointer (review finding #5).
            #
            # A CAST, though, only converts between two pointer SPELLINGS of
            # one representation. `MojoDict *` / `MojoList *` / `MojoSet *` /
            # `MojoBytes *` are four DISTINCT runtime structs with four
            # different slot layouts (DESIGN.html R2), so casting between
            # them reinterprets one struct's memory as another's and the
            # callee reads a `len` that is really a capacity. `_sce_simple_emit`
            # refuses exactly this pair for that reason — but this branch
            # SHADOWED it, because `ptype.endswith(' *')` matches before the
            # arm below that would have routed through `_safe_coerce_emit`.
            # Real, minimal: `probe(box)` with `box` inferred `MojoList *` at
            # one call site and handed a `set` at another emitted
            # `pp = (MojoList *)s;`, and `for x in box` then read
            # `mojo_list_len`/`mojo_list_get_int` out of a `MojoSet` —
            # printing `0` for a set holding `10` and `20`, with no
            # diagnostic and reads past the set's own slot array.
            #
            # Where a real conversion exists, use it. Where none does, the
            # raw cast is KEPT rather than refused, and that is deliberate:
            # refusing makes the self-host build red (two closure modules
            # drop out and 738 gcc errors follow) without making anything
            # true, because both of those modules are parameter-type
            # INFERENCE disagreements rather than type-confused programs.
            # The inference is `mojo/middle/infra_infer.py`, not this file's
            # to fix; see the INTERFACE REQUEST
            # `bugs/INTERFACE_REQUEST_1_to_middle_infra_infer.md` for both
            # sites and for what to delete here once it lands.
            _cv = _convert_container_kind(gen, ptype, atype, aval)
            coerced_args.append(_cv if _cv is not None
                                else gen._new_val(ptype, f'({ptype}){aval}'))
        elif ptype and ptype != atype:
            ct = gen._new_temp(ptype)
            gen._safe_coerce_emit(atype, ptype, aval, ct)
            coerced_args.append(ct)
        else:
            coerced_args.append(aval)
    args_str = ', '.join(coerced_args)
    # For imported functions with known C signatures, use the declared return type
    # to avoid "invalid conversion in gimple call" when the caller guessed wrong.
    # Priority: _LIBC_DECLARED _KNOWN_SIGS (C stdlib) > imported_symbols > func_return_types.
    # _KNOWN_SIGS for C stdlib must win because a Mojo fn can shadow a C name (e.g. atan2).
    # But _KNOWN_SIGS may contain stale struct-method entries; only trust it for _LIBC_DECLARED.
    imported_ret = None
    in_libc_known = fname in gen._LIBC_DECLARED and fname in gen._KNOWN_SIGS
    # A C library symbol's real signature is authoritative; a same-named Mojo
    # wrapper (e.g. `def dlopen(...) -> _CPointer` → int64_t) must not override
    # the caller's C return type. Otherwise the void*-returning libc dlopen gets
    # assigned into an int64_t call temp (int-from-pointer error).
    is_libc = fname in gen._LIBC_DECLARED
    if in_libc_known:
        sig_ret = gen._KNOWN_SIGS[fname][0]
        if sig_ret != ret_type:
            imported_ret = sig_ret
    if not imported_ret and not is_libc:
        imported_ret = (gen.imported_symbols.get(fname) or {}).get('c_return_type')
    # Also check func_return_types (Mojo function return types) for same mismatch,
    # but skip if fname is a known C stdlib function (to avoid Mojo shadow overriding).
    if not imported_ret and not in_libc_known and not is_libc and fname in gen.func_return_types:
        fn_ret = gen.func_return_types[fname]
        # Never coerce a used value through a 'void' call temp (would emit an
        # illegal `void t; t = f();`). A 'void' entry here is a shadow — e.g. a
        # Mojo wrapper that shares a name with a value-returning libc symbol
        # reached via external_call — so the caller's explicit ret_type wins.
        if fn_ret != ret_type and fn_ret != 'void':
            imported_ret = fn_ret
    if result_var and imported_ret and imported_ret != ret_type:
        call_tmp = gen._new_temp(imported_ret)
        gen._emit(f'  {call_tmp} = {fname} ({args_str});')
        gen._safe_coerce_emit(imported_ret, ret_type, call_tmp, result_var)
    elif result_var:
        gen._emit(f'  {result_var} = {fname} ({args_str});')
    else:
        gen._emit(f'  {fname} ({args_str});')
    for _lv, _bv, _le in _pending_list_unpacks:
        gen._emit(f'  if ({_bv}) {{')
        gen._emit(f'    {_list_unpack_name(_le)}({_lv}, {_bv}, -1);')
        gen._emit(f'    free ({_bv});')
        gen._emit('  }')
    _release_transient_cstr_args(gen, arg_pairs)


def _emit_str_cat(gen, lv: str, rv: str, free_left: bool = False, free_right: bool = False) -> str:
    """`mojo_str_cat(lv, rv)` -> a fresh heap string temp, freeing the operands
    that the CALLER has proven are temporaries nobody else can reference.

    `mojo_str_cat` always copies, so an operand that was itself a
    concatenation result (`a + b + c`, an f-string's running accumulator) or a
    conversion temp (`String + Int` -> `mojo_str_from_int`) is dead the moment
    the outer cat returns. Freeing it there is the whole ownership rule for
    these temporaries: the lowering that created it is the only thing that
    ever names it, so it is also the thing that frees it. An operand that
    might be a variable read, a literal, a field or a call result of unknown
    ownership must NOT be passed as `free_*` (see the two `_is_fresh_operand`
    call sites). The result is registered fresh so a parent cat can free it in
    turn.
    """
    t = gen._call_expr('char *', 'mojo_str_cat', [('char *', lv), ('char *', rv)])
    if free_left:
        gen._emit_call('void', '', 'free', [('char *', lv)])
        gen._fresh_vals.discard(lv)
    if free_right:
        gen._emit_call('void', '', 'free', [('char *', rv)])
        gen._fresh_vals.discard(rv)
    gen._fresh_str_tmps.add(t)
    return t


def _is_fresh_operand(gen, node, val: str) -> bool:
    """True iff `val` is the value of operand expression `node` AND it is a
    concatenation result `_emit_str_cat` built for exactly that expression.
    Both halves are required: the syntactic check (`node` is itself a `+`)
    stops an identifier/field read that merely *aliases* a fresh temp (`s = a
    + b` then `s + c`: the operand node is an IdentExpr) from being freed
    out from under the variable."""
    if val in gen._fresh_str_tmps:
        return isinstance(node, gimple_ctypes.BinaryOp) and node.op == '+'
    # A fresh string that did not come from a `+` of this function's own cat
    # (`String(i)`, a slice, an f-string): still a value a fresh-producing
    # runtime call created that no consumer has claimed, from an expression that
    # can only have produced it (never an identifier).
    return is_fresh_container_operand(gen, node, val)


# Dict runtime functions that have a `_kw` twin taking the key as a raw word.
_KW_DICT_FNS = frozenset([
    'mojo_dict_get_int', 'mojo_dict_get_double', 'mojo_dict_get_str',
    'mojo_dict_set_int', 'mojo_dict_set_double', 'mojo_dict_set_str',
    'mojo_dict_contains', 'mojo_dict_pop_int',
    'mojo_dict_setdefault_int', 'mojo_dict_setdefault_str',
])


def _apply_kw_keys(gen, fname: str, arg_pairs: list):
    """Resolve the placeholder keys `_char_to_cstr(word_ok=True)` handed out.
    For a dict function with a `_kw` twin: call the twin and pass the raw
    integer word. For anything else: build the decimal string now, exactly as
    the non-word path would have, and let the release hook free it after the
    call. Returns `(fname, arg_pairs)`."""
    reg = gen._kw_key_src
    if not reg:
        return fname, arg_pairs
    out = []
    renamed = False
    for _apair in arg_pairs:
        _k = _as_str(_apair[1])
        if _k in reg:
            _word = reg[_k]
            del reg[_k]
            if fname in _KW_DICT_FNS:
                out.append(('int64_t', _word))
                renamed = True
            else:
                _s = gen._call_expr('char *', 'mojo_cstr_or_int_str', [('int64_t', _word)])
                gen._cstr_key_src[_s] = _word
                out.append(('char *', _s))
        else:
            out.append(_apair)
    if renamed:
        return fname + '_kw', out
    return fname, out


def _release_transient_cstr_args(gen, arg_pairs: list) -> None:
    """Free every transient dict-key/compare-operand string among a call's
    arguments, right after that call (see `_char_to_cstr`'s `transient`).
    An entry is consumed on release, so a key can be released at most once."""
    if not gen._cstr_key_src:
        return
    for _apair in arg_pairs:
        _k = _as_str(_apair[1])
        if _k in gen._cstr_key_src:
            _orig = gen._cstr_key_src[_k]
            del gen._cstr_key_src[_k]
            gen._emit_call('void', '', 'mojo_cstr_or_int_release',
                           [('int64_t', _orig), ('char *', _k)])


def _declared_int_ctype(gen, val: str) -> str | None:
    """The C type a value was *declared* with, when `val` names a plain
    variable/parameter/global (not a temp, literal, or expression).

    This deliberately consults the declaration tables (var_types /
    _global_var_types) rather than the value's *semantic* type. A
    scalar-newtype parameter like `mask: UInt8` is physically declared
    `int64_t` at the ABI level (see `_param_ctype`/`_resolve_type` and the
    ABI-widened `func_param_types` the signature is built from) even
    though the codegen's `_actual_types` records its semantic type as
    `uint8_t`. Any copy of that value into a `uint8_t`-typed local must be
    cast explicitly: GIMPLE rejects the implicit `int64_t` -> `uint8_t`
    narrowing ("non-trivial conversion in 'parm_decl'",
    std/builtin/dtype.mojo `_match(self, mask: UInt8)`), and likewise
    rejects the reverse direction — see `_SCALAR_INT_TYPES`'s comment.

    Returns None when `val` isn't a resolvable plain variable, or its
    declared type isn't a scalar integer (pointers/containers/structs keep
    their existing handling)."""
    if not val or not (val[0] in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_'):
        return None
    declared = gen.var_types.get(val)
    if declared is not None:
        return declared if declared in gimple_ctypes._SCALAR_INT_TYPES else None
    declared = gen._global_var_types.get(val)
    if declared is not None:
        # Globals are declared at C level in the module struct; a boxed
        # container global is stored as int64_t regardless of its Mojo
        # type, so the real declared storage type is authoritative for
        # deciding whether a cast is needed.
        real = gen._global_c_decl_types.get(val, declared)
        return real if real in gimple_ctypes._SCALAR_INT_TYPES else None
    return None


def _ensure_local(gen, ctype: str, val: str) -> str:
    """If val is a global variable (not a local temp or constant), load it into
    a local temp first.  GIMPLE requires all cast/unary operands to be registers."""
    is_numeric_literal = bool(val.lstrip('-').replace('.', '', 1).isdigit())
    is_local = (val.startswith('_t') or val.startswith('"') or val.startswith("'")
                or is_numeric_literal)
    if is_local:
        # A bare integer/float literal's own GIMPLE type defaults to
        # 'int' (no '.') or 'double' (has a '.'), regardless of what
        # ctype the CALLER actually needs it typed as — a caller that
        # assigns this return value directly into a temp DECLARED as a
        # different scalar type (e.g. `int64_t _t = <this>;`) hits a
        # real GIMPLE "non-trivial conversion in 'integer_cst'" error,
        # since (unlike ordinary C) GIMPLE requires the RHS of a plain
        # assignment to already have the exact declared type, no
        # implicit int-widening. Confirmed via `Lib/importlib/
        # _bootstrap.py`'s with-statement `__exit__` dummy-None-arg
        # plumbing (_gen_stmt_WithStmt's `_extra_args = [('int64_t',
        # '0')] * n`, reaching `_emit_call`'s `_ensure_local('int64_t',
        # '0')`, then a caller emitting `{temp} = {this_return};`
        # verbatim with no cast of its own — see bugs/CODEGEN_
        # with_stmt_exit_dummy_arg_literal_int64_cast.md). Only cast
        # when the literal's own default type doesn't already match
        # ctype — a plain 'int' literal assigned into an 'int'-typed
        # temp needs no cast (and GIMPLE rejects a cast whose source
        # and destination types are identical as a redundant no-op).
        if is_numeric_literal:
            _native = 'double' if '.' in val else 'int'
            if ctype != _native:
                return f'({ctype}){val}'
        return val
    # Copying a wider-declared scalar into a narrower integer temp is an
    # implicit conversion GIMPLE rejects (e.g. an int64_t ABI parameter
    # copied into a uint8_t temp) — cast explicitly. `_declared_int_ctype`
    # only fires for a genuine *declared-type* mismatch; same-type copies
    # keep the existing bare load.
    declared = gen._declared_int_ctype(val)
    if declared is not None and declared != ctype and ctype in gimple_ctypes._SCALAR_INT_TYPES:
        t = gen._new_temp(ctype)
        gen._emit(f'  {t} = ({ctype}){val};')
        return t
    t = gen._new_val(ctype, f'{val}')
    return t


def _tagged_dyn_read(gen, val: str, want: str) -> str | None:
    """If `val` is a temp read from a tagged nested generator-tuple slot
    (registered in `gen._tagged_dyn_vals` by `_lower_IdentExpr`), return the
    `mojo_tagged_*` read of the requested kind (`'str'`/`'list'`/`'int'`/
    `'double'`); else None. The tag stored in the box decides at runtime
    whether the raw word is actually that kind (mismatch yields NULL/0)."""
    _tdv = getattr(gen, '_tagged_dyn_vals', None)
    if not _tdv or val not in _tdv:
        return None
    box, pos = _tdv[val]
    if want == 'str':
        return gen._new_val('char *', f"mojo_tagged_str ((int64_t){box}, {pos})")
    if want == 'list':
        _raw = gen._new_val('int64_t', f"mojo_tagged_list ((int64_t){box}, {pos})")
        return gen._coerce_to_type('int64_t', 'MojoList *', _raw)
    if want == 'double':
        return gen._new_val('double', f"mojo_tagged_double ((int64_t){box}, {pos})")
    return gen._new_val('int64_t', f"mojo_tagged_int ((int64_t){box}, {pos})")


def _char_to_cstr(gen, typ: str, val: str, transient: bool = False, word_ok: bool = False) -> tuple[str, str]:
    """Convert a char-type value to char * for string operations.
    Returns (new_type, new_val) — if typ is 'char', calls mojo_char_to_str.
    If typ is 'int64_t' and actual type isn't a pointer, also converts.
    Otherwise casts through (char *)(int64_t) for boxed pointers."""
    if typ == 'char':
        return 'char *', gen._call_expr('char *', 'mojo_char_to_str', [('char', val)])
    if typ in ('int', 'int64_t'):
        _td = _tagged_dyn_read(gen, val, 'str')
        if _td is not None:
            return 'char *', _td
        actual = gen._actual_types.get(val)
        if actual == 'char':
            cv = gen._new_val('char', f'(char){val}')
            return 'char *', gen._call_expr('char *', 'mojo_char_to_str', [('char', cv)])
        if actual is not None and actual.endswith(' *'):
            # A KNOWN-boxed pointer (a char*/MojoDict*/... value that was
            # type-erased through an int64_t slot elsewhere in this
            # codegen's dynamic-typing convention, tracked explicitly in
            # _actual_types — e.g. `name = node.name` from the A5
            # getattr, where `name` really is a string pointer that was
            # never re-typed as char*) — round-trip the bit pattern back
            # instead of stringifying it. The OLD check (any int64_t with
            # no pointer record → char) truncated such a local to a
            # single byte, so `name in self.var_types` looked up the low
            # byte of the pointer as the key and ALWAYS missed.
            ip = gen._new_val('int64_t', f'(int64_t){val}')
            return 'char *', gen._new_val('char *', f'(char *){ip}')
        # No tracked boxed-pointer origin: this is a genuine numeric Int
        # dict key (e.g. `Dict[Int, V]`'s `d[k] = v` / `k in d` / `d[k]`)
        # — convert it to its decimal string, the same way
        # _lower_dict_literal already does for literal `{intkey: v}`
        # pairs (see its own comment: "Int key 0 -> '0' instead of
        # C-casting the int to char* which produces NULL for 0"). Every
        # OTHER dict-key site (subscript get/set/augmented-assign/`in`/
        # comprehension) used to skip that conversion and just
        # bit-reinterpret the int as a pointer — NULL for 0 (an
        # immediate SIGSEGV the instant the runtime strdup()s/strcmp()s
        # it), a wild unmapped read for any other small int. The
        # previous default here (assume boxed pointer whenever
        # _actual_types has no entry) was backwards: an untracked
        # int64_t is overwhelmingly a real Int, not a pointer — every
        # genuinely-boxed-pointer case in this codegen explicitly
        # registers itself in _actual_types (see the call sites above).
        # Found via box.3d/game/lib/recipes.mojo's
        # `var _fuel_burn_times: Dict[Int, Int] = {}` — `init_recipes()`
        # crashed with `strdup(NULL)` inside `_dict_set_raw_seq` on the
        # very first `_fuel_burn_times[item_id] = ...` (item_id was a
        # genuine, tracked-nowhere `Int` value of 0).
        # Runtime discriminator rather than a flat stringify: an UNTRACKED
        # int64_t is usually a real Int, but a lambda parameter is typed
        # int64_t whatever it is given, so a string passed to one arrives
        # with its pointer bits here and nothing recorded — and stringifying
        # that looked the key up by decimal address (`lambda k: d[k]` called
        # with "a" searched for "97" and returned 0).
        #
        # `transient=True` is the caller's promise that exactly ONE runtime
        # call consumes this key and that call copies or merely reads it
        # (dict get/set/contains/pop copy via strdup; string compare reads).
        # The heap decimal is then freed right after that call (see
        # `_release_transient_cstr_args`), so an Int-keyed dict in a hot
        # loop no longer leaks one string per access. A caller that stores
        # the pointer, or reuses it across several calls, must not pass it.
        if transient and word_ok:
            if val in getattr(gen, '_int_word_vals', ()):
                # This codegen PROVABLY knows the word is an integer (see
                # `gen._int_word_vals`), so it supplies the answer instead of
                # asking the runtime to work it out — which is the whole
                # point: `mojo_boxed_is_str` is a range test, so it calls
                # every positive int64 in [2^31, 2^47) a pointer and the `_kw`
                # twin dereferenced it. `d[3000000000] = 1` was a SIGSEGV,
                # at -O0, -O2 and under ASan alike.
                #
                # So render the decimal and use the ORDINARY dict entry
                # point, exactly as this function already does for a
                # non-transient key. That is not a demotion: the dict
                # re-normalises the text through `_canon_int`, so `d[5]` and
                # `d["5"]` stay the one integer slot they have always been
                # and `d[3000000000] = 1` finds what it stored. It costs a
                # format the `_kw` twin skips — that is the price of not
                # guessing, paid only where guessing was wrong.
                #
                # Transient, same as every other key here: the block comes
                # from the same pool and is released by
                # `_release_transient_cstr_args` right after the one call
                # that consumes it, so an Int-keyed dict in a hot loop still
                # leaks nothing.
                iv = (val if typ == 'int64_t'
                      else gen._new_val('int64_t', f'(int64_t){val}'))
                ikey = gen._call_expr('char *', 'mojo_int_str_transient',
                                     [('int64_t', iv)])
                gen._cstr_key_src[ikey] = val
                return 'char *', ikey
            # A dict operation's key that is an untracked int64_t: hand the
            # consumer the raw machine WORD instead of a string. `_emit_call`
            # turns the dict call into its `_kw` twin, which decides string vs
            # integer at runtime exactly as `mojo_cstr_or_int_str` does but looks
            # an integer up directly (nothing formatted, nothing to release). The
            # `char *` returned here is only a placeholder for `_apply_kw_keys` to
            # recognise; if it reaches a function without a `_kw` twin, that
            # function materialises the string the old way.
            ipw = gen._new_val('int64_t', f'(int64_t){val}')
            marker = gen._new_val('char *', f'(char *){ipw}')
            gen._kw_key_src[marker] = val
            return 'char *', marker
        key = gen._call_expr('char *', 'mojo_cstr_or_int_str', [('int64_t', val)])
        if transient:
            gen._cstr_key_src[key] = val
        return 'char *', key
    if typ in ('double', 'float'):
        # A FLOATING-POINT dict key: the runtime keys every dict by a `char *`,
        # so the value has to be rendered to text. The old fall-through below
        # emitted a raw `(char *)value` bit-cast, which for a `double` is not
        # valid C ("cannot convert to a pointer type") and would have been a
        # garbage pointer even if it had compiled — real on
        # `d[Float64(0.0)] = "zero"` in the stdlib's test_dict.mojo.
        #
        # One helper for both widths: a `float` widens to `double` exactly
        # (C's usual arithmetic conversions), and `%.17g` of the widened value
        # is the same text `%.9g` of the original would print for every value
        # that round-trips — so a separate float formatter would be a second
        # spelling of the same key for no gain.
        # Register the string as a class-C temporary so
        # `_release_transient_cstr_args` frees it after its one consuming call
        # (§4.1's protocol). Without this a float-keyed dict access in a loop
        # leaks the rendered key every time — measured +32.17 B/iter on
        # build/memprobes/float_dict_key.mojo, which is exactly the
        # "Int-keyed dict in a hot loop leaks nothing" result §10.4 reports for
        # the integer case.
        #
        # Recorded with `_orig = 0`, not the double's own bits: the protocol's
        # release test is `release(s) iff s != (char *)orig`, and its purpose is
        # to spare the BORROWED case where the helper returned its argument
        # unchanged (`mojo_cstr_or_int_str` on an already-boxed string). A
        # rendered float key has no borrowed case — `mojo_str_from_double`
        # always returns a block of its own, from the transient pool or a fresh
        # malloc, never the argument — so 0, which is never a live pointer, says
        # "always release" outright instead of relying on the double's bit
        # pattern not colliding with the string it just produced.
        #
        # "Release" rather than "free" is load-bearing since the float key moved
        # onto the pool: the key is a `_INT_STR_BLOCK`-sized block, and
        # `mojo_cstr_or_int_release` is what puts it back. Passing a pool block
        # to plain `free()` is a live memory-corruption bug, which is the whole
        # reason `_cstr_key_src` is consulted here rather than a bare free.
        key = gen._call_expr('char *', 'mojo_str_from_double', [(typ, val)])
        if transient:
            gen._cstr_key_src[key] = '0'
        return 'char *', key
    if typ != 'char *':
        return 'char *', gen._new_val('char *', f'(char *){val}')
    return typ, val






def _declare_var(gen, name: str, ctype: str, elem: str | None = None, force: bool = False):
    """Register a C-level declaration for Python local `name`.

    Default (force=False): first-decl-wins — if `name` was already
    declared (e.g. the SAME loop-variable name reused across two
    separate sibling `for` loops with different element types), this
    is a deliberate no-op; later reads keep coercing to the FIRST
    declared type. Load-bearing; do not change.

    force=True is for the one case that needs the OPPOSITE behavior:
    a `for` loop whose target name self-shadows its own iterable
    (`for tail in tail:`) — by the time `_declare_var(var, elem)` runs
    for the loop target, `var` is already registered (as the
    iterable's own type) from BEFORE the loop even started, so the
    default no-op guard would leave the stale type/declaration in
    place. force=True mints a genuinely fresh, non-colliding C
    identifier for `name`, records the rename in `self._c_names` (so
    `_lower_IdentExpr`'s `_c_names.get(name, name)` picks it up for
    every subsequent read/write of `name` in the loop body), and
    overrides `self.var_types[name]`/`self._elem_types[name]` to the
    new, correct type — never touching the OLD declaration (still
    valid C, just no longer reachable under `name`).
    """
    # Chokepoint guard, same as _new_temp/_safe_coerce_emit: `ctype` is C
    # TYPE text, and this backend erases an uninferable `str` to int64_t.
    # The `decls.append(f"  {ctype} {c_name};")` calls below would then
    # write the string's ADDRESS as the type — `47303466400 * _t34;`.
    ctype = _as_str(ctype)
    if force:
        # The shadow counter is `gen._shadow_seq_box`, NOT `temp_counter`.
        # `temp_counter` restarts at 0 in every function's prologue, and every
        # function's `decls` are all emitted into ONE translation unit -- so two
        # functions could mint the same `_shadow7_n` and the second use
        # inherited the first one's declared type. A box rather than a bare int
        # because each imported module is emitted by a throwaway temp_gen; the
        # box is shared by reference (see emit_resolve's temp_gen sharing
        # block), and a bare int would restart in each one.
        #
        # Measured in the self-host closure: `module_gen.py`'s
        # `{_safe_name(n) for n in _imported_names}` is a set-of-str
        # comprehension whose loop variable is `char *`, and it collided with
        # an `int64_t` `_shadow272_n` from another function, so
        # `char * = mojo_set_iter_val_str(...)` would not gimplify. One
        # translation unit needs one counter.
        # `if force:` and NOT `if force and name in gen.var_types:` -- a
        # self-shadowing loop target must ALWAYS get its own C variable,
        # which is what this branch's own docstring above promises. The old
        # `and name in var_types` guard made the behaviour depend on whether
        # a PREVIOUS loop with the same target name had already cleaned up
        # after itself: when it had, this call fell through to the normal
        # path, which reuses `gen._c_names[name]` -- i.e. the earlier loop's
        # C identifier, declared with the earlier loop's element type.
        #
        # Measured: `gen_module_impl` has two self-shadowing loops both named
        # `_n` (`for _n in _n`). One iterates ints and the other
        # `{_safe_name(n) for n in _imported_names}` iterates a set of
        # strings, so the second needs `char *` and the shared variable was
        # declared `int64_t` -- `char * = mojo_set_iter_val_str(...)` then
        # failed to gimplify. Distinct variables per loop, always.
        gen._shadow_seq_box[0] += 1
        import re as _re
        safe = _re.sub(r'[^a-zA-Z0-9_]', '_', name.strip('`'))
        if safe and safe[0].isdigit():
            safe = '_' + safe
        c_name = f"_shadow{gen._shadow_seq_box[0]}_{safe}"
        gen._c_names[name] = c_name
        gen.decls.append(f"  {ctype} {c_name};")
        gen.var_types[name] = ctype
        if elem is not None:
            gen._elem_types[name] = elem
        else:
            gen._elem_types.pop(name, None)
        return
    if name not in gen.var_types:
        # Strip backtick-quoted Mojo identifiers (e.g. `6bit` → _6bit)
        if name.startswith('`') and name.endswith('`') and len(name) > 2:
            inner = name[1:-1]
            if inner and inner[0].isdigit():
                inner = '_' + inner
            import re as _re
            c_name = _re.sub(r'[^a-zA-Z0-9_]', '_', inner)
            gen._c_names[name] = c_name
            gen.decls.append(f"  {ctype} {c_name};")
            gen.var_types[name] = ctype
            if elem is not None:
                gen._elem_types[name] = elem
            return
        # Rename C keywords, macro names, and C library functions to avoid conflicts
        if name in gimple_ctypes._C_PARAM_EXTRA_KEYWORDS or name in gimple_ctypes._C_MACRO_NAMES:
            c_name = f"_kw_{name}"
        elif name in gimple_ctypes._C_KEYWORDS:
            c_name = f"_{name}"
        elif name in gimple_ctypes._C_RESERVED_FUNCS:
            # Local variable shadows a C library function; rename to avoid
            # "invalid call to non-function" when the function is called later
            c_name = f"_var_{name}"
        elif (name in gen.imported_symbols
              and gen.imported_symbols[name].get('return_type', 'int64_t') != 'unknown'):
            # Local variable shadows an imported *function* (not a module import) —
            # rename the local so the extern decl and local variable don't conflict.
            # Module imports have return_type='unknown'; functions default to 'int64_t'.
            c_name = f"_local_{name}"
        else:
            c_name = name
        if c_name != name:
            gen._c_names[name] = c_name
        gen.decls.append(f"  {ctype} {c_name};")
        gen.var_types[name] = ctype
    if elem is not None:
        gen._elem_types[name] = elem


def _write_dest(gen, name: str) -> str:
    """Return the C lvalue for a write to variable `name`.
    Inside a closure, captured variables must be written through the env pointer."""
    if name in gen._captures and gen._env_param:
        mut_ptr = getattr(gen, '_gimple_mut_ptr', None)
        if mut_ptr and name in mut_ptr:
            # `{mut}`-capture-spec (ClosureInfo.mut_names): the env
            # field is a POINTER to the real outer local, preloaded
            # into `mut_ptr[name]` once at closure entry (see
            # _gen_lifted_closure) -- dereference it so the write
            # lands on the outer local itself, not a private copy.
            return f'*{mut_ptr[name]}'
        return f'{gen._env_param}->{gimple_ctypes._c_field_name(name)}'
    if name in gen._boxed_mut_locals:
        # This function's OWN local is heap-boxed (a pointer variable,
        # `{ctype} * name`) because some nested closure captures it BY
        # REFERENCE -- see _seed_mut_captured_local_types's docstring.
        # Dereference the pointer directly (no need to preload: unlike
        # `_gimple_mut_ptr` above, this name IS already a plain,
        # directly-named local pointer, not behind a struct
        # component_ref, so `*name` is already valid GIMPLE).
        return f'*{gen._cname(name)}'
    # A `global x` declaration inside a nested function, OR a plain
    # top-level statement genuinely AT module scope (no `global` needed
    # there — see _gen_stmt_AssignStmt's identical `_in_toplevel_gen`
    # check, which this mirrors): both need the write routed to the
    # module globals struct field, not a bare (never-declared) local.
    # Missing the `_in_toplevel_gen` half of this meant ANY top-level
    # augmented assignment to a global (`X += (4,)`, no enclosing
    # function at all — real Python code, e.g. the stdlib's own
    # _compat_pickle.py: `PYTHON2_EXCEPTIONS += ("WindowsError",)`)
    # emitted a write to an undeclared bare local ("PYTHON2_EXCEPTIONS
    # undeclared (first use in this function)") instead of the global —
    # a hard compile failure, not just a silently-dropped update.
    if (name in gen._global_var_types
            and (gen._in_toplevel_gen
                 or name in getattr(gen, '_func_declared_globals', ())
                 # BUG-2026-018 (box.3d/game test_framework): a write to a
                 # bare name that is THIS module's own global, from a
                 # function that never declared `global name`, must still
                 # land on the globals struct — the interpreter mutates the
                 # module binding through its dynamic scope chain (8/8 in
                 # test_field_access.mojo), while the compiled side used to
                 # declare a fresh LOCAL here and drop every increment
                 # (`_passed = _passed + 1` in check() wrote a dead temp;
                 # every suite printed 0/0). This mirrors the IdentExpr
                 # READ path's exact condition (un-shadowed + owned by this
                 # module or unowned), keeping reads and writes on the SAME
                 # storage — before this, the read half of `_passed + 1`
                # already resolved to the global while the write went to a
                # local.
                 or (not gen._in_toplevel_gen
                     and name not in gen.var_types
                     and getattr(gen, '_global_to_module', {}).get(name) in (
                         None, (gen.module_name if len(gen.module_name) > 0 else "root"))))):
        # `global x` declared in this function — write to the module
        # globals struct, mirroring the AssignStmt write path's routing
        # (otherwise AugAssign `x += 1` on a global emitted a LOCAL
        # write, leaving the global unchanged: "counter undeclared").
        #
        # Always target THIS module's own struct (self._current_module_
        # ctx), never `_global_to_module.get(name)` — that map is a
        # SHARED, whole-transitive-tree, name-keyed "first module to
        # claim this bare name wins" map (see gen_module's Phase 1.7 /
        # "Module-level globals" passes and bugs/hard/CODEGEN_module_
        # globals_cross_contamination_via_imported_stmts.md), so when
        # two genuinely DIFFERENT modules each declare their own
        # same-named top-level global (e.g. every file's own `HERE =
        # ...`), it can point at whichever module happened to be
        # scanned FIRST — not necessarily this one. But a `global name`
        # statement (or a bare top-level statement) unambiguously means
        # "THIS function's/THIS statement's own enclosing module's
        # global" under real Python scoping, regardless of what any
        # OTHER module also happens to call itself — and Mechanism 1's
        # fix (that same doc) already guarantees this module's own
        # struct genuinely has a field for `name` whenever this branch
        # fires, since its globals-struct scan is scoped to this
        # module's own statements only. Mirrors _gen_stmt_AssignStmt's
        # and _gen_stmt_MultiAssignStmt's own `_in_toplevel_gen`
        # branches, which already use this exact same direct-current-
        # module routing for the identical reason.
        safe_module = gimple_ctypes._c_field_name(gen._current_module_ctx or "root")
        return f"_{safe_module}_globals.{gimple_ctypes._c_field_name(name)}"
    return gen._cname(name)






def _plan_mut_captured_params(gen, node, func_name: str):
    """Record which PARAMETERS of `func_name` a nested closure captures
    BY REFERENCE, and mint the C identifier each one is declared under.

    Runs BEFORE the parameter list is turned into a C signature, which is
    the entire reason it is separate from `_seed_mut_captured_local_types`:
    a by-reference capture needs a heap BOX, and a box is a pointer local
    that has to carry the SOURCE-LEVEL name (`_boxed_mut_locals` keys
    every later read/write/dereference off that name, and the closure
    seeding stores `_cname(name)` into the env field). A parameter is
    already declared under that name, so the incoming parameter has to be
    declared under a different C identifier and the box local seeded from
    it in the prologue.

    Without this, a mut-captured parameter kept its plain scalar
    declaration (`_seed_mut_captured_local_types` skips any name already
    in `var_types`, and a parameter always is) while the closure it feeds
    declares a POINTER env field -- so the seeding stored an `int64_t`
    into an `int64_t *` field: a hard `-Wint-conversion` error. Real
    repro: `Tools/wasm/wasi/__main__.py`'s
    `def subdir(working_dir, *, clean_ok=False)`, whose doubly-nested
    `wrapper` declares `nonlocal working_dir`.

    Only PLAIN parameters qualify. A `*args`/`**kwargs` parameter is
    already a pointer in its own right, and boxing one would change the
    function's ABI for no gain (its captured type is the container, and a
    `MojoList *`/`MojoDict *` box holds it correctly without one)."""
    for _ci in getattr(gen, '_all_closures', {}).get(func_name, {}).values():
        _cap_types = dict(_ci.captures)
        for _mn in _ci.mut_names:
            if _mn not in _cap_types or _mn in gen._mut_boxed_param_c:
                continue
            for _pn, _pt in (node.params or []):
                if _pn != _mn or _pn.startswith('*'):
                    continue
                gen._mut_boxed_param_c[_mn] = f"_mutbox_{gen._param_safe_name(_mn)}"
                break


def _seed_mut_captured_local_types(gen, func_name: str):
    """For every local of `func_name` that some nested closure captures
    BY REFERENCE (ClosureInfo.mut_names), declare it as a heap-boxed
    POINTER (`self._boxed_mut_locals[name] = pointee_ctype`) instead of
    an ordinary scalar, and register the pointer-typed declaration now,
    before that local's own VarDecl statement is compiled (`_declare_
    var` is a no-op for a name already in `var_types` -- the same
    "declared by an earlier pass" mechanism `_inferred_var_types`
    already relies on, see `_enclosing_scope_with_locals`'s docstring).

    Boxing (not just taking `&local` of an ordinary stack scalar, this
    method's first design) is required, not a style choice: `-fgimple`
    rejects a stack local's address being taken ANYWHERE in the
    function if that same local is also cast-assigned or directly
    `return`ed elsewhere in the SAME function -- confirmed via a
    hand-reduced repro ("non-register as LHS of unary operation" /
    "invalid operand in return statement") after this by-reference-
    capture feature's own stdlib-dylib regression check hit it for
    real on `std/memory/span.mojo`'s `Span.count` (`var count = 0`,
    later `return count` in the SAME function that also captures
    `count` by reference into a nested `do_count` closure -- exactly
    this shape). A never-address-taken pointer local sidesteps the
    restriction entirely: ordinary GIMPLE rules apply to the pointer
    variable itself, and only its separately-allocated pointee is
    dereferenced.

    `_gen_stmt_VarDecl`/`_lower_IdentExpr`/`_write_dest`/`_type_of`
    each consult `self._boxed_mut_locals` to malloc the box at
    declaration time and route every later read/write through a
    dereference instead of a bare identifier.

    A mut-captured PARAMETER takes the same treatment, with two
    differences forced by it already having a declaration: the
    declaration is emitted directly (`_declare_var` is a no-op for a
    name `var_types` already holds) and OVERWRITES the parameter's
    recorded `var_types` entry with the pointer ctype, because that
    entry is what `_type_of`'s own boxed-local branch exists to
    correct. See `_plan_mut_captured_params`."""
    for ci in getattr(gen, '_all_closures', {}).get(func_name, {}).values():
        cap_types = dict(ci.captures)
        # SORTED, and load-bearing. `ci.mut_names` is a frozenset, so
        # iterating it directly emitted the boxed-pointer declarations in
        # Python string-hash order -- which changes with PYTHONHASHSEED,
        # i.e. between processes on the same machine and the same source.
        # Measured on stdlib test/runtime/test_locks.mojo: seeds 0/1/2/4/6/
        # 7/10/12 emit `int64_t * _;` before `int64_t * rawCounter;` and
        # seeds 3/5/8/9/11 emit them the other way round -- two byte-
        # different .ci files for one module, stable only within a process.
        # That is a reproducibility bug with teeth: it makes every
        # "generated C is byte-identical" claim seed-dependent unless the
        # seed was pinned, and bootstrap's stage1 == stage2 == stage3
        # comparison is exactly the check it can silently defeat. Same
        # reason as the sorted() in _emit_mut_local_box_allocs below.
        for mn in sorted(ci.mut_names):
            if mn not in cap_types:
                continue
            if mn in gen._mut_boxed_param_c:
                ctype = cap_types[mn]
                gen._boxed_mut_locals[mn] = ctype
                gen.decls.append(f"  {ctype} * {gen._cname(mn)};")
                gen.var_types[mn] = f"{ctype} *"
                continue
            if mn not in gen.var_types:
                ctype = cap_types[mn]
                gen._boxed_mut_locals[mn] = ctype
                # _declare_var (not a bare var_types assignment): must
                # actually EMIT the C declaration here too, since this
                # runs before the local's own VarDecl statement is
                # compiled -- `_declare_var` is a no-op (by design) for
                # a name already in `var_types`, so if we only set the
                # dict entry without also declaring it, nothing would
                # ever emit the real C declaration at all (a real
                # "'name' undeclared" gcc error, hit and fixed during
                # this feature's own verification).
                gen._declare_var(mn, f"{ctype} *")


def _emit_mut_local_box_allocs(gen):
    """Allocate the heap box for every heap-boxed mutable local (see
    _seed_mut_captured_local_types) ONCE, in the function's prologue.

    History: the box used to be allocated by _gen_stmt_VarDecl at the
    local's `var x = ...` statement, which silently assumed the first
    binding of any `{mut}`-captured local is always a Mojo-style VarDecl.
    Real Python source (the compiler's other first-class input -- e.g.
    Tools/cases_generator/analyzer.py's `nonlocal next_opcode` closure,
    whose first binding is a PLAIN `next_opcode = 1` AssignStmt) never
    goes through _gen_stmt_VarDecl at all, so the box was never
    allocated while every read/write still dereferenced the pointer --
    a write through an uninitialized pointer local (observed as a NULL
    or garbage-address segfault mid-function). Allocating unconditionally
    here also fixes two latent identity hazards of the per-statement
    scheme: a VarDecl re-executed by its enclosing loop re-malloc'd a
    fresh box each iteration (the nested closure's env kept pointing at
    the stale one, so nonlocal updates after rebinding silently split
    into two cells), and a first binding lexically inside one branch but
    executed via another path left the box unallocated on that path.
    Prologue allocation gives the box exactly-once, call-scoped
    semantics -- matching Python's own per-call cell model. Must run
    AFTER _seed_mut_captured_local_types (which emitted the `{ctype} *
    name` declarations) and BEFORE any body statement; both plain-
    function and struct-method generation call it immediately after
    seeding for exactly that reason. The malloc/cast two-step mirrors
    the env-struct allocator's pattern (`-fgimple` rejects a direct
    `name = ({ctype} *) malloc (...)` single statement, and needs a
    literal byte count rather than `sizeof(scalar)` -- see
    _SCALAR_CTYPE_SIZE's docstring)."""
    for mn in sorted(gen._boxed_mut_locals):
        ctype = gen._boxed_mut_locals[mn]
        cname = gen._cname(mn)
        vp = gen._new_val('void *', f"malloc ({gimple_codegen._SCALAR_CTYPE_SIZE.get(ctype, 8)})")
        gen._emit(f"  {cname} = ({ctype} *) {vp};")
        _box_param_c = gen._mut_boxed_param_c.get(mn)
        if _box_param_c:
            # A mut-captured PARAMETER: the box is fresh, so copy the
            # incoming value in through a register temp. `-fgimple`
            # rejects a cast expression's result being stored directly
            # through an INDIRECT_REF (see the identical treatment in
            # `_rewrite_assign_stmt`'s `is_deref` case), and the temp is
            # needed for the plain-pointer case too so the store is a
            # bare `*name = tmp;` with no embedded cast.
            pv = gen._new_val(ctype, _box_param_c)
            gen._emit(f"  *{cname} = {pv};")


def _new_jbp_temp(gen) -> str:
    gen.temp_counter += 1
    name = f"_jbp{gen.temp_counter}"
    gen.decls.append(f"  jmp_buf *{name};")
    return name






def _convert_container_kind(gen, dst_type: str, src_type: str, value: str):
    """Convert a container of one RUNTIME kind into another, or None.

    `MojoDict *` / `MojoList *` / `MojoSet *` / `MojoBytes *` are four
    distinct runtime structs (DESIGN.html R2), so no cast converts between
    them — only a real call does. Exactly two conversions exist in this
    runtime and both are exact rather than approximate, which is what makes
    them safe to apply implicitly at a call site whose parameter type was
    INFERRED and therefore may simply be wrong:

    | from      | to       | call                  | why it is exact                       |
    |-----------|----------|-----------------------|---------------------------------------|
    | `MojoSet *`  | `MojoList *` | `mojo_set_to_list` | iterating a set yields its elements in insertion order, which is the order `mojo_set_to_list` returns them in |
    | `MojoDict *` | `MojoList *` | `mojo_dict_keys`   | iterating a dict yields its KEYS, and `mojo_dict_keys` is exactly the key list |

    The reverse directions, and anything involving `MojoBytes *`, have no
    builder in this runtime and return None; the caller decides what to do
    with that (today: the pre-existing raw cast — see its comment there for
    the two measured closure sites that make refusing it a regression).

    Returning None rather than a cast is the load-bearing half. A set
    converted to a list is a *value* the callee can consume correctly;
    conversely a list silently presented as a set would corrupt every
    subsequent `mojo_set_*` call on it, which is a strictly worse outcome
    than the disagreement that produced the call.

    Element-type metadata is carried across the conversion so a later
    `for x in <arg>` inside the callee binds its loop variable with the
    right accessor: a dict's keys are always `char *`, and a set's element
    type is the source's own tracked element type when there is one."""
    _KIND = gimple_ctypes._CONTAINER_KIND_TYPES
    if dst_type not in _KIND or src_type not in _KIND or src_type == dst_type:
        return None
    if dst_type == 'MojoList *' and src_type == 'MojoSet *':
        res = gen._call_expr('MojoList *', 'mojo_set_to_list', [('MojoSet *', value)])
        _e = gen._elem_of(value)
        if _e:
            gen._elem_types[res] = _e
        return res
    if dst_type == 'MojoList *' and src_type == 'MojoDict *':
        res = gen._call_expr('MojoList *', 'mojo_dict_keys', [('MojoDict *', value)])
        gen._elem_types[res] = 'char *'
        return res
    return None


def _coerce_to_type(gen, src_type: str, dst_type: str, value: str) -> str:
    """
    Generic type coercion routine: converts value from src_type to dst_type.
    Returns the properly cast value (may emit temp assignments as needed).

    Uses existing _safe_coerce_emit logic via temp variable assignment.
    Works for ANY type pair without function-name awareness.
    Scales to 1M functions - ONE routine, not 1M special cases.
    """
    if src_type == dst_type:
        return value

    # Use _safe_coerce_emit to handle the coercion via a temp
    result = gen._new_temp(dst_type)
    gen._safe_coerce_emit(src_type, dst_type, value, result)
    return result


def _generator_to_list(gen, value: str) -> str:
    """R7 addition to the `_materialize_as_list` chokepoint: drain a
    `MojoGenerator *` into a fresh `MojoList *`, so every consumer that
    wants a list view of "any iterable" (`sum()`/`any()`/`all()`/
    `max()`/`min()`/`sorted()`/...) accepts a generator expression or a
    generator call exactly as it accepts a list.

    Real Python's `sum(x for x in xs)` consumes the generator lazily and
    abandons it once exhausted; this is the same computation, materialized.
    The resume/value/destroy driving is the SAME convention
    `_compr_generator_loop` and `_gen_for_generator_iter` use (see that
    function's docstring), driven off the four-symbol per-generator API
    recorded in `_generator_var_api` when the generator value was built —
    so no new ABI and no per-call-site symbol knowledge is needed.

    Each value is appended with the accessor matching the generator's own
    declared `value_ctype`, so a string-valued generator really appends
    `char *` values rather than boxing the pointer bits as integers.
    """
    _iv = _as_str(value)
    api = gen._generator_var_api.get(_iv)
    if api is None:
        # No known API for this handle: refuse rather than cast a
        # MojoGenerator* to MojoList* and read a list header out of a
        # coroutine object (the unchecked-coercion crash this branch
        # replaces).
        raise RuntimeError(
            f"cannot materialize a generator as a list: no known generator "
            f"API for {_iv!r} (pass the generator through a variable, or "
            f"consume it with a for loop)")
    base = api['base']
    vct = api.get('value_ctype') or 'int64_t'
    res = gen._new_temp('MojoList *')
    gen._emit(f"  {res} = mojo_list_new ();")
    bb_cond = gen._new_bb(); bb_body = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    more = gen._new_val('_Bool', f"{base}_resume ({_iv})")
    gen._emit(f"  if ({more}) goto {bb_body}; else goto {bb_after};")
    gen._emit_label(bb_body)
    val = gen._new_val(vct, f"{base}_value ({_iv})")
    if vct in ('char *', 'MojoStr *'):
        gen._void_call('mojo_list_append_str',
                       [('MojoList *', res), ('const char *', val)])
        gen._elem_types[res] = 'char *'
    elif vct == 'double':
        gen._void_call('mojo_list_append_double',
                       [('MojoList *', res), ('double', val)])
        gen._elem_types[res] = 'double'
    else:
        boxed = gen._new_val('int64_t', gen._to_int64(vct, val))
        gen._void_call('mojo_list_append_int',
                       [('MojoList *', res), ('int64_t', boxed)])
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)
    # No `{base}_destroy` — same reason as `_compr_generator_loop`: draining
    # a generator does not close it, and the caller may hold the handle
    # (`sum(g)` must leave `g` a valid, exhausted generator, not a dangling
    # pointer).
    return res


def _materialize_as_list(gen, src_type: str, value: str) -> str:
    """DESIGN.html R1: the shared "give me a MojoList* view of this value"
    decision, for an operation that accepts any iterable (Python's
    all()/any(), enumerate(), str.join()/bytes.join()/shlex.join(), ...)
    but whose runtime primitive only operates on a MojoList*.

    A dict materializes its KEYS (real Python semantics — iterating a dict
    yields keys); a set materializes via mojo_set_to_list, which walks the
    SAME insertion order as a plain `for x in s:` loop (mojo_set_order_
    indices) — mojo_set_sorted would silently give a set consumed here a
    DIFFERENT observable order than one consumed by an ordinary loop, for
    no ordering guarantee gained (real Python's set order is unspecified
    either way, so there is no correctness reason to sort). Anything else
    goes through the ordinary R2 chokepoint unchanged.

    This exact "materialize dict-keys/set-sorted/else-coerce" shape was
    independently duplicated 5 times (all()/any(), enumerate(),
    str.join(), bytes.join(), shlex.join()) during the same 2026-09-13 R3
    cast-migration pass that introduced each of them one at a time — that
    consolidation is the R1 follow-up DESIGN.html calls for.

    A `MojoGenerator *` (a generator call, including every compiled
    generator expression — see `fire_compiler.desugar_genexps`) is drained
    into a list by `_generator_to_list` below, so `sum(x for x in xs)` and
    friends work: before that case existed, such a value fell through to
    the generic coercion below and a coroutine object was read as a list
    header (a hard crash).

    DESIGN.html R5 (added same day as a direct follow-on of the R1
    consolidation above): when `src_type` is a genuinely opaque/boxed
    handle (int64_t/void*/other pointer — the real kind isn't statically
    known), guard with the runtime kind registries
    (`mojo_is_registered_dict`/`_set`) instead of blindly assuming list —
    the exact gap bugs/CODEGEN_all_any_dict_set_miscompile.md documented
    (that doc is gone, closed by this change).
    Fixing it here, once, closes it for all 5 call sites at once."""
    if src_type == 'MojoList *':
        return value
    if src_type == 'MojoDict *':
        _dk = gen._call_expr('MojoList *', 'mojo_dict_keys', [('MojoDict *', value)])
        gen._elem_types[_dk] = 'char *'  # dict keys are always strings
        return _dk
    if src_type == 'MojoSet *':
        _sl = gen._call_expr('MojoList *', 'mojo_set_to_list', [('MojoSet *', value)])
        # Carry the set's element type onto the list, exactly as the dict
        # branch just above does for its keys. `set.to_list` only reboxes;
        # without this the list is untyped and every later consumer reads
        # it with the int accessor — `for i, c in enumerate(sorted(
        # set(text)))` bound `c` as int64_t and then passed those raw
        # pointer bits to `stoi[c] = i`, which gimple rejects ("invalid
        # argument to gimple call": mojo_dict_set_int takes char *).
        _se = gen._elem_of(value)
        if _se and _se != 'int64_t':
            gen._elem_types[_sl] = _se
        return _sl
    if src_type == 'MojoGenerator *':
        return _generator_to_list(gen, value)
    if src_type in ('int64_t', 'int', 'void *') or src_type.endswith(' *'):
        _td = _tagged_dyn_read(gen, value, 'list')
        if _td is not None:
            return _td
        it64 = gen._to_int64(src_type, value)
        result = gen._new_temp('MojoList *')
        bb_dict = gen._new_bb(); bb_not_dict = gen._new_bb()
        bb_set = gen._new_bb(); bb_not_set = gen._new_bb()
        bb_after = gen._new_bb()
        isd = gen._call_expr('int', 'mojo_is_registered_dict', [('int64_t', it64)])
        gen._emit(f"  if ({isd}) goto {bb_dict}; else goto {bb_not_dict};")
        gen._emit_label(bb_dict)
        _dp = gen._coerce_to_type('int64_t', 'MojoDict *', it64)
        _dk = gen._call_expr('MojoList *', 'mojo_dict_keys', [('MojoDict *', _dp)])
        gen._emit(f"  {result} = {_dk};")
        gen._emit(f"  goto {bb_after};")
        gen._emit_label(bb_not_dict)
        iss = gen._call_expr('int', 'mojo_is_registered_set', [('int64_t', it64)])
        gen._emit(f"  if ({iss}) goto {bb_set}; else goto {bb_not_set};")
        gen._emit_label(bb_set)
        _sp = gen._coerce_to_type('int64_t', 'MojoSet *', it64)
        _sl = gen._call_expr('MojoList *', 'mojo_set_to_list', [('MojoSet *', _sp)])
        gen._emit(f"  {result} = {_sl};")
        gen._emit(f"  goto {bb_after};")
        gen._emit_label(bb_not_set)
        _lp = gen._coerce_to_type('int64_t', 'MojoList *', it64)
        gen._emit(f"  {result} = {_lp};")
        gen._emit_label(bb_after)
        return result
    return gen._coerce_to_type(src_type, 'MojoList *', value)



def _quick_container_elem(gen, node) -> str | None:
    """Syntactic container ELEMENT type of a value expression, or None when
    it can't be statically determined. Identifier elements resolve through
    the current function's local container-element map (var_types is empty
    during Pass 2c); call elements resolve through _return_elem_types so
    the fixpoint propagates callee elem types to their callers."""
    if isinstance(node, (gimple_ctypes.ListExpr, gimple_ctypes.TupleExpr, gimple_ctypes.SetExpr)):
        return gen._prepass_list_elem(node.elements)
    if isinstance(node, gimple_ctypes.Comprehension):
        # `[f(x) for _, x in it]` — element type is the mapped expression's
        # container-elem (or scalar-leaf) type.
        return gen._quick_container_elem(node.element)
    if isinstance(node, gimple_ctypes.MemberExpr):
        # `return self.data` — a list FIELD's element type, from the
        # cross-method contract `_field_elem_types` records whenever the
        # field is assigned a container literal (or appended to). Without
        # this arm a method returning one of its own float-list fields
        # inferred no return element type, so every call site typed the
        # result's elements by the unknown-element default — and a
        # comprehension binding them (`[a + gi * v for a, v in zip(gx,
        # self.w.row(i))]`) declared `v` as a MojoList* and emitted
        # `MojoList * * double`, a hard gcc error.
        _pst = getattr(gen, '_prepass_struct', None)
        if _pst and _pst in gen.struct_field_types:
            _ft = gen.struct_field_types[_pst].get(node.member)
            if _ft in ('MojoList *', 'MojoSet *'):
                return gen._field_elem_types.get(_pst, {}).get(node.member)
        return None
    if isinstance(node, gimple_ctypes.SubscriptExpr):
        # `return self.data[a:b]` — a list SLICE is a fresh list of the
        # SAME elements, so it carries the sliced list's element type.
        # A str slice is itself a str, not a container, so it answers
        # None rather than a char* element type.
        if isinstance(getattr(node, 'index', None), gimple_ctypes.SliceExpr):
            _ot = gen._quick_type(node.obj) if hasattr(gen, '_quick_type') else None
            if _ot == 'char *':
                return None
            return gen._quick_container_elem(node.obj)
        return None
    if isinstance(node, gimple_ctypes.TernaryExpr):
        a = gen._quick_container_elem(getattr(node, 'if_true', None) or getattr(node, 'body', None))
        b = gen._quick_container_elem(getattr(node, 'if_false', None) or getattr(node, 'orelse', None))
        if a and b:
            return gimple_ctypes.TypeLattice.join_all([a, b])
        return a or b
    if isinstance(node, gimple_ctypes.IdentExpr):
        return gen._prepass_local_elems.get(node.name)
    if isinstance(node, gimple_ctypes.CallExpr):
        key = gen._prepass_callee_key(node)
        if key is not None:
            e = gen._return_elem_types.get(key)
            if e is not None:
                return e
        # Known SCALAR-returning leaf helpers (exported by gimple_ctypes,
        # outside every closure's function set): their contribution to a
        # container literal is their scalar return type itself.
        callee = getattr(node.func, 'name', None) or (
            getattr(node.func, 'attr', None) if isinstance(node.func, gimple_ctypes.MemberExpr) else None)
        if callee in ('_mojo_type', '_c_escape', '_safe_name'):
            return 'char *'
    return None




def _fstring_sub_exprs(gen, node) -> list:
    """Parse an f-string StringLiteral's `{expr}` interpolations into AST
    expression nodes, best-effort.

    F-string interpolation sub-expressions are raw source text kept
    inside the StringLiteral's own `.value` (only parsed lazily, at
    actual codegen time, by _lower_StringLiteral) — they are NOT real
    AST nodes reachable from the top-level parse tree. That made a call
    embedded directly inside an interpolation (e.g. f"{g('a','b')}",
    with no intermediate variable) invisible to _collect_calls and thus
    to Pass 1.3d's cross-call scalar contract below: only the
    `y = g(...)` shape, a genuine AssignStmt.value CallExpr, was ever
    observed. See bugs/CODEGEN_untyped_param_string_direct_fstring_call.md.
    Mirrors _lower_StringLiteral's own fresh-parse-from-text handling of
    these so both paths agree on what a call site looks like."""
    val, is_fstring = gen._decode_str_literal_text(node.value)
    if not is_fstring:
        return []
    out = []
    for kind, text, _spec, _conv in gen._parse_fstring_parts(val):
        if kind != 'expr':
            continue
        try:
            # Module-level `Parser`/`py_tokenize` (see _lower_StringLiteral's
            # matching fix): a function-scoped `from fire_compiler import
            # ... as _P` is unresolvable in the self-hosted compiler.
            expr_node = Parser(py_tokenize(text))._parse_expr(0)
            expr_node = gimple_ctypes.ast_rewriter.rewrite_node(expr_node)
            out.append(expr_node)
        except Exception:
            pass  # same "can't be lowered" tolerance as _lower_StringLiteral
    return out




def _list_repr_fn(gen, rav: str) -> str:
    """Choose the list-repr runtime helper for a `MojoList *` value.

    MojoList stores every element as a raw int64_t slot with no
    per-element type tag, and the generic codegen-emitted `_mojo_repr_list`
    reads each slot back via mojo_list_get_int. A list of doubles then
    mis-reprs (or, when a bit pattern happens to look like a plausible heap
    address, crashes inside `_mojo_generic_elem_repr` /
    `mojo_read_type_tag_safe`). When this codegen already knows the element
    type is double (self._elem_types, e.g. from a `[3.5, 2.5]` literal),
    route to the double-aware runtime helper instead. Unknown/mixed element
    types keep the generic repr — never regress the int/str/nested cases.

    Same reasoning applies to a genuinely homogeneous int64_t element
    list (e.g. `[a for a in range(n)]`, `[i for i, _ in pair_gen(n)]`):
    the generic `_mojo_repr_list` -> `_mojo_generic_elem_repr` pair
    treats any slot holding the raw value 0 as the `None` sentinel
    (load-bearing for genuinely dynamic/heterogeneous lists, where a
    boxed 0 really can mean a null), which silently misprints a real
    int element of 0 as `None` for a list statically known to hold
    only plain ints — found via a real repro (`[a for a, _ in
    pair_gen(4)]` where pair_gen yields (0, 0), (1, 10), ...: printed
    `[None, 1, 2, 3]` instead of `[0, 1, 2, 3]`). Route to
    mojo_repr_list_ints (mirrors mojo_repr_list_doubles's structure,
    no None-sentinel check) whenever the element type is known to be
    int64_t.
    """
    # A list of 2-element PAIR lists (what `enumerate(x)` and `zip(a, b)`
    # build): the generic repr reads each inner slot through the
    # None-sentinel heuristic, so the index 0 of the first pair printed as
    # `None` instead of `0`. Route to the pair-aware helpers, choosing the
    # one for the SECOND slot's statically known type (a double and an int
    # are indistinguishable in the raw slot).
    nested = gen._nested_elem_types.get(rav)
    if isinstance(nested, list) and len(nested) == 2 and nested[0] == 'int64_t':
        if nested[1] == 'double':
            return 'mojo_repr_list_pairs_d'
        if nested[1] in ('char *', 'MojoStr *'):
            return 'mojo_repr_list_pairs_s'
        return 'mojo_repr_list_pairs'
    # A list of int-holding LISTS (a nested list literal): the inner 0 of
    # `[[0, 7], [1, 8]]` printed as `None` through the generic repr's
    # sentinel heuristic. The nested entry here is the inner list's ELEMENT
    # type (a bare 'int64_t'), not a per-slot pair spec, so it is a
    # different shape from the enumerate/zip pairs handled above.
    if gen._elem_types.get(rav) == 'MojoList *' and nested == 'int64_t':
        return 'mojo_repr_list_intlists'
    # A `struct.unpack` result whose format MIXES kinds goes FIRST, before the
    # uniform branches below: its one container ctype is the degraded
    # 'int64_t' _struct_elem_ctype returns for any non-uniform format, so the
    # int helper would claim it and print a float slot's raw IEEE-754 bits
    # and a bytes slot's pointer as a decimal address. The per-slot kinds are
    # statically known from the format, so hand them to the kinds-aware helper
    # instead. UNIFORM formats are not routed here — `_struct_slot_kind_bytes`
    # answers None for them, and their uniform helper is already exact.
    if _struct_slot_kind_bytes(gen, rav) is not None:
        return 'mojo_repr_list_kinds'
    et = gen._elem_types.get(rav)
    if et == 'double':
        return 'mojo_repr_list_doubles'
    if et == 'int64_t':
        return 'mojo_repr_list_ints'
    if et == '_Bool':
        # `[True, False]` -- the generic path both formats a bool slot as
        # "1"/"0" (mojo_repr_int, not mojo_repr_bool) AND treats its False
        # (0) slot as the None sentinel, printing `[1, None]`. Mirrors the
        # int64_t/double routing just above.
        return 'mojo_repr_list_bools'
    if et == 'MojoBytes *':
        return 'mojo_repr_list_bytes'
    return '_mojo_repr_list'


# The one-byte-per-slot spelling of a `struct.unpack` result's per-slot kinds
# ('i'/'d'/'s'), interned as a string-pool constant, or None when the value has
# no known kinds or its kinds are all the same (see _list_repr_fn's last branch).
# The bytes are from a fixed alphabet, so the pooled string needs no C escaping.
_STRUCT_KIND_BYTE = {'int': 'i', 'double': 'd', 'bytes': 's'}


def _struct_slot_kind_bytes(gen, rav: str) -> str | None:
    kinds = gen._struct_slot_kinds.get(rav)
    if not kinds or len(set(kinds)) == 1:
        return None
    return ''.join(_STRUCT_KIND_BYTE[k] for k in kinds)


def _list_repr_call(gen, key: str, lst: str | None = None) -> tuple[str, list]:
    """The `_list_repr_fn` call for a `MojoList *` value: (function, arguments).

    All the uniform helpers take the list alone. `mojo_repr_list_kinds`
    additionally needs the slot-kind string, and the kinds live under the
    ORIGINAL value's name while the call may have to pass a coerced copy of
    it (a boxed `int64_t` handle, or a `void *`), which is what `key` and
    `lst` are for. Pairing the choice with its argument list in one function
    is what keeps them from disagreeing — a helper picked in one place and an
    argument list built in another is exactly how a one-parameter function
    ends up being called with two arguments.
    """
    fn = gen._list_repr_fn(key)
    args = [('MojoList *', lst if lst is not None else key)]
    if fn == 'mojo_repr_list_kinds':
        args.append(('const char *', gen._intern_string(_struct_slot_kind_bytes(gen, key))))
    return fn, args


def _stringify_value(gen, et: str, ev: str, enode=None) -> str:
    """Convert an already-lowered (type, value) pair into a `char *` per
    Python `str()` semantics. Shared by f-string interpolation, `%`
    string-formatting's `%s` conversion and the `str()` builtin — all three
    need "stringify this typed value" and previously only f-strings had it
    inline.

    `enode` is the operand's AST node when the caller has it, and is the only
    way to tell a bool from the int 0/1 it shares a slot with: a bool's
    lowered C type is a plain `int` here, so `'%s' % (b,)`, `f'{b}'` and
    `str(b)` all printed `1` for a `b = True` at module scope while the same
    value inside a `def` (where the name's inferred type IS `_Bool`) printed
    `True`. See `is_python_bool_expr`."""
    if et == 'char *':
        return ev
    if enode is not None and et in ('int', 'int64_t') \
            and gimple_exprtypes.is_python_bool_expr(gen, enode):
        return gen._call_expr('char *', 'mojo_bool_to_str',
                              [('int', gen._new_val('int', f'(int){ev}'))])
    # A boxed char* (a string pointer stored in an int64_t var, e.g. a
    # tuple-loop var read via get_str and boxed) — stringify as the string
    # it points to, not its decimal address. Without this, f-strings /
    # %s of such a value emitted `static char * <address> = "<address>"`.
    if et in ('int', 'int64_t') and gen._get_actual_type(et, ev) == 'char *':
        return gen._new_val('char *', f'(char *){ev}')
    # A boxed container (a call result whose static type is int64_t/void*
    # but whose real value, per _get_actual_type, is a container) — same
    # re-typing `print`'s dispatch already does before falling to its own
    # container branches (emit_infra.py's print-args loop). Without this,
    # f"{struct.unpack(...)}" / str(a_call_result()) fell straight to the
    # generic `mojo_str` branch below and read the container's header bytes
    # as a C string (bugs/CODEGEN_fstring_and_str_of_a_list_are_garbage.md).
    if et in ('int', 'int64_t', 'void *'):
        _real = gen._get_actual_type(et, ev)
        if _real in ('MojoList *', 'MojoSet *', 'MojoDict *'):
            et = _real
            ev = gen._new_val(_real, f'({_real}){ev}')
    if et == 'MojoList *' or et == 'MojoSet *':
        # A plain container value (a literal, or a local whose static type
        # is already known) reaches here directly, same value the `print`
        # dispatch already knows how to repr — reuse its helper choice
        # rather than falling through to the generic `mojo_str` branch
        # below, which reads the container's raw header bytes as text.
        if et == 'MojoList *':
            fn, fn_args = gen._list_repr_call(ev)
        else:
            fn, fn_args = '_mojo_repr_set', [('MojoSet *', ev)]
        return gen._call_expr('char *', fn, fn_args)
    if et == 'MojoDict *':
        return gen._call_expr('char *', '_mojo_repr_dict', [('MojoDict *', ev)])
    if et == 'MojoBytes *':
        # Python str(b) / f"{b}" both give the b'...' repr text (no decode).
        return gen._call_expr('char *', 'mojo_bytes_repr', [('MojoBytes *', ev)])
    if et == 'MojoMemoryView *':
        return gen._call_expr('char *', 'mojo_memoryview_repr', [('MojoMemoryView *', ev)])
    if et == '_Bool':
        # Python str(True)/str(False) → "True"/"False", not the "1"/"0"
        # the int path below would produce.
        return gen._call_expr('char *', 'mojo_bool_to_str', [('int', ev)])
    if et in ('int', 'int64_t', 'int8_t', 'int16_t', 'int32_t',
              'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t'):
        # A value read through `mojo_list_get_boxed` (a slot of a
        # heterogeneous list whose index was not a compile-time constant)
        # may be a BOX: a heap cell whose payload is a float, because a
        # float has no int64_t spelling. `mojo_repr_boxed` resolves both
        # cases in one call, so nothing below has to branch — and for a
        # value that is NOT a box it is the same answer, and the same
        # allocation, as the mojo_str_from_int arm below.
        if ev in getattr(gen, '_boxed_vals', ()):
            nv = gen._ensure_local('int64_t', ev)
            return gen._call_expr('char *', 'mojo_repr_boxed', [('int64_t', nv)])
        nv = gen._to_int64(et, ev)
        return gen._call_expr('char *', 'mojo_str_from_int', [('int64_t', nv)])
    if et in ('double', 'float'):
        fv = ev if et == 'double' else gen._new_val('double', f'(double){ev}')
        return gen._call_expr('char *', 'mojo_repr_float', [('double', fv)])
    if et.endswith(' *') and et != 'void *':
        # A struct value: consult the receiver's OWN dunder, `__str__`
        # first and `__repr__` second, which is CPython's order for
        # `str(x)` and is what makes `str(p)` stop printing the bare type
        # name the generated field dump produces for an empty field list.
        # This arm did not exist at all, so `str(obj)` and `"%s" % obj` —
        # a SECOND, entirely separate route from the `repr()` one — ran the
        # generated field dump, with the user's `__str__` compiled, exported
        # and never called from anywhere. Same shape as the `repr()` half
        # (bugs/CODEGEN_user_defined_dunder_repr_not_consulted_by_str_and_
        # container_spellings.md), one spelling over.
        #
        # The lookup is `user_dunder_repr_call`, SHARED with `_repr_value`
        # so the two routes cannot drift apart. No dunder → the generic
        # `mojo_str` fallback below, exactly as before.
        _rsn = et[:-2].strip()
        if _rsn:
            _rcall = user_dunder_repr_call(gen, _rsn, et, ev,
                                           ('__str__', '__repr__'))
            if _rcall is not None:
                return _rcall
    return gen._call_expr('char *', 'mojo_str', [(et, ev)])


def _apply_fstring_spec(gen, part_val: str, spec: str) -> str:
    """Apply a format-spec mini-language subset (fill/align/width and
    zero-padding, e.g. `{x:04d}`) to an already-stringified f-string
    value, mirroring myinterpreter._apply_fstring_format_spec so the
    compiled path and interpreter agree. Emits a runtime helper call.
    """
    # "0" prefix -> zero-pad right-aligned to the width
    fill = ' '
    align = None
    i = 0
    if len(spec) >= 2 and (spec[1] == '<' or spec[1] == '>' or spec[1] == '^'):
        fill = spec[0]
        align = spec[1]
        i = 2
    elif len(spec) >= 1 and (spec[0] == '<' or spec[0] == '>' or spec[0] == '^'):
        align = spec[0]
        i = 1
    elif len(spec) >= 1 and spec[0] == '0':
        fill = '0'
        align = '>'
        i = 1
    width_digits = ''
    while i < len(spec) and spec[i] >= '0' and spec[i] <= '9':
        width_digits += spec[i]
        i += 1
    if not width_digits:
        return part_val
    # Emit a runtime call that pads part_val to the width using the fill
    # char and alignment. Use a small inline approach: call mojo_str_rjust/
    # mojo_str_ljust/center if available, else fall back to a runtime
    # helper. Check for the runtime padding helpers:
    width = int(width_digits)
    if align == '<':
        return gen._call_expr('char *', 'mojo_str_ljust',
                               [('char *', part_val), ('int64_t', str(width)), ('char *', f'"{fill}"')])
    if align == '^':
        return gen._call_expr('char *', 'mojo_str_center',
                               [('char *', part_val), ('int64_t', str(width)), ('char *', f'"{fill}"')])
    # '>' (right-align) and '0' (zero-pad right) both rjust
    return gen._call_expr('char *', 'mojo_str_rjust',
                           [('char *', part_val), ('int64_t', str(width)), ('char *', f'"{fill}"')])


def _subst_in_value(gen, v, mapping: dict):
    if isinstance(v, list):
        return [gen._subst_in_value(x, mapping) for x in v]
    if isinstance(v, tuple):
        return tuple(gen._subst_in_value(x, mapping) for x in v)
    if gimple_ctypes.dataclasses.is_dataclass(v) and not isinstance(v, type):
        return gen._subst_idents(v, mapping)
    return v




def _known_field_elem_type(gen, member: str) -> str | None:
    """Element C type of `member` when it is a container field whose element
    type is recorded identically by every struct that has one — the
    `_known_field_type` treatment ONE LEVEL DOWN, for a boxed receiver whose
    own struct isn't statically known.

    Without this a boxed `node.methods` resolved to `MojoList *` (via
    `_known_field_type`) but with NO element type, so `for m in node.methods:`
    fell to `_gen_for_iter`'s runtime dict-or-list dispatch — whose dict arm
    binds the loop variable to a `char *` KEY while the list arm binds a real
    element, giving one variable two incompatible declared types."""
    _ets: list = []
    for _sn in gen._field_elem_types:
        _fm: dict = gen._field_elem_types[_sn]
        if member in _fm:
            _v = _fm[member]
            if _v not in _ets:
                _ets.append(_v)
    if len(_ets) == 1:
        return _ets[0]
    return None


def _known_field_nested_elem_type(gen, member: str) -> str | None:
    """`_known_field_elem_type` for the inner tuple SLOT type of a
    list-of-tuples field (see `_field_nested_elem_types`)."""
    _ets: list = []
    for _sn in gen._field_nested_elem_types:
        _fm: dict = gen._field_nested_elem_types[_sn]
        if member in _fm:
            _v = _fm[member]
            if _v not in _ets:
                _ets.append(_v)
    if len(_ets) == 1:
        return _ets[0]
    return None




def _try_lower_slice_region_eq(gen, slice_node, other_node, negate: bool):
    """`slice_node == other_node` (or `!=` if negate) where slice_node is
    a plain `s[a:b]` SliceExpr with no step - lowers to a direct
    mojo_cstr_region_eq call with no intermediate slice allocation, if
    the slice's source and the other operand are both plain `char *`.
    Returns None (do nothing, let the caller fall through to the generic
    lowering) if the shapes don't match closely enough to be safe."""
    ot, ov = gen.lower_expr(slice_node.obj)
    if ot != 'char *':
        return None
    oth_t, oth_v = gen.lower_expr(other_node)
    if oth_t != 'char *':
        return None
    if slice_node.start is not None:
        _st, sv = gen.lower_expr(slice_node.start)
        start_v = gen._to_int64(_st, sv)
    else:
        start_v = '0'
    if slice_node.stop is not None:
        _et, ev = gen.lower_expr(slice_node.stop)
        stop_v = gen._to_int64(_et, ev)
    else:
        stop_v = 'MOJO_SLICE_STOP_OMITTED'
    eq_t = gen._call_expr('int', 'mojo_cstr_region_eq',
                            [('char *', ov), ('int64_t', start_v), ('int64_t', stop_v), ('char *', oth_v)])
    t = gen._new_temp('_Bool')
    cmp = '== 0' if negate else '!= 0'
    gen._emit(f"  {t} = {eq_t} {cmp};")
    return '_Bool', t


def _sprintf_one(gen, c_spec: str, arg_val: str) -> str:
    """sprintf a single value through a heap buffer into `char *`, using
    a compile-time-known C format spec. Same malloc+sprintf shape
    print() already uses for its non-string/list/dict operands (see
    the print()-builtin lowering) -- factored out here since
    %-formatting needs it once per spec rather than once per call."""
    buf = gen._new_temp('char *')
    vp = gen._new_temp('void *')
    fmt_t = gen._new_val('char *', gen._intern_string(gimple_ctypes._c_escape(c_spec)))
    gen._emit(f'  {vp} = malloc (256);')
    gen._emit(f'  {buf} = (char *) {vp};')
    gen._emit(f'  sprintf ({buf}, {fmt_t}, {arg_val});')
    return buf


def _to_int64(gen, ctype: str, val: str) -> str:
    """Cast val to int64_t; emits to a temp so the result is always an lvalue."""
    _td = _tagged_dyn_read(gen, val, 'int')
    if _td is not None:
        return _td
    # A value read out of a heterogeneous container at an index that is not a
    # compile-time constant may be a BOX (see mojo_list_get_boxed) — a heap
    # cell, because a float has no int64_t spelling. Every int64_t consumer
    # reaches its value through here, so this is the one place the box has to
    # come apart; `mojo_box_int` is Python's own truncation of the float it
    # holds, and returns the input unchanged when it is not a box. Printing
    # does NOT come through here (it asks `mojo_repr_boxed`, which resolves
    # both cases in one call and must see the box itself).
    if val in getattr(gen, '_boxed_vals', ()):
        t = gen._new_temp('int64_t')
        gen._emit(f"  {t} = mojo_box_int ({val});")
        return t
    if ctype == 'int64_t':
        # GIMPLE: can't redundantly cast global int64_t to int64_t; just load
        return gen._ensure_local('int64_t', val)
    t = gen._new_temp('int64_t')
    if ctype.endswith(' *'):
        # Pointer → int64_t requires void* intermediate in GIMPLE
        val_local = gen._ensure_local(ctype, val)
        vp = gen._new_val('void *', f"(void *){val_local}")
        gen._emit(f"  {t} = (int64_t){vp};")
    else:
        # Non-pointer, non-int64_t: load global then cast
        val_local = gen._ensure_local(ctype, val)
        gen._emit(f"  {t} = (int64_t){val_local};")
    return t




def _elaborate_overload_call(gen, node: gimple_ctypes.CallExpr):
    """Resolve and elaborate an overloaded imported call (slice 4): lower the
    args, pick the matching overload by their C types, and emit the call to the
    signature-mangled concrete symbol."""
    g = node.func.name
    source = gen._imported_overloads.get(g)
    if not source:
        return None
    # Keyword-only calls (e.g. std.memory.memcpy(dest=.., src=.., count=..))
    # were previously invisible here: only node.args was lowered, so a
    # kwargs-only call always resolved with an EMPTY arg-type list, which
    # overload resolution below either fails to disambiguate or matches
    # against a wrong/empty-param candidate — either way, the argument
    # values themselves were silently dropped, emitting a call the real
    # signature can never accept (confirmed root cause of a spurious
    # `memcpy();` — zero args — that broke a cold-CAS-cache stdlib build
    # investigated 2026-07-15). Real call sites overwhelmingly write
    # kwargs in the callee's own declaration order, so appending them
    # after any positional args is the same best-effort convention used
    # elsewhere in this file (_lower_call's general kwarg padding).
    arg_pairs = [gen.lower_expr(a) for a in node.args]
    for _kn, _kexpr in (getattr(node, 'kwargs', None) or []):
        arg_pairs.append(gen.lower_expr(_kexpr))
    try:
        module_src = open(source).read()
        import elaborate
        info = elaborate.Elaborator().elaborate_overload_call(
            module_src, g, [ct for ct, _ in arg_pairs])
    except Exception:
        gimple_ctypes._debug_note('overload elaboration failed')
        info = None
    if not info:
        return None
    return gen._emit_generic_instantiation(info, arg_pairs)


def _maybe_lower_mlir_op(gen, node: gimple_ctypes.CallExpr):
    """Lower a ``__mlir_op.\\`dialect.op\\`[attrs](args)`` call via mlir.py.

    The callee is either a ``MemberExpr`` on ``__mlir_op`` (no attr params) or
    a ``SubscriptExpr`` wrapping that member (the ``[...]`` attribute params).
    Returns ``(ctype, val)`` if handled, else ``None`` so normal dispatch runs.
    """
    func = node.func
    attr_members: list[str] = []
    named_attrs: dict[str, object] = {}   # param name → literal value (when an __mlir_attr)
    if isinstance(func, gimple_ctypes.SubscriptExpr):
        # Collect the op's [name=value] params. __mlir_attr literals feed both
        # index.cmp's predicate (flat list) and struct GEP's index= (by name).
        for _name, _val in (getattr(func, 'attrs', None) or []):
            if isinstance(_val, gimple_ctypes.MemberExpr) and isinstance(_val.obj, gimple_ctypes.IdentExpr) \
                    and _val.obj.name == '__mlir_attr':
                attr_members.append(_val.member)
                if _name:
                    kind, v = gimple_ctypes.mlir.parse_attr(_val.member)
                    if kind in ('int', 'simd'):
                        named_attrs[_name] = v
        func = func.obj
    if not (isinstance(func, gimple_ctypes.MemberExpr) and isinstance(func.obj, gimple_ctypes.IdentExpr)
            and func.obj.name == '__mlir_op'):
        return None

    arg_pairs = [gen.lower_expr(a) for a in node.args]

    # Memory / lvalue ops (load / store / offset) need typed, statement-aware
    # emission; mlir.py classifies, we emit with operand types + ptr helpers.
    mem = gimple_ctypes.mlir.mem_op_kind(func.member)
    if mem is not None:
        return gen._lower_mlir_mem(mem, arg_pairs)

    # Struct / aggregate GEP (extract / gep / aget): read the index= field of a
    # known struct. Falls through to the deferred stub when the layout or index
    # isn't statically resolvable.
    sk = gimple_ctypes.mlir.struct_op_kind(func.member)
    if sk is not None:
        res = gen._lower_mlir_struct(sk, named_attrs.get('index'), arg_pairs)
        if res is not None:
            return res
        op = gimple_ctypes.mlir.unwrap(func.member)
        t = gen._new_temp('int64_t')
        gen._emit(f"  {t} = (int64_t)0;  /* mlir __mlir_op.{op}: deferred: unresolved struct index/layout */")
        return 'int64_t', t

    # Index arg_pairs[i][1] directly rather than tuple-unpacking a for-
    # clause target (`for (_, v) in arg_pairs`) — the established boxing
    # bug (a 2-tuple unpack re-boxes an element to int64_t even if it
    # started as char*/a pointer).
    arg_vals = [_ap[1] for _ap in arg_pairs]
    res = gimple_ctypes.mlir.lower_op(func.member, arg_vals, attr_members)
    if res is None:
        # Operands already evaluated; yield 0 so surrounding code still compiles.
        # Distinguish "deferred by design" (GPU/coro/atomics/…) from "not met yet".
        op = gimple_ctypes.mlir.unwrap(func.member)
        reason = gimple_ctypes.mlir.deferral_reason(func.member)
        note = f"deferred: {reason}" if reason else "not modeled"
        t = gen._new_temp('int64_t')
        gen._emit(f"  {t} = (int64_t)0;  /* mlir __mlir_op.{op}: {note} */")
        return 'int64_t', t
    ctype, expr = res
    t = gen._new_val(ctype, f"{expr}")
    return ctype, t


def _compr_range_loop(gen, node, gen0, res, res_type):
    gen._declare_var(gen0.target, 'int64_t',
                    force=_compr_target_is_shadowed(gen, gen0.target))
    args = gen0.iterable.args
    dynamic_step = False
    if len(args) == 1:
        # Explicitly-typed int64_t TEMPS, not bare '0'/'1' string
        # literals -- see the increment-temp comment further down for
        # the exact failure mode this class of bug produces. A bare
        # '0'/'1' defaults to C `int` under strict -fgimple (which has
        # no implicit int->int64_t widening across statements), so
        # `{target} = 0;` (target declared int64_t two lines above)
        # and the increment `{target} + 1` both produced "non-trivial
        # conversion in 'integer_cst'"/"type mismatch in binary
        # expression" for EVERY 1-arg/2-arg range()-based comprehension
        # (`[i * 4 for i in range(n)]`) -- not just the increment-temp
        # DECLARATION shape the prior fix (see below) addressed. Using
        # `self._new_val(...)` (a real pre-materialized temp, matching
        # this same function's own `one64 = self._new_val('int64_t',
        # "(int64_t)1")` pattern a few lines down) rather than simply
        # inlining the `(int64_t)` cast as a string is required too --
        # strict GIMPLE rejects a cast expression appearing directly as
        # an operand of a binary op ("expected expression before '('
        # token"); the cast must be its own prior assignment, with only
        # the resulting bare temp name used in the binary expression.
        # Found via Tools/cases_generator/cwriter.py's `CWriter.
        # __init__`: `self.indents = [i * 4 for i in range(indent + 1)]`.
# `1LL`/`0LL`, not `(int64_t)1`/`(int64_t)0`: a C-style cast is not a
# legal gimple OPERAND, so `idx + (int64_t)1` is a hard gimplification
# error ("expected expression before '(' token") that takes out the whole
# self-host closure. The `LL` suffix is the tree's existing idiom for a
# width-correct int64_t literal and needs no cast.
        start_v = gen._new_val('int64_t', '0LL')
        step_v = gen._new_val('int64_t', '1LL')
        cond_op = '<'
        _stop_t, stop_v = gen.lower_expr(args[0])
        if _stop_t != 'int64_t':
            # Same reasoning as start_v below: a bare int-typed bound
            # compared against the int64_t-declared loop target gives
            # "mismatching comparison operand types" under strict
            # -fgimple (GCC does NOT apply usual arithmetic conversions
            # across a GIMPLE comparison statement) — test_deque.py's
            # `list(range(50, 150))` ctor lowering.
            stop_v = gen._new_val('int64_t', f"(int64_t){stop_v}")
    elif len(args) == 2:
        start_t, start_v = gen.lower_expr(args[0])
        _stop_t, stop_v  = gen.lower_expr(args[1])
        if _stop_t != 'int64_t':
            stop_v = gen._new_val('int64_t', f"(int64_t){stop_v}")
        # `start_v` (unlike `stop_v`, only ever used in a comparison,
        # which undergoes GIMPLE's usual arithmetic conversion) feeds a
        # DIRECT `{target} = {start_v};` assignment below into an
        # int64_t-declared target -- the exact same bare-literal-into-
        # int64_t shape the 1-arg branch's comment above documents
        # ("non-trivial conversion in 'integer_cst'"), but that fix was
        # only ever applied to the 1-arg branch's own hardcoded
        # `(int64_t)0`, not here. A literal/`int`-typed 2-arg start
        # (`range(0, len(cl))`) hit the identical GCC error this branch
        # was never covered for. Materialize as a real int64_t temp,
        # mirroring `one64`/the 1-arg branch's own `start_v` construction.
        if start_t != 'int64_t':
            start_v = gen._new_val('int64_t', f"(int64_t){start_v}")
# `1LL`/`0LL`, not `(int64_t)1`/`(int64_t)0`: a C-style cast is not a
# legal gimple OPERAND, so `idx + (int64_t)1` is a hard gimplification
# error ("expected expression before '(' token") that takes out the whole
# self-host closure. The `LL` suffix is the tree's existing idiom for a
# width-correct int64_t literal and needs no cast.
        step_v = gen._new_val('int64_t', '1LL')
        cond_op = '<'
    elif len(args) == 3:
        start_t, start_v = gen.lower_expr(args[0])
        _stop_t, stop_v  = gen.lower_expr(args[1])
        if _stop_t != 'int64_t':
            stop_v = gen._new_val('int64_t', f"(int64_t){stop_v}")
        se = args[2]
        if isinstance(se, gimple_ctypes.IntLiteral) and se.value < 0:
            cond_op = '>'
        elif isinstance(se, gimple_ctypes.UnaryOp) and se.op == '-':
            cond_op = '>'
        elif isinstance(se, gimple_ctypes.IntLiteral):
            cond_op = '<'
        else:
            cond_op = '<'; dynamic_step = True
        step_t, step_v = gen.lower_expr(se)
        # Same bare-literal-into-int64_t gap as the 2-arg branch above,
        # for BOTH `start_v` (direct `{target} = {start_v};` assignment)
        # and `step_v` (direct `{target} + {step_v}` addition feeding
        # another int64_t-typed temp below, `st`) -- a 3-arg
        # `range(0, len(cl), 2)` (turtle.py's `TurtleScreenBase.
        # _pointlist`: `[(cl[i], -cl[i+1]) for i in range(0, len(cl),
        # 2)]`) hit both: "non-trivial conversion in 'integer_cst'" on
        # `i = 0;` and "type mismatch in binary expression" on the
        # increment. `dynamic_step`'s own comparisons (`{t_sp} = {step_v}
        # > 0;`) are fine uncast, same reasoning as `stop_v` above.
        if start_t != 'int64_t':
            start_v = gen._new_val('int64_t', f"(int64_t){start_v}")
        if step_t != 'int64_t':
            step_v = gen._new_val('int64_t', f"(int64_t){step_v}")
    else:
        return

    # Every emitted reference below must go through _cname: _declare_var
    # renames targets colliding with C reserved identifiers (`index` is a
    # POSIX function, so `_declare_var('index')` declares `_var_index` and
    # records the mapping in _c_names) — emitting the raw Python name made
    # the loop write an UNDECLARED `index` while body reads (which resolve
    # through _c_names) read the declared-but-never-assigned `_var_index`
    # (GCC: "lvalue required as left operand of assignment"; real repro:
    # Tools/scripts/summarize_stats.py's `{...: v for (index, v) in
    # enumerate(...)}` inside OpcodeStats.get_specialization_failure_kinds).
    tgt_c = gen._cname(gen0.target)
    gen._emit(f"  {tgt_c} = {start_v};")
    bb_cond = gen._new_bb(); bb_body = gen._new_bb()
    bb_post = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    if dynamic_step:
        t_lt = gen._new_temp('_Bool'); t_gt = gen._new_temp('_Bool')
        t_sp = gen._new_temp('_Bool'); cond_t = gen._new_temp('_Bool')
        gen._emit(f"  {t_lt} = {tgt_c} < {stop_v};")
        gen._emit(f"  {t_gt} = {tgt_c} > {stop_v};")
        gen._emit(f"  {t_sp} = {step_v} > 0;")
        gen._emit(f"  {cond_t} = {t_sp} ? {t_lt} : {t_gt};")
    else:
        cond_t = gen._new_val('_Bool', f"{tgt_c} {cond_op} {stop_v}")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
    gen._emit_label(bb_body)
    gen._gen_compr_append(node, gen0, res, res_type, bb_post)
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    # `gen0.target` is declared int64_t (line above); this increment
    # temp must match exactly -- GIMPLE has no implicit int->int64_t
    # widening across statements, so declaring it 'int' (32-bit) here
    # produced "non-trivial conversion in 'var_decl'"/"type mismatch
    # in binary expression" on the very next line's `{gen0.target} =
    # {st};` for EVERY range-based comprehension (`[x for x in
    # range(...)]` and friends), not just some narrow edge case.
    # Found via pathlib/__init__.py's `tuple(self[i] for i in
    # range(*idx.indices(len(self))))`.
    st = gen._new_val('int64_t', f"{tgt_c} + {step_v}")
    gen._emit(f"  {tgt_c} = {st};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)


def _compr_list_loop(gen, node, gen0, res, res_type, it_val):
    # `it_val` arrives from `_lower_comprehension` where it is reassigned
    # (the `_get_actual_type` cast block) — whole-function type
    # unification there can widen it back to int64_t even though it holds
    # a `MojoList *`. Every `f'... ({it_val})'` below would then emit
    # `mojo_str_from_int(<ptr>)` — a raw ASLR pointer decimal baked into
    # the generated code (`mojo_list_len (37556144960)`), the top
    # stage2-vs-stage3 non-determinism source. Bind a FRESH `char *`
    # local here (never reassigned → nothing to unify with) and use it in
    # every emitted reference. FRESH name, not `it_val = _as_str(it_val)`:
    # reassigning the param re-widens it via the same unification.
    _iv = _as_str(it_val)
    # Detect tuple unpacking target: "_, av" or "(_, av)"
    target_str = gen0.target.strip()
    inner_str = target_str[1:-1].strip() if (target_str.startswith('(') and target_str.endswith(')')) else target_str
    if ',' in inner_str:
        # Tuple target: each element of the outer list is a sub-list
        # (tuple). Mirrors _gen_for_list's identical, already-fixed
        # per-slot logic (see its own comment for the history): pick
        # the accessor PER SLOT via slot_types/_dict_items_val_elems/
        # _nested_elem_types instead of assuming every slot is a
        # string. The old code here read EVERY slot via
        # mojo_list_get_str unconditionally, which round-trips a
        # genuinely-numeric slot's bit pattern correctly (get_str then
        # cast back to int64_t is value-preserving) but then always
        # tagged the var `_actual_types[vn] = 'char *'` regardless —
        # so a later arithmetic use (e.g. `range(a, a + b) for a, b in
        # pairs` with pairs a list of int tuples) had `b` wrongly
        # treated as a pointer by `_lower_binary_tail`'s `_actual_
        # types.get(rv, ...)` lookup, producing "passing argument 2 of
        # 'mojo_range' makes integer from pointer without a cast".
        # Bracket-aware split (see _gen_for_list's identical fix): a naive
        # `inner_str.split(',')` tore a NESTED target like
        # `label, (value, den)` into the bogus fragments `(value` / `den)`
        # which were then declared and assigned VERBATIM as C identifiers
        # (`(value = _t10;` / `den) = _t11;`) — hard syntax errors at the
        # comprehension site (real: Tools/scripts/summarize_stats.py's
        # `[... for label, (value, den) in object_stats.items()]`).
        var_names = _split_top_level_comma(inner_str)
        is_dict_items = _iv in gen._dict_items_val_elems
        value_elem = gen._dict_items_val_elems.get(_iv) if is_dict_items else None
        slot_types = gen._tuple_slot_types.get(_iv)
        pair_elem = gen._nested_elem_types.get(_iv, 'int64_t')
        slot_elems = []
        for i, vn in enumerate(var_names):
            if is_dict_items:
                se = 'char *' if i == 0 else (value_elem or 'int64_t')
            elif slot_types is not None and i < len(slot_types):
                se = slot_types[i]
            else:
                se = pair_elem
            slot_elems.append(se)

        def _declare_target_name(vn, se):
            # A parenthesized slot is not itself a variable — recurse so
            # only its INNER names get declared, as boxed int64_t (the
            # assignment recursion below reads the slot as an opaque
            # boxed pair; mirrors _gen_for_list's identical convention).
            if vn.startswith('(') and vn.endswith(')'):
                for _nv in _split_top_level_comma(vn[1:-1].strip()):
                    _declare_target_name(_nv, 'int64_t')
            else:
                gen._declare_var(vn, se)

        # index walk + `_as_str` — NOT `for vn, se in zip(var_names,
        # slot_elems)`: the zip 2-tuple unpack boxes both slots on the
        # self-hosted path, so `_declare_var(vn, se)` got a boxed ctype
        # and `mojo_str_cat` in the decl builder ran `strlen()` on
        # garbage (a hard segfault on the single-TU `--dump
        # myinterpreter.py`, in a list comprehension with a tuple target).
        for _czi in range(len(var_names)):
            _cvn = _as_str(var_names[_czi])
            _cse = _as_str(slot_elems[_czi]) if _czi < len(slot_elems) else 'int64_t'
            _declare_target_name(_cvn, _cse)
        len64 = gen._new_val('int64_t', f'mojo_list_len ({_iv})')
        idx64 = gen._new_val('int64_t', '(int64_t)0')
        bb_cond = gen._new_bb(); bb_body = gen._new_bb()
        bb_post = gen._new_bb(); bb_after = gen._new_bb()
        gen._emit(f"  goto {bb_cond};")
        gen._emit_label(bb_cond)
        cond_t = gen._new_val('_Bool', f"{idx64} < {len64}")
        gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
        gen._emit_label(bb_body)
        raw_elem = gen._new_val('int64_t', f"mojo_list_get_int ({_iv}, {idx64})")
        sub_list = gen._coerce_to_type('int64_t', 'MojoList *', raw_elem)

        def _emit_slot_assign(ptr, vn, i, se):
            # Nested tuple target: the slot is an opaque boxed pair —
            # cast and recurse one level (deeper nesting recurses
            # identically), mirroring _gen_for_list. Checked BEFORE any
            # accessor dispatch so even a wrongly-str-typed slot can't
            # emit a parenthesized name verbatim.
            # `_p` fresh `char *` view: `ptr` (a `MojoList *` temp name)
            # gets unified to int64_t through this nested fn on the
            # self-hosted path, so `f'... ({ptr} ...)'` emitted a raw
            # ASLR pointer decimal (`mojo_list_get_str (46304590592, 0)`)
            # — a stage2-vs-stage3 non-determinism source.
            _p = _as_str(ptr)
            if vn.startswith('(') and vn.endswith(')'):
                raw_n = gen._new_val('int64_t', f"mojo_list_get_int ({_p}, {i})")
                nested_ptr = gen._coerce_to_type('int64_t', 'MojoList *', raw_n)
                nested_names = _split_top_level_comma(vn[1:-1].strip())
                for j, nn in enumerate(nested_names):
                    _emit_slot_assign(nested_ptr, nn, j, 'int64_t')
                return
            cv = gen._cname(vn)
            suf = gimple_ctypes.TypeLattice.list_suffix(se)
            vt = gen.var_types.get(vn, se)
            if suf == 'str':
                sub_str = gen._new_val('char *', f"mojo_list_get_str ({_p}, {i})")
                if vt == 'char *':
                    gen._emit(f"  {cv} = {sub_str};")
                else:
                    sub_val = gen._new_val('int64_t', f"(int64_t){sub_str}")
                    gen._emit(f"  {cv} = {sub_val};")
                    gen._actual_types[vn] = 'char *'
            else:
                raw = gen._new_val('int64_t', f"mojo_list_get_int ({_p}, {i})")
                if vt == 'int64_t':
                    gen._emit(f"  {cv} = {raw};")
                else:
                    gen._safe_coerce_emit('int64_t', vt, raw, cv)

        for i, vn in enumerate(var_names):
            _emit_slot_assign(sub_list, vn, i, slot_elems[i])
        gen._gen_compr_append(node, gen0, res, res_type, bb_post)
        gen._emit(f"  goto {bb_post};")
        gen._emit_label(bb_post)
# `1LL`/`0LL`, not `(int64_t)1`/`(int64_t)0`: a C-style cast is not a
# legal gimple OPERAND, so `idx + (int64_t)1` is a hard gimplification
# error ("expected expression before '(' token") that takes out the whole
# self-host closure. The `LL` suffix is the tree's existing idiom for a
# width-correct int64_t literal and needs no cast.
        one64 = gen._new_val('int64_t', "1LL")
        st = gen._new_val('int64_t', f"{idx64} + {one64}")
        gen._emit(f"  {idx64} = {st};")
        gen._emit(f"  goto {bb_cond};")
        gen._emit_label(bb_after)
        return
    elem = _as_str(gen._elem_of(_iv))
    gen._declare_var(_as_str(gen0.target), elem)
    # FRESH `char *` view of the loop-target C name: `gen0.target` (an AST
    # str field) erases to int64_t on the self-hosted path, so a bare
    # `f'  {gen0.target} = ...'` LVALUE emitted a raw ASLR pointer decimal
    # (`54648467328 = _t224;`) — a stage2-vs-stage3 idempotency failure.
    _tgt = gen._cname(_as_str(gen0.target))
    len64 = gen._new_val('int64_t', f'mojo_list_len ({_iv})')
    idx64 = gen._new_val('int64_t', '(int64_t)0')
    bb_cond = gen._new_bb(); bb_body = gen._new_bb()
    bb_post = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    cond_t = gen._new_val('_Bool', f"{idx64} < {len64}")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
    gen._emit_label(bb_body)
    suf = gimple_ctypes.TypeLattice.list_suffix(elem)
    if suf == 'double':
        gen._emit(f"  {_tgt} = mojo_list_get_double ({_iv}, {idx64});")
    elif suf == 'str':
        # mojo_list_get_str returns char*, handle type mismatch with target variable
        temp_str = gen._new_val('char *', f"mojo_list_get_str ({_iv}, {idx64})")
        target_type = gen._type_of(_as_str(gen0.target))
        if target_type == 'char *':
            gen._emit(f"  {_tgt} = {temp_str};")
        else:
            # Cast to int64_t if target is opaque
            int_ptr = gen._new_val('int64_t', f"(int64_t){temp_str}")
            gen._emit(f"  {_tgt} = {int_ptr};")
    else:
        raw64 = gen._new_val('int64_t', f"mojo_list_get_int ({_iv}, {idx64})")
        # The loop variable may have been first declared elsewhere in this
        # function with a non-int64_t C type (e.g. `f` used as a string in
        # one branch and as a node handle in `for f in node.fields` later —
        # _declare_var is first-decl-wins). Assigning an int64_t element
        # straight into a `char *` variable is a hard "makes pointer from
        # integer" compile error; mirror _gen_for_list's identical
        # coercion. A node handle boxed into a char*-declared var is a
        # bit-pattern-preserving cast — the field-access lowering already
        # reads boxed handles through the runtime tag dispatch.
        target_type = gen._type_of(_as_str(gen0.target))
        if target_type != 'int64_t':
            gen._safe_coerce_emit('int64_t', target_type, raw64, _tgt)
        else:
            gen._emit(f"  {_tgt} = (int64_t) {raw64};")
    gen._gen_compr_append(node, gen0, res, res_type, bb_post)
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    one64 = gen._new_val('int64_t', "(int64_t)1")
    st = gen._new_val('int64_t', f"{idx64} + {one64}")
    gen._emit(f"  {idx64} = {st};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)


def _compr_generator_loop(gen, node, gen0, res, res_type, it_val):
    """`list(<supported generator call>())` / any other comprehension
    consuming one — mirrors _compr_list_loop's/_gen_for_generator_iter's
    resume()/value() convention (see _gen_for_generator_iter's
    docstring) so a `for` loop and this comprehension-based consumer
    (which `list(...)`/`set(...)`/etc. all route through via
    _lower_ctor_from_iterable) get identical, non-duplicated semantics."""
    _iv = _as_str(it_val)   # see _compr_list_loop
    api = gen._generator_var_api.get(_iv)
    if api is None:
        gen._emit(f"  /* TODO: comprehension over MojoGenerator* with no known API (unreachable in Milestone B scope) */")
        return
    base, vct = api['base'], api['value_ctype']
    # `[... for a, b in <tuple-yielding generator>():]` — mirrors
    # _gen_for_generator_iter's identical tuple-target handling (see
    # its own comment), EXCEPT a comprehension's target string is NOT
    # guaranteed to be paren-wrapped for a bare (unparenthesized)
    # tuple target the way ForStmt.target always is:
    # `_parse_generator_target` (fire_compiler.py) only wraps in
    # parens when the SOURCE itself wrote them (`for (a, b) in ...`);
    # `for a, b in ...` inside a comprehension parses to the literal
    # string "a, b" with no parens at all, unlike `_parse_unpack_
    # target`'s ForStmt path which always synthesizes the wrapping
    # parens regardless of source spelling. The old strict
    # startswith('(')/endswith(')') check here missed that bare form
    # entirely, silently falling through to the single-var branch
    # below and emitting a literal, invalid `e, _ = <tuple val>;`
    # comma-expression statement — which doesn't just fail to compile
    # cleanly itself, it desyncs the surrounding -fgimple parser badly
    # enough to cascade into dozens of unrelated "type defaults to
    # 'int'"/"conflicting types" errors on LATER, perfectly-formed
    # declarations (real repro: Lib/test/test_exception_group.py's
    # `[e for e, _ in leaf_generator(eg)]`). Mirrors `_compr_list_
    # loop`'s own already-correct both-forms detection (its "Detect
    # tuple unpacking target" comment) instead of reinventing a
    # narrower check.
    tuple_slot_ctypes = api.get('tuple_slot_ctypes')
    _target_str = gen0.target.strip()
    _inner_str = (_target_str[1:-1].strip()
                  if (_target_str.startswith('(') and _target_str.endswith(')'))
                  else _target_str)
    is_tuple_target = (',' in _inner_str and tuple_slot_ctypes is not None)
    if is_tuple_target:
        var_names = [v.strip() for v in _inner_str.split(',')]
    else:
        var_names = None
        gen._declare_var(gen0.target, vct,
                        force=_compr_target_is_shadowed(gen, gen0.target))
    bb_cond = gen._new_bb(); bb_body = gen._new_bb()
    bb_post = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    cond_t = gen._new_val('_Bool', f"{base}_resume ({_iv})")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
    gen._emit_label(bb_body)
    val = gen._new_val(vct, f"{base}_value ({_iv})")
    if is_tuple_target:
        gen._emit_generator_tuple_unpack(var_names, tuple_slot_ctypes, val)
    else:
        # _cname, not the raw Python name: see _compr_range_loop's
        # reserved-identifier comment (`index` et al. are renamed by
        # _declare_var; body reads resolve through _c_names).
        gen._emit(f"  {gen._cname(gen0.target)} = {val};")
    gen._gen_compr_append(node, gen0, res, res_type, bb_post)
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)
    # Deliberately NO `{base}_destroy` here. Consuming a generator does not
    # CLOSE it, in real Python or here: the handle belongs to whatever holds
    # it (usually a variable), and this loop may be run again over the same,
    # now-exhausted generator — `g = (x for x in xs); sum(x for x in g);
    # sum(x for x in g)` must print the total and then 0, exactly like
    # CPython. Destroying it here freed the coroutine while `g` still pointed
    # at it, so that second pass was a use-after-free (a real SIGSEGV, found
    # by test_gimple_runner.py's `gimple_genexp_local_consumed_twice` once
    # generator expressions became real generators). An unnamed temporary
    # (`list(x for x in xs)`) now simply lives until process exit, which is
    # what CPython's GC does too.


def _compr_dict_loop(gen, node, gen0, res, res_type, it_val):
    _iv = _as_str(it_val)   # see _compr_list_loop: keep the ptr a char* in the f-string
    gen._declare_var(gen0.target, 'char *',
                    force=_compr_target_is_shadowed(gen, gen0.target))
    iter_t = gen._new_temp('MojoDictIter *')
    more_t = gen._new_temp('int')
    gen._emit(f"  {iter_t} = mojo_dict_iter_new ({_iv});")
    bb_cond = gen._new_bb(); bb_body = gen._new_bb()
    bb_post = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    gen._emit(f"  {more_t} = mojo_dict_iter_next ({iter_t});")
    cond_t = gen._new_val('_Bool', f"{more_t} != 0")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
    gen._emit_label(bb_body)
    key_tmp = gen._new_val('const char *', f"mojo_dict_iter_key ({iter_t})")
    tgt = gen0.target
    vt = gen.var_types.get(tgt, 'char *')
    tgt_c = gen._cname(tgt)
    if vt in ('int64_t', 'int', 'int32_t'):
        vp = gen._new_val('void *', f'(void *){key_tmp}')
        box = gen._new_val('int64_t', f'(int64_t){vp}')
        gen._emit(f"  {tgt_c} = {box};")
    else:
        gen._emit(f"  {tgt_c} = (char *) {key_tmp};")
    gen._gen_compr_append(node, gen0, res, res_type, bb_post)
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)
    gen._emit(f"  mojo_dict_iter_free ({iter_t});")


def _compr_target_is_shadowed(gen, target) -> bool:
    """True when a comprehension's loop target must get its OWN C variable.

    A comprehension's `for` target is a fresh binding in the comprehension's
    own scope, so it can never share the enclosing function's C variable for
    that source name. Without this, `_declare_var`'s first-decl-wins guard
    reused whatever was already declared -- and a self-shadowing `for n in n`
    earlier in the function leaves behind a SHADOW variable with that name,
    typed for THAT loop's elements.

    Measured in the self-host closure: `gen_module_impl` has a
    `for _n in _n` loop (int64_t elements) and later
    `{_safe_name(n) for n in _imported_names}` (a set of strings, so
    `char *`). The comprehension reused the loop's `_shadow5_n`, declared
    `int64_t`, and `char * = mojo_set_iter_val_str(...)` would not
    gimplify -- one of the four errors that took out bootstrap-stage2-cc.

    Only true when a variable of that name is already live, so the
    single-comprehension case -- by far the common one -- is completely
    unchanged.
    """
    return _as_str(target) in gen.var_types


def _compr_set_loop(gen, node, gen0, res, res_type, it_val):
    _iv = _as_str(it_val)   # see _compr_list_loop
    # A source set of strings (e.g. `frozenset({'a','b'})`) must round-trip
    # its elements as `char *` — reading them back with mojo_set_iter_val_int
    # tags the pointer bits 'int', so a later `x in frozenset` via
    # mojo_set_contains_str misses every element.
    _sv_elem = _as_str(gen._elem_of(_iv))
    _sv_is_str = (_sv_elem == 'char *')
    gen._declare_var(gen0.target, 'char *' if _sv_is_str else 'int64_t',
                    force=_compr_target_is_shadowed(gen, gen0.target))
    iter_t = gen._new_temp('MojoSetIter *')
    more_t = gen._new_temp('int')
    gen._emit(f"  {iter_t} = mojo_set_iter_new ({_iv});")
    bb_cond = gen._new_bb(); bb_body = gen._new_bb()
    bb_post = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    gen._emit(f"  {more_t} = mojo_set_iter_next ({iter_t});")
    cond_t = gen._new_val('_Bool', f"{more_t} != 0")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
    gen._emit_label(bb_body)
    if _sv_is_str:
        gen._emit(f"  {gen._cname(gen0.target)} = mojo_set_iter_val_str ({iter_t});")
    else:
        gen._emit(f"  {gen._cname(gen0.target)} = mojo_set_iter_val_int ({iter_t});")
    gen._gen_compr_append(node, gen0, res, res_type, bb_post)
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)
    gen._emit(f"  mojo_set_iter_free ({iter_t});")


def note_dict_callable_ret(gen, dict_val: str, value_text: str) -> None:
    """A callable stored into a dict keeps its return type for a later
    `d[k](...)` call, which is the one place a dict subscript can be a
    CALLEE. Called from every dict store of an int64 slot; a non-callable
    value has no entry in `_callable_ret_types` and is a no-op, which is
    what keeps this off the hot path."""
    _rt = gen._callable_ret_types.get(value_text)
    if not _rt:
        return
    _cur = gen._dict_callable_ret.get(dict_val)
    if _cur is None:
        gen._dict_callable_ret[dict_val] = _rt
    elif _cur and _cur != _rt:
        # A second, DIFFERENT return type for the same dict: ambiguous from
        # here on, and it must STAY ambiguous -- a third store of the first
        # type must not un-poison it, so the '' is sticky (`_cur and ...`
        # above never re-enters this branch once poisoned).
        gen._dict_callable_ret[dict_val] = ''


def _gen_print(gen, args: list, kwargs: list = None):
    # print(..., file=sys.stderr): kwargs used to be silently dropped
    # entirely (the file= expression was never even inspected), so every
    # print(..., file=sys.stderr) — the standard error-reporting idiom
    # throughout this codebase's own source — always printed to stdout
    # AND, once self-hosted, crashed evaluating `sys.stderr` generically
    # (mojo_obj_getattr's stub). Detected here by AST shape at compile
    # time; see _is_sys_stderr.
    print_fn = 'mojo_print'
    if kwargs:
        for kw_name, kw_val in kwargs:
            if kw_name == 'file' and gen._is_sys_stderr(kw_val):
                print_fn = 'mojo_print_stderr'

    # Inline string-literal call arguments (e.g. `mojo_print (" ")`) are not
    # valid in __GIMPLE — every literal must go through the _slit_ pool and
    # be loaded into a char* temp first (see _intern_string's docstring).
    # print()'s own separator/end/empty literals previously violated this
    # directly, which silently "worked" for top-level code (compiled as
    # plain C, where inline literals are fine) but corrupted the argument
    # at runtime for any struct method (always emitted as raw __GIMPLE) —
    # confirmed via a genuinely minimal repro (any struct method calling
    # print() with 2+ args segfaults; single-arg print was unaffected
    # since it skips the separator/uses only the pooled user string).
    def _emit_literal_print(escaped: str, print_fn: str):
        slit = gen._intern_string(escaped)
        t = gen._new_val('char *', slit)
        gen._emit(f'  {print_fn} ({t});')

    if not args:
        _emit_literal_print('', print_fn)
        return
    parts = [gen.lower_expr(a) for a in args]
    # The STATIC type of each printed expression, for the dispatch below.
    # Needed because a boolean's C type is often a plain `int`: a BoolLiteral
    # lowers to int, and any/all/isinstance lower to `int` on purpose (they
    # are C ints). Only the static type knows the value is a bool, and
    # without it every `print(True)`, `print(b)` (b = True),
    # `print(any(xs))` and `print(isinstance(v, T))` printed `1`/`0`.
    # `_quick_type` is best-effort by contract, so a node it cannot type
    # falls back to the lowered C type rather than failing the print.
    arg_static = []
    for _a in args:
        try:
            arg_static.append(gen._quick_type(_a))
        except Exception:
            arg_static.append('')
    # A dict/list-get result stored in a plain local is boxed generically
    # as int64_t at the C level even when the real value is a string —
    # _lower_IdentExpr's plain-local-read path returns the *declared*
    # var_types entry, not the tracked real type (_actual_types), unlike
    # e.g. _lower_method_call's receiver resolution. Without re-resolving
    # here, print() on such a value picked the int format specifier and
    # printed the raw boxed pointer as a decimal address instead of the
    # string content. Found via py_tokenize's own multi-line-string cache
    # (`string_cache[placeholder]`, a MojoDict[str, str]) — `print()`ing
    # a restored docstring value printed its address, and any Token built
    # from it carried that same wrong value into `.value`.
    resolved_parts = []
    for atype, aval in parts:
        # A DYNAMIC tagged nested-generator-tuple element (see
        # _lower_IdentExpr's _tagged_dyn_src branch): the real kind is only
        # known at runtime, so emit a tag-dispatched repr — str passes the
        # pointer straight through, list/dict go through their repr helpers,
        # everything else formats the int/double word. Without this the
        # generic numeric path printed the raw boxed word (modulefinder's
        # `print(nm)` printed a pointer address).
        _tdv = getattr(gen, '_tagged_dyn_vals', None)
        if _tdv and aval in _tdv and atype in ('int', 'int64_t'):
            box, pos = _tdv[aval]
            _res = gen._new_temp('char *')
            bb_str = gen._new_bb(); bb_chk3 = gen._new_bb()
            bb_list = gen._new_bb(); bb_chk2 = gen._new_bb()
            bb_dbl = gen._new_bb(); bb_int = gen._new_bb()
            bb_done = gen._new_bb()
            _tag = gen._new_val('int64_t', f"mojo_tagged_tag_dyn ((int64_t){box}, {pos})")
            _sp = gen._new_val('char *', f"mojo_tagged_str ((int64_t){box}, {pos})")
            _lp = gen._coerce_to_type(
                'int64_t', 'MojoList *',
                gen._new_val('int64_t', f"mojo_tagged_list ((int64_t){box}, {pos})"))
            _dp = gen._new_val('double', f"mojo_tagged_double ((int64_t){box}, {pos})")
            gen._emit(f'  if ({_tag} == 1) goto {bb_str}; else goto {bb_chk3};')
            gen._emit_label(bb_str)
            gen._emit(f'  {_res} = {_sp};')
            gen._emit(f'  goto {bb_done};')
            gen._emit_label(bb_chk3)
            gen._emit(f'  if ({_tag} == 3) goto {bb_list}; else goto {bb_chk2};')
            gen._emit_label(bb_list)
            _lrepr = gen._call_expr('char *', *gen._list_repr_call(_lp))
            gen._emit(f'  {_res} = {_lrepr};')
            gen._emit(f'  goto {bb_done};')
            gen._emit_label(bb_chk2)
            gen._emit(f'  if ({_tag} == 2) goto {bb_dbl}; else goto {bb_int};')
            gen._emit_label(bb_dbl)
            _sd = _sprintf_one(gen, '%g', _dp)
            gen._emit(f'  {_res} = {_sd};')
            gen._emit(f'  goto {bb_done};')
            gen._emit_label(bb_int)
            _s = _sprintf_one(gen, '%ld', aval)
            gen._emit(f'  {_res} = {_s};')
            gen._emit_label(bb_done)
            resolved_parts.append(('char *', _res))
            continue
        if atype in ('int', 'int64_t'):
            real = gen._get_actual_type(atype, aval)
            if real == 'char *':
                aval = gen._new_val('char *', f'(char *){aval}')
                atype = 'char *'
            elif real == 'MojoDict *':
                dp = gen._coerce_to_type('int64_t', 'MojoDict *', aval)
                rv = gen._call_expr('char *', '_mojo_repr_dict', [('MojoDict *', dp)])
                aval = rv
                atype = 'char *'
            elif real in ('MojoList *', 'MojoSet *'):
                lp = gen._new_val(real, f'({real}){aval}')
                if real == 'MojoList *':
                    fn, fn_args = gen._list_repr_call(aval, lp)
                else:
                    fn, fn_args = '_mojo_repr_set', [(real, lp)]
                rv = gen._call_expr('char *', fn, fn_args)
                aval = rv
                atype = 'char *'
        resolved_parts.append((atype, aval))
    parts = resolved_parts
    for i, (atype, aval) in enumerate(parts):
        _stat = arg_static[i] if i < len(arg_static) else ''
        # A name recorded as holding a bool (`b = True`): its own static type
        # is the `int` that BoolLiteral lowers to, so the check above cannot
        # see it. Only `print` consults this set — through the one shared
        # predicate, which a dict store now uses too, so the two cannot
        # disagree about the same value (they did: `print(b)` said True while
        # `{'k': b}` printed `{'k': 1}`).
        if _stat != '_Bool' and args and i < len(args):
            if gimple_exprtypes.is_python_bool_expr(gen, args[i]):
                _stat = '_Bool'
        if atype == 'char *':
            gen._emit(f'  {print_fn} ({aval});')
        elif atype in ('int', 'int64_t') and aval in getattr(gen, '_boxed_vals', ()):
            # A slot read out of a heterogeneous list at a NON-constant index
            # is a BOX when its runtime kind is a float: a heap cell, because
            # a float has no int64_t spelling and the generic `%ld` path
            # below would print the box's own address. `mojo_repr_boxed`
            # answers both cases in one call, so no branch is needed, and for
            # a value that is not a box it is the same integer text (and the
            # same allocation) the generic path produces.
            rv = gen._call_expr('char *', 'mojo_repr_boxed', [('int64_t', aval)])
            gen._emit(f'  {print_fn} ({rv});')
        elif atype in ('double', 'float', '__fp16'):
            dv = aval if atype == 'double' else gen._new_val('double', f'(double){aval}')
            rv = gen._call_expr('char *', 'mojo_repr_float', [('double', dv)])
            gen._emit(f'  {print_fn} ({rv});')
        elif atype == 'MojoList *':
            # print(a_list) previously fell to the generic numeric
            # sprintf path below via printf_fmt('MojoList *'), printing
            # the raw boxed pointer as a decimal address — Python prints
            # a real `[elem, ...]` repr. Reuse the reflection-generated
            # list repr rather than a separate formatter.
            rv = gen._call_expr('char *', *gen._list_repr_call(aval))
            gen._emit(f'  {print_fn} ({rv});')
        elif atype == 'MojoDict *':
            rv = gen._call_expr('char *', '_mojo_repr_dict', [('MojoDict *', aval)])
            gen._emit(f'  {print_fn} ({rv});')
        elif atype == 'MojoBytes *':
            rv = gen._call_expr('char *', 'mojo_bytes_repr', [('MojoBytes *', aval)])
            gen._emit(f'  {print_fn} ({rv});')
        elif atype == 'MojoSet *':
            # print({1, 2}) with no boxing involved (a set LITERAL's lowered
            # type is statically MojoSet *, so it never reaches the boxed
            # int64_t re-typing branch above that already calls
            # _mojo_repr_set) fell all the way to the generic numeric path
            # below and printed the set's own ADDRESS -- len() and iteration
            # on the very same value were already correct, so this was
            # purely a missing dispatch arm, not a missing repr helper.
            rv = gen._call_expr('char *', '_mojo_repr_set', [('MojoSet *', aval)])
            gen._emit(f'  {print_fn} ({rv});')
        elif _stat in ('MojoList *', 'MojoSet *', 'MojoDict *', 'MojoBytes *') \
                and atype not in ('MojoList *', 'MojoSet *', 'MojoDict *', 'MojoBytes *', 'char *'):
            # A container-typed call result whose LOWERED type is `void *`:
            # `zip(...)` returns void* on purpose (see _lower_builtin_zip_n's
            # comment on why it must not claim a pair element type), so print
            # had no container branch to take and fell to the numeric path,
            # printing the list's ADDRESS. The static type knows what it is,
            # so route on that.
            if _stat == 'MojoDict *':
                _dp = gen._coerce_to_type(atype if atype in ('int64_t', 'int', 'void *') else 'int64_t',
                                          'MojoDict *', aval)
                rv = gen._call_expr('char *', '_mojo_repr_dict', [('MojoDict *', _dp)])
            else:
                _lp = gen._coerce_to_type(atype if atype in ('int64_t', 'int', 'void *') else 'int64_t',
                                          _stat, aval)
                if _stat == 'MojoList *':
                    _fn, _fargs = gen._list_repr_call(aval, _lp)
                else:
                    _fn, _fargs = '_mojo_repr_set', [(_stat, _lp)]
                rv = gen._call_expr('char *', _fn, _fargs)
            gen._emit(f'  {print_fn} ({rv});')
        elif atype == '_Bool' or (_stat == '_Bool' and atype in ('int', 'int64_t', 'char *', 'long')):
            # Python prints True/False; the generic numeric path below would
            # sprintf a _Bool with "%d" and print 1. Also reached for
            # `_Bool`-typed locals, which is how a comparison or a
            # builtin-returning bool (any/all/isinstance/in) reaches here.
            rv = gen._call_expr('char *', 'mojo_repr_bool', [('_Bool', aval)])
            gen._emit(f'  {print_fn} ({rv});')
        else:
            t = gen._new_temp('char *')
            vp = gen._new_temp('void *')
            # The format string is itself an inline literal in a call
            # argument position — same __GIMPLE restriction as the
            # separator/newline literals above, so pool it too.
            fmt_slit = gen._intern_string(gimple_ctypes.TypeLattice.printf_fmt(atype))
            fmt_t = gen._new_val('char *', fmt_slit)
            gen._emit(f'  {vp} = malloc (256);')
            gen._emit(f'  {t} = (char *) {vp};')
            gen._emit(f'  sprintf ({t}, {fmt_t}, {aval});')
            gen._emit(f'  {print_fn} ({t});')
            gen._emit(f'  free ({t});')
        if i < len(parts) - 1:
            _emit_literal_print(' ', print_fn)
    _emit_literal_print('\\n', print_fn)


def _comptime_call_hook(gen):
    """Build the call hook for comptime_eval.eval_const_int: fold a call to
    an *imported* function by running it at compile time as cached machine
    code (elaborate.py extracts the source, comptime.evaluate runs it).

    The hook is the one genuinely backend-specific piece of comptime folding,
    which is why it is a parameter of the shared evaluator rather than part
    of it — a backend with no import elaborator (the formal arm64 path) omits
    it and simply does not fold calls."""
    def hook(name, argvals):
        src_path = gen._imported_fn_sources.get(name)
        if not src_path:
            return None
        try:
            # importlib (NOT a bare `import` statement): gen_module's
            # find_imports AST-walk collects every ImportStmt at any
            # nesting depth and would inline elaborate.py/comptime.py
            # into the self-host closure — compiler-core sources that
            # were never GIMPLE-clean. import_module is invisible to
            # that walk while resolving identically at runtime.
            import importlib as _importlib
            _elab = _importlib.import_module('elaborate')
            _comptime = _importlib.import_module('comptime')
            module_src = open(src_path).read()
            fn_src = _elab.extract_fn_source(module_src, name)
            if fn_src:
                return int(_comptime.evaluate(fn_src, name, argvals))
        except Exception:
            gimple_ctypes._debug_note('comptime evaluation failed', name)
        return None
    return hook


def _eval_const_int(gen, node) -> int | None:
    """Evaluate an expression as a compile-time integer, or return None.

    Folding rules are shared with the formal arm64 backend
    (mojo/middle/comptime.py); this wrapper supplies the gimple path's
    binding table and its compile-time-call hook."""
    return comptime_eval.eval_const_int(node, gen._comptime_vals,
                                          _comptime_call_hook(gen))


def _eval_const_bool(gen, node) -> bool | None:
    """Evaluate an expression as a compile-time bool, or return None."""
    return comptime_eval.eval_const_bool(node, gen._comptime_vals,
                                           _comptime_call_hook(gen))

def _split_top_level_comma(s: str) -> list[str]:
    """Split s by top-level commas only (bracket-aware)."""
    parts, depth, start = [], 0, 0
    for i, c in enumerate(s):
        if c in '([': depth += 1
        elif c in ')]': depth -= 1
        elif c == ',' and depth == 0:
            parts.append(s[start:i].strip())
            start = i + 1
    parts.append(s[start:].strip())
    return parts

# Per-part parse results for `_dedup_variadic_externs`, keyed by the part's
# exact text: (concrete, variadic) function names, or None-absent.
#
# The function is called ONCE PER `gen_module_impl` with the CUMULATIVE
# `parts` list — the generated C of every module compiled so far ANYWHERE in
# the transitive tree, because `_module_stmts` and the preamble accumulation
# are shared by reference into every `temp_gen`. So without this cache the
# same parts are re-split and re-parsed at every one of the N levels: O(N^2)
# in emitted text, which is the same per-level-rescan-the-cumulative-total
# shape as bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md
# documents for the AST-walking consumers, just measured in C fragments
# instead of AST nodes. That doc ruled this site "out of scope" on 08-18 and
# 08-25 because it is not an `imported_stmts` AST consumer; a 2026-09-26
# re-profile of a 160-module struct chain put it at 34% of the run (12.97s of
# 38.6s, with its nested `_is_extern_decl` called 11,188,407 times), which is
# 4x the largest AST consumer still standing — so the unit of work does not
# change the complexity class, and this is now the top remaining site.
#
# Process-global rather than per-gen, for two reasons. There is no gen
# instance to hang it on (this is a free function reached through a
# `self._dedup_variadic_externs` shim), and the cached value is a pure
# function of the key — the full text of the part — with nothing time-
# dependent in it, so unlike the `_field_scan_var_cache` /
# `_calls_in_stmts_cache` family it needs no write-invalidation at all. Same
# shape as `_WALK_FIELD_NAMES_CACHE`. Lookup is cheap rather than merely
# correct because CPython caches a str's hash on the object, and `parts`
# holds the SAME str objects across levels (they are appended, never
# re-joined), so a repeat level pays a hash-cache hit per part and nothing
# more.
#
# Phase 8 (2026-09-30) added the SECOND half of the fix, the one Phase 7's
# own "What is left, precisely" section said was the only remaining way to
# go: the entry for a part's own OUTPUT TEXT is now DERIVED from the entries
# of the parts that produced it (`_record_output_parse`), instead of being
# re-parsed byte by byte the first time the parent level lays hands on it.
# Before, the corpus was scanned once per distinct TEXT, and one of those
# texts is every module's whole output blob — whose parse is exactly the
# union of its own parts' parses — so half of all parse volume was spent
# re-deriving, from scratch, something the child had just derived. Phase 7's
# cache could not absorb it (every blob is a distinct text the moment it is
# born) and a shared running `concrete` set cannot replace it (a superset of
# any one level's corpus; see below). The derivation is guarded by a
# `_record_output_parse`-local boundary check and is the ONLY thing in this
# file that writes an entry it did not parse itself.
_DEDUP_EXTERN_PARTS_CACHE: dict = {}

def _text_after_last(s: str, sep: str) -> str:
    """`s[s.rfind(sep) + 1:]` — the text after the last `sep`, or all of `s`
    when there is none.

    Exists because that slice, written inline on a value this codegen had
    typed `int64_t`, did not survive self-compilation: `str.rfind` lowers to
    `mojo_str_rfind` only for a `char *` RECEIVER (`emit_methods.py`'s
    str-method table keys on the resolved receiver ctype), so on an
    `int64_t` one it fell through to the declared-but-unimplemented extern and
    the emitted assignment handed back the RECEIVER POINTER where an index
    belonged. `a[a.rfind(';') + 1:]` then became `a + (a + 1)`, and the
    self-hosted compiler, reading its own `extern`-declaration parts with
    that, walked off into unmapped memory on the very first `--dump-full`:
    SIGBUS inside `_dedup_variadic_externs__boundaries_preserve_parse`, exit
    -10, a zero-byte `.ci`. The one thing that made it findable at all is
    that `_parse_part(part: str)` — the SAME scanning one level up — has a
    `str`-annotated parameter and therefore lowers; this helper is that same
    mechanism, applied to the one caller that had no annotation to use. (The
    marker GCC's stub emits is deliberately not quoted verbatim here: it ends
    up in this docstring's own string literal, where a later grep for
    unimplemented calls in generated C would find it.)

    The `i < 0` branch is the `rfind == -1` case Python's slice already
    handles (`s[-1 + 1:]` is all of `s`), stated rather than relied on.
    """
    i = s.rfind(sep)
    if i < 0:
        return s
    return s[i + 1:]

def _dedup_variadic_externs(parts: list) -> str:
    """Join the preamble, dropping a variadic `extern T name (...);` import
    declaration when a CONCRETE prototype for the same function is also present
    (e.g. an elaborated instantiation forward-declares `get_defined_int (void)`
    while the import-decl pass emits `(...)`, which GCC reports as conflicting
    types). The concrete prototype wins.

    Per-part parse results are memoized process-globally
    (`_DEDUP_EXTERN_PARTS_CACHE`), and the entry for the text this function
    RETURNS is published there too (`_record_output_parse`), so the parent
    level — which inlines exactly this text as one of its own parts — reads
    the child's parse instead of rescanning the child's whole output blob.

    Deliberately plain string scanning (`.split`/`.find`/`.rfind`), NOT
    regex `.finditer()`/`.findall()` — this codegen has no lowering for
    either shape of for-loop (finditer needs a compile-time-known
    module-level pattern var; findall has no lowering at all, confirmed
    directly: `for w in pat.findall(s): ...` emits `mojo_unsupported_iter`
    even outside self-hosting), so a loop here over either would silently
    run zero times once this file compiles itself."""
    def _is_extern_decl(stmt: str) -> bool:
        # A genuine `extern ...;` declaration always has "extern" as the
        # first token of ONE of its (possibly preprocessor-guard-
        # prefixed) lines — checking the fragment for the bare
        # SUBSTRING "extern" is not enough: a `#line N "path/to/
        # test_external_call.mojo"` directive immediately followed by
        # an ordinary function CALL statement (e.g. `std_testing___
        # init___assert_false (_t5)`) also contains "extern" — as a
        # substring of "external" in the source filename — which wrongly
        # classified that CALL as a concrete prototype for
        # `std_testing___init___assert_false`, causing the REAL
        # variadic extern declarations for it to be dropped everywhere
        # ("implicit declaration of function" once compiled). Real
        # regression, found via compile_stdlib.py's
        # test/ffi/test_external_call.mojo.
        #
        # Necessary-condition short-circuit FIRST: all three accepted line
        # shapes below contain the substring `extern`, so a fragment
        # without it cannot satisfy any of them. Proves equivalent, and
        # skips the `.split('\n')` + per-line strip/compare for the
        # overwhelming majority of fragments (every statement of every
        # emitted function body). `not in` on a str is lowered on the
        # self-hosted path (cpp_async.py's `',' not in stmt.name`).
        if 'extern' not in stmt:
            return False
        for line in stmt.split('\n'):
            line = line.strip()
            if line == 'extern' or line.startswith('extern ') or line.startswith('extern"'):
                return True
        return False

    def _fragment_names(stmt: str) -> tuple:
        """The extern name ONE `;`-delimited fragment contributes, as
        `(concrete_name, variadic_name)` — either may be None, and a
        fragment never contributes both (they are disjoint by construction).

        A name is `concrete` when its parameter list is neither `...` nor
        empty, and `variadic` when it is exactly `...` — the two lists are
        disjoint by construction, and an empty parameter list is in neither
        (the old first pass skipped it via `params not in ('...', '')`; the
        old second pass skipped it via `params != '...'`, so it never
        decided anything either way).

        Factored out of `_parse_part` (which applies it to each fragment of
        a part) because `_boundaries_preserve_parse` needs to compare a
        MERGED fragment's contribution against the two it replaced — same
        per-fragment reading, one function, so the two cannot drift.
        """
        if not _is_extern_decl(stmt):
            return (None, None)
        paren = stmt.find('(')
        if paren < 0:
            return (None, None)
        close = stmt.rfind(')')
        if close < paren:
            return (None, None)
        params = stmt[paren + 1:close].strip()
        head_toks = stmt[:paren].strip().split()
        if not head_toks:
            return (None, None)
        name = head_toks[-1].lstrip('*')
        if params == '...':
            return (None, name)
        if params != '':
            return (name, None)
        return (None, None)

    def _parse_part(part: str) -> tuple:
        """One part's extern declarations, as (concrete, variadic) name lists.

        A PURE function of `part`'s own text — it reads no gen state, no
        module globals, nothing but its argument — which is exactly what
        makes `_DEDUP_EXTERN_PARTS_CACHE` sound. Split out of the two passes
        below so a part is split/parsed ONCE rather than once per pass, and
        (with the cache) once per `gen_module` level rather than once per
        level per pass; see that dict's own comment for why the repetition
        across levels was the expensive part.

        Whole-part short-circuit: a part with no `extern` substring at all
        can contribute no name (every accepted fragment shape contains it —
        see `_is_extern_decl`), so the `.split(';')` — which materializes
        one new str per statement, tens of thousands of them for a
        multi-megabyte imported-module blob — is skipped entirely. Same
        reasoning, one level up.
        """
        if 'extern' not in part:
            return ([], [])
        concrete = []
        variadic = []
        for stmt in part.split(';'):
            c_name, v_name = _fragment_names(stmt)
            if c_name is not None:
                concrete.append(c_name)
            if v_name is not None:
                variadic.append(v_name)
        return concrete, variadic

    def _boundaries_preserve_parse(joined: list) -> bool:
        """Does `'\\n'.join(joined)` parse as the concatenation of the parts'
        own parses?

        The join changes exactly one thing: where a `;`-delimited fragment
        of the joined text SPANS parts. A fragment that starts in part `i`'s
        trailing text (`fa`, i.e. after its last `;`) runs on until the next
        `;` anywhere in the joined text — which is in the first following
        part that has one at all, so a run can straddle three or more parts,
        and an EMPTY part does NOT end it (it has no `;` either; the join's
        own newline passes straight through). Everything else parses
        exactly as it did in its own part.

        For each such run the merged fragment is read with the same
        `_fragment_names` the parts themselves were parsed with, and it must
        carry exactly the names the run's pieces carried separately. That is
        a direct comparison on the only thing the parse feeds (a name set),
        not a hand-derived argument about paren/`rfind` positions — which is
        the point, because the shapes that break the derivation are not
        guessable: `extern int late (int` names nothing on its own (no
        closing paren) yet completes into a concrete `late` when the next
        part supplies the `)`, and two pieces each naming a different
        function cannot both survive, since a fragment carries at most one
        concrete and one variadic name.

        Cheap skip first, provably free: a run whose pieces contain no
        `extern` substring at all. The merged fragment's lines are the
        pieces' lines, so it cannot be an extern declaration and names
        nothing at all (see `_is_extern_decl`) — same reasoning
        `_parse_part` uses to skip a whole part. A part that ends in `;`
        starts no run: its trailing fragment is a whole fragment of the
        joined text.
        """
        n = len(joined)
        i = 0
        while i < n:
            a = joined[i]
            # `_text_after_last`, not the inline slice: `a` comes out of an
            # unannotated `list`, so it is `int64_t`, and `str.rfind` has no
            # lowering for an `int64_t` receiver — the inline form compiled
            # itself into a stubbed call that returned the pointer and made
            # the whole self-hosted compiler SIGBUS. See the helper.
            fa = _text_after_last(a, ';')
            if fa == '' or i == n - 1:
                i += 1
                continue
            frags = [fa]
            j = i + 1
            while j < n:
                b = joined[j]
                fb_end = b.find(';')
                if fb_end < 0:
                    frags.append(b)
                    j += 1
                    continue
                frags.append(b[:fb_end])
                break
            sides_c = []
            sides_v = []
            any_extern = False
            for frag in frags:
                if 'extern' not in frag:
                    continue
                any_extern = True
                c_name, v_name = _fragment_names(frag)
                if c_name is not None:
                    sides_c.append(c_name)
                if v_name is not None:
                    sides_v.append(v_name)
            if any_extern:
                merged = frags[0]
                for k in range(1, len(frags)):
                    merged = merged + '\n' + frags[k]
                m_c, m_v = _fragment_names(merged)
                # EVERY piece's name must be exactly the merged
                # fragment's, and a merged fragment with no name must have
                # had none. Checking the first piece alone is not enough:
                # `extern int a (int)` + `extern int a (int)` +
                # `extern "C" ... b (...)` (no `;` anywhere) is ONE
                # fragment whose `find('(')`/`rfind(')')` span all three,
                # naming `a` and swallowing `b` — equal to the first piece,
                # different from the union.
                if m_c is None:
                    if len(sides_c) > 0:
                        return False
                elif len(sides_c) == 0:
                    return False
                else:
                    for k in range(len(sides_c)):
                        if sides_c[k] != m_c:
                            return False
                if m_v is None:
                    if len(sides_v) > 0:
                        return False
                elif len(sides_v) == 0:
                    return False
                else:
                    for k in range(len(sides_v)):
                        if sides_v[k] != m_v:
                            return False
            i = j
        return True

    def _record_output_parse(out: str, out_parts: list,
                             exact_concrete, variadic_by_out_part: list) -> None:
        """Publish `_DEDUP_EXTERN_PARTS_CACHE[out]` for the text JUST
        returned, with the parse its parts' own entries imply.

        `out` is `'\n'.join(out_parts)`, so the parse of `out` is the
        concatenation of the parses of `out_parts` — whose entries the caller
        has just read — exactly when no run of parts merges into one
        `;`-delimited fragment that changes what it names, which is what
        `_boundaries_preserve_parse` decides by direct comparison.

        The condition is checked rather than assumed, and when it fails
        nothing is published (the parent level then parses the text itself,
        exactly as it did before this existed).

        `exact_concrete` is the caller's already-computed set when it is
        provably the exact name set of `out` (nothing was dropped) — passed
        BY REFERENCE, so the common case allocates nothing; `None` asks for
        it to be rebuilt from the parts. Every part of `out_parts` is already
        in the cache by the time this runs (the caller read or filled its
        entry in the main pass), so `entry` below is never absent; a missing
        one would be a programming error here, not a case to paper over.
        """
        if not _boundaries_preserve_parse(out_parts):
            return
        if exact_concrete is None:
            exact_concrete = set()
            for p in out_parts:
                entry = _DEDUP_EXTERN_PARTS_CACHE.get(p)
                for name in entry[0]:
                    exact_concrete.add(name)
        out_variadic = []
        for vl in variadic_by_out_part:
            for name in vl:
                out_variadic.append(name)
        _DEDUP_EXTERN_PARTS_CACHE[out] = (exact_concrete, out_variadic)


    # ONE pass over `parts`, not two. The old shape scanned every fragment
    # twice — once to build `concrete`, once to decide each part's fate —
    # re-deriving `paren`/`close`/`params`/`name` the second time, and it
    # could not be collapsed into one pass only because `concrete` is not
    # complete until every part has been read. Collecting each part's
    # `variadic` names alongside its `concrete` names makes the drop test a
    # membership question that can be asked afterwards, so the parse is
    # shared instead of repeated. Same predicate, same inputs, same
    # decision: a part is dropped iff one of its variadic names is in the
    # tree-wide `concrete` set.
    #
    # A part's entry is read from `_DEDUP_EXTERN_PARTS_CACHE` — including,
    # now, the entry `_record_output_parse` published for a CHILD module's
    # whole output blob when this level is that blob's first reader, which
    # is why the per-level parse volume is the bytes THIS level added rather
    # than the cumulative corpus. What is NOT done here is a process-wide
    # running `concrete` set across levels: it is a strict SUPERSET of any
    # one level's corpus (a sibling's names, and a dropped part's names,
    # live in it but not in this level's `parts`), and a superset drops
    # parts the per-level computation keeps — a silent output change. The
    # same reasoning rejected it on 2026-09-26.
    concrete = set()
    variadic_by_part = []
    for p in parts:
        entry = _DEDUP_EXTERN_PARTS_CACHE.get(p)
        if entry is None:
            entry = _parse_part(p)
            _DEDUP_EXTERN_PARTS_CACHE[p] = entry
        part_concrete, part_variadic = entry
        for name in part_concrete:
            concrete.add(name)
        variadic_by_part.append(part_variadic)
    if not concrete:
        out = '\n'.join(parts)
        _record_output_parse(out, parts, concrete, variadic_by_part)
        return out
    kept = []
    kept_variadic = []
    dropped = False
    for i in range(len(parts)):
        drop = False
        for name in variadic_by_part[i]:
            if name in concrete:
                drop = True
                break
        if not drop:
            kept.append(parts[i])
            kept_variadic.append(variadic_by_part[i])
        else:
            dropped = True
    out = '\n'.join(kept)
    # Nothing dropped ⇒ the set just built IS the output's exact name set,
    # so hand the same object over rather than rebuilding it.
    _record_output_parse(out, kept, None if dropped else concrete, kept_variadic)
    return out


# ── Phase 3 (doc/OWNERSHIP_MODEL.md) codegen wiring — TODO item 1 ──────────
#
# Scope, deliberately narrow (see the doc's TODO checklist): only emits a
# real `mojo_*_free` for a local container this function PROVABLY, solely,
# permanently owns (ownership_destruct.py's analysis — escape analysis
# composed with definite-assignment, both validated against a 664-file real
# Modular stdlib sweep before this wiring existed), and ONLY for a function
# containing no `try`/`except` and no nested `def`/`async def`/`lambda`
# anywhere in its body. Both exclusions sidestep open, unresolved problems
# rather than guess at them: a `try`/`except` here would need the free to
# survive `mojo_raise`'s raw `longjmp` unwind (it currently would NOT —
# see doc/OWNERSHIP_MODEL.md's exception-handling cross-cutting section),
# and a nested closure's capture could extend a binding's real lifetime
# past this function's own return (the async/coroutine cross-cutting
# section, still just a design TODO, not implemented). Loop-body-scoped
# containers are also out of scope for now — not because of a codegen
# limitation, but because ownership_destruct.py's own escape analysis
# only ever credits a name assigned via a SINGLE static assignment in the
# whole function (its rule 2), which a loop-body assignment never is.







_OWNED_FREE_RUNTIME_FN = {
    'MojoDict *': 'mojo_dict_free',
    'MojoList *': 'mojo_list_free',
    'MojoSet *': 'mojo_set_free',
}

# doc/OWNERSHIP_MODEL.md's exception-handling option 2 (TODO item 3): a
# cleanup thunk pushed right after a candidate's single constructing
# assignment, cancelled (without invoking) at the exact free call
# `_emit_owned_local_frees` already emits below. `mojo_raise`'s longjmp
# skips that free call entirely on any exception path reached before a
# candidate's owning return/fallthrough runs — this is what lets
# `mojo_raise` (runtime/fire_runtime.c) still free it in that case.
_OWNED_PUSH_RUNTIME_FN = {
    'MojoDict *': 'mojo_cleanup_push_dict',
    'MojoList *': 'mojo_cleanup_push_list',
    'MojoSet *': 'mojo_cleanup_push_set',
}


def _owned_free_runtime_fn(ctype) -> str:
    """`_OWNED_FREE_RUNTIME_FN.get(ctype)`, but as an explicit if/elif
    chain rather than a dict `.get()` — self-hosted codegen has no
    mechanism that tracks a MODULE-LEVEL dict LITERAL's VALUE type
    (`_global_dict_val_types` exists but is never populated anywhere;
    confirmed by grep), so `.get()` on one of these small string->string
    tables returned its result mislabeled as a generic `int64_t`, and
    interpolating that into an f-string (`f"  {runtime_fn} ({name});"`)
    printed the raw pointer decimal instead of the function name
    (`4346281880 (items);` instead of `mojo_list_free (items);` — a
    real, reproducible `make bootstrap` divergence). An explicit
    if/elif's each branch returns a STRING LITERAL directly, which is
    always correctly typed."""
    if ctype == 'MojoDict *':
        return 'mojo_dict_free'
    if ctype == 'MojoList *':
        return 'mojo_list_free'
    if ctype == 'MojoSet *':
        return 'mojo_set_free'
    return ''


def _owned_push_runtime_fn(ctype) -> str:
    """`_OWNED_PUSH_RUNTIME_FN.get(ctype)` — see `_owned_free_runtime_fn`
    for why this can't be a dict `.get()` call under self-hosting."""
    if ctype == 'MojoDict *':
        return 'mojo_cleanup_push_dict'
    if ctype == 'MojoList *':
        return 'mojo_cleanup_push_list'
    if ctype == 'MojoSet *':
        return 'mojo_cleanup_push_set'
    return ''


def _struct_ptr_owned(gen, name: str, ctype) -> bool:
    """`name` is a local bound to a struct instance this function owns: its C
    type is a pointer to a struct the analysis vetted AND it passed the
    declaration gate (`maybe_push_owned_local` pushed it). The second condition
    matters: a candidate that never went through the gate — whatever its type —
    must never be freed just because it is a candidate."""
    if ctype is None or not ctype.endswith(' *'):
        return False
    base = ctype[:-2].strip()
    if ctype != 'char *' and (base not in gen._analysis_structs or base not in gen.struct_field_types):
        return False
    return name in gen._owned_free_pushed


def _owned_stack_push_runtime_fn(ctype) -> str:
    """The cleanup-stack push for a STACK-homed container of `ctype` (the
    `_STACK` kinds tear down buffers only, never `free()` the struct); an
    explicit if-chain for the same self-hosting reason as
    `_owned_free_runtime_fn`."""
    if ctype == 'MojoDict *':
        return 'mojo_cleanup_push_dict_stack'
    if ctype == 'MojoList *':
        return 'mojo_cleanup_push_list_stack'
    if ctype == 'MojoSet *':
        return 'mojo_cleanup_push_set_stack'
    return ''


def _literal_ctor_ctype(node) -> str | None:
    """`node` is a container LITERAL (list/dict/set display, any contents) ->
    its ctype, else None. `dict()`/`list()`/`set()` calls are not literals:
    with no arguments they are the empty-constructor case, with arguments
    they take other lowering paths that do not honour a storage request."""
    if isinstance(node, DictExpr):
        return 'MojoDict *'
    if isinstance(node, ListExpr):
        return 'MojoList *'
    if isinstance(node, SetExpr):
        return 'MojoSet *'
    return None


def emit_container_new(gen, t: str, ctype: str) -> None:
    """Emit the allocation of a container LITERAL into temp `t`: an `_init` of
    the stack storage `maybe_stack_alloc_owned_ctor` reserved for this exact
    statement if one is pending for `ctype`, else the usual heap
    `mojo_*_new()`. The request is consumed here, at literal ENTRY (before the
    elements are lowered), so a nested literal never takes the outer one's
    storage."""
    st = gen._literal_storage
    if st != '' and gen._literal_storage_ctype == ctype:
        gen._literal_storage = ''
        gen._emit(f"  {_OWNED_STACK_KIND[ctype][0]} (&{st});")
        gen._emit(f"  {t} = &{st};")
        return
    if ctype == 'MojoDict *':
        gen._emit(f"  {t} = mojo_dict_new ();")
    elif ctype == 'MojoSet *':
        gen._emit(f"  {t} = mojo_set_new ();")
    else:
        gen._emit(f"  {t} = mojo_list_new ();")


def _drop_owned_candidate(gen, name: str) -> None:
    """`name` stops being owned: not a function-level candidate and not armed
    for its loop body, so no allocation, push or free is ever emitted for it."""
    gen._owned_free_candidates.discard(name)
    gen._scope_armed.discard(name)


def _container_keys_safe(gen, name: str, ctype) -> bool:
    """A dict or set owns its key/element strings, so it may be torn down at
    scope exit only if no key it handed out by iteration can outlive it
    (ownership_destruct.key_views_consumed). Any other type is unaffected."""
    if ctype != 'MojoDict *' and ctype != 'MojoSet *':
        return True
    return _key_views_ok(gen._own_fn_body, name)


def maybe_push_owned_local(gen, name: str, value=None) -> None:
    """Call once, right after lowering ANY statement whose sole target is
    the plain identifier `name` (a `VarDecl` or a single-target
    `AssignStmt`) — see the two call sites in gimple_gen_stmts.py's
    central `gen_stmt` dispatcher. A no-op unless `name` is one of the
    enclosing function's Phase-3 owned-free candidates (`begin_function`)
    and hasn't already been pushed this function. Single static assignment
    (ownership_destruct.py's rule 2) means a real candidate's constructing
    assignment is reached at most once per invocation, so the "already
    pushed" guard should never actually trigger — it exists so a future
    relaxation of that analysis fails closed (skips the push, today's
    pre-existing exception-path leak) rather than double-pushing the same
    pointer onto the cleanup stack."""
    # Direct attribute access (not `getattr(gen, ..., default)`): the
    # field is unconditionally declared in `GimpleGen.__init__` now, and
    # `getattr()` on a self-hosted struct goes through the GENERIC
    # dynamic-dispatch path (`_mojo_dispatch_getattr`), which returns an
    # opaque value with no element-type metadata — the plain attribute
    # read below is what lets `_field_elem_types` (set once, in
    # `begin_function`) actually reach this set's elements as `char *`
    # instead of defaulting them to `int64_t` (see `begin_function`'s
    # own docstring for the full story and the segfault this caused).
    candidates = gen._owned_free_candidates
    if name not in candidates and name not in gen._scope_armed:
        return
    pushed = gen._owned_free_pushed
    if name in pushed:
        return
    # A CAPTURING LAMBDA bound to this name: the value is a `MojoBoundMethod`
    # plus the environment its constructor allocated with it, and the two are
    # one allocation unit. It is not a container, so it does not go through the
    # freshness/`var_types` machinery below — `_closure_vals` is the record
    # that the value really is one (the non-capturing lambda case, which is a
    # bare static function pointer and allocates nothing, never appears there).
    if gen._decl_rhs_val != '' and gen._decl_rhs_val in gen._closure_vals:
        gen._closure_vals.discard(gen._decl_rhs_val)
        if not _lambda_owned(gen._own_fn_body, name):
            _drop_owned_candidate(gen, name)
            return
        gen._owned_closure_names.add(name)
        gen._emit(f"  mojo_cleanup_push_closure ({name});")
        pushed.add(name)
        if name in gen._scope_armed:
            _scope_register(gen, name, 'mojo_closure_free')
        return
    # A declaration whose value is not a container display (a call, a slice, a
    # comprehension, a `+`) only MAY have built a fresh container — the
    # analysis credited the name on that "maybe". Ownership is kept only when
    # the value is provably fresh HERE: a producer expression whose lowered
    # value is a temp a fresh-returning action created and nothing has claimed.
    # Anything else (a call returning a stored container, an alias) means the
    # name does not own its value, so it stops being a candidate at this
    # declaration and nothing about it is ever freed.
    # A declaration whose value is a container the runtime built and that
    # SOLELY owns its string elements (see `_OWNS_STR_ELEMS`); decided once,
    # here, where the value is still the temp the producing call returned.
    owns_str_elems = False
    if value is not None and not _is_ctor_display(value):
        rhs = gen._decl_rhs_val
        if rhs == '' or not is_fresh_container_operand(gen, value, rhs):
            candidates.discard(name)
            return
        gen._fresh_vals.discard(rhs)
        # The NAME inherits the property, because the free is emitted for the
        # name at the scope exit, long after the temp is gone.
        if rhs in gen._owned_str_elem_vals:
            gen._owned_str_elem_vals.discard(rhs)
            if not _list_elements_ok(gen._own_fn_body, name):
                # The list owns its strings, but the program may hand an
                # element pointer out (`kept.append(parts[0])`), and the
                # element free would then dangle. Fail closed to the plain
                # `mojo_list_free`: a few bytes leak instead.
                owns_str_elems = False
            else:
                owns_str_elems = True
                gen._owned_str_elem_names.add(name)
        # A fresh STRING is owned only if no method call on it can hand back
        # the receiver itself (`t = s.strip()` may alias `s`): see
        # ownership_destruct.receiver_results_consumed.
        if gen.var_types.get(name) == 'char *' and not _string_uses_ok(gen._own_fn_body, name):
            candidates.discard(name)
            gen._owned_str_elem_names.discard(name)
            return
    ctype = gen.var_types.get(name)
    if not _container_keys_safe(gen, name, ctype):
        _drop_owned_candidate(gen, name)
        return
    # A non-empty literal was lowered with a stack-storage request
    # (`maybe_stack_alloc_owned_ctor`): consumed -> the value lives in that
    # storage and is torn down with `_destroy`; still pending -> nothing took
    # it, the value is an ordinary heap allocation and the request is dropped.
    on_stack = False
    if gen._literal_storage_ctype != '':
        on_stack = gen._literal_storage == '' and gen._literal_storage_ctype == ctype
        gen._literal_storage = ''
        gen._literal_storage_ctype = ''
    if on_stack:
        gen._owned_stack_allocated.add(name)
        push_fn = _owned_stack_push_runtime_fn(ctype)
        free_fn = _owned_destroy_runtime_fn(ctype)
        if push_fn == '' and ctype is not None and ctype.endswith(' *'):
            # A stack-homed struct instance has nothing to tear down (no
            # buffers of its own are owned through it) and nothing to unwind:
            # record the name as handled and register no free.
            pushed.add(name)
            if name in gen._scope_armed:
                _scope_register(gen, name, '')
    else:
        if owns_str_elems and ctype == 'MojoList *':
            push_fn = 'mojo_cleanup_push_list_strs'
            free_fn = 'mojo_list_free_owned_strs'
        else:
            push_fn = _owned_push_runtime_fn(ctype)
            free_fn = _owned_free_runtime_fn(ctype)
        if push_fn == '' and ctype is not None and ctype.endswith(' *'):
            # A struct instance (a constructor call of a vetted struct): a plain
            # heap block, torn down with free() and, on an exception, by a PTR
            # thunk. Vetting is the analysis table; here only its C type is
            # checked, because `_lower_call` marks only vetted constructors
            # fresh, which the declaration gate above already required.
            _base = ctype[:-2].strip()
            if (_base in gen._analysis_structs and _base in gen.struct_field_types) or ctype == 'char *':
                # A struct instance or a heap string: a plain malloc block.
                push_fn = 'mojo_cleanup_push_ptr'
                free_fn = 'free'
    if push_fn:
        # `_cname(name)`, not `name`: `_declare_var` renames a local whose Mojo
        # name is a C keyword (`var unsigned = ...` in the stdlib's
        # test_range.mojo -> `_unsigned`) and records that in `_c_names`, so
        # every ordinary read/write goes through the renamed identifier. The
        # cleanup push is emitted from the OWNERSHIP analysis, which works in
        # Mojo-level names and never consulted `_c_names` — so it wrote
        # `mojo_cleanup_push_list (unsigned);`, and GCC read `unsigned` as the
        # type keyword: "expected expression before 'unsigned'". The free at
        # `_emit_owned_local_frees` below had the identical bug on the same
        # name.
        gen._emit(f"  {push_fn} ({gen._cname(name)});")
        pushed.add(name)
        if name in gen._scope_armed:
            _scope_register(gen, name, free_fn)


def _emit_owned_local_frees(gen):
    """Emits a `mojo_*_free(name);` call for every name in
    `gen._owned_free_candidates` whose C type is currently known (via
    `gen.var_types`) to be one of the three boxed container types — called
    once per `return` statement (gimple_gen_stmts.py's
    `_gen_stmt_ReturnStmt`) and once more for a function's natural
    fallthrough exit (gimple_gen_funcs.py's `gen_func`), so a function
    with N return points gets its eligible locals freed on all N of them,
    consistent with `ownership_destruct.py`'s definite-assignment
    guarantee (assigned, and never escaped, on every path to every exit).
    A candidate whose type isn't resolved to one of the three container
    types by the time this runs (e.g. codegen hadn't reached its
    constructing assignment yet, or it inferred to something else) is
    silently skipped — this is a memory-usage improvement layered on top
    of an already-working compiler, never a step that may itself turn a
    correct program incorrect, so any uncertainty here resolves to "don't
    free" (today's pre-existing leak), not "free anyway"."""
    # sorted(): `_owned_free_candidates` is a plain Python `set` (from
    # ownership_destruct.py), whose iteration order depends on hash-seed
    # randomization — iterating it directly here made the ORDER of
    # emitted free calls (for a function with 2+ candidates) vary between
    # otherwise-identical process invocations. This is exactly the class
    # of bug `make bootstrap`'s byte-identity check exists to catch, and
    # it did: stage1-vs-stage2 `fire.ci` differed with this bug present.
    # A fixed, deterministic order is required output, not a style choice.
    # Direct attribute access — see `maybe_push_owned_local`'s identical
    # note just above for why `getattr(gen, ..., default)` must not be
    # used here.
    stack_allocated = gen._owned_stack_allocated
    freed = 0
    for name in sorted(gen._owned_free_candidates):
        ctype = gen.var_types.get(name)
        # A stack-allocated candidate (Phase 6) must be torn down via
        # `_destroy` (buffer-only), never `_free` — the struct itself
        # lives in this function's own stack frame, not on the heap; see
        # this file's "Phase 6" section.
        if name in stack_allocated:
            runtime_fn = _owned_destroy_runtime_fn(ctype)
        elif name in gen._owned_closure_names:
            # A bound method and the environment it owns (see mojo_closure_free).
            runtime_fn = 'mojo_closure_free'
        elif name in gen._owned_str_elem_names and ctype == 'MojoList *':
            # Decided at the DECLARATION, where the value was still the temp a
            # `_OWNS_STR_ELEMS` function returned; re-derived here from
            # `var_types` it would be indistinguishable from any other list,
            # and the wrong free either leaks the strings or frees borrowed
            # ones.
            runtime_fn = 'mojo_list_free_owned_strs'
        else:
            runtime_fn = _owned_free_runtime_fn(ctype)
            if runtime_fn == '' and _struct_ptr_owned(gen, name, ctype):
                runtime_fn = 'free'
        if runtime_fn:
            # `_cname(name)`, for the same reason as the cleanup push in
            # `_maybe_push_owned_local` — a keyword-named local is declared
            # under a renamed identifier and must be freed under it too.
            gen._emit(f"  {runtime_fn} ({gen._cname(name)});")
            freed += 1
    # Block-scoped candidates still live at this exit (a `return` inside a
    # loop body, after the declaration): the same free, the same cancel.
    freed += _emit_scope_frees(gen, 0)
    # Cancel exactly the thunks this free just handled inline, so
    # mojo_raise's unwind (if this exact return/fallthrough is later
    # re-executed... it can't be, but see below) never double-frees them.
    # `freed` here always equals the number of this function's OWN
    # still-live pushes at this point: anything a callee itself pushed is
    # already cancelled by the time it returns (same invariant, applied
    # recursively), and this function has no try of its own to interleave
    # a nested checkpoint with (see `_is_free_eligible_function`) — so the
    # top `freed` entries on the global cleanup stack are provably these
    # candidates' own, in any order, cancel-by-count is exact rather than
    # merely conservative.
    if freed:
        gen._emit(f"  mojo_cleanup_cancel_n ({freed});")


# ── Block-scoped destruction (doc/MEMORY.html §7.1) ─────────────────────────
#
# `ownership_destruct.analyze_scoped_locals` names the locals that a LOOP BODY
# owns: assigned once, from a constructor, as a direct child statement of the
# body, never escaping, and mentioned nowhere outside the body from that
# declaration on. Because the declaration is straight-line inside one block,
# every path that reaches the end of the body, or a `break`/`continue`/
# `return` lexically after it, has executed it — so the free needs no
# definite-assignment proof, only these three emission points:
#
#   1. the end of the body           -> `gen_loop_body` (falls through)
#   2. `break`/`continue`            -> `emit_loop_exit_frees`
#   3. `return` anywhere inside      -> `_emit_owned_local_frees`
#
# and an exception is covered by the same cleanup-thunk stack the function-
# level candidates use (a push at the declaration, a cancel at the free).
#
# FAIL-CLOSED by construction. A name is only freed if `gen_loop_body` ARMED it
# — i.e. lowered the very body it is declared in — so a loop lowering that has
# not been routed through `gen_loop_body` (the regex-scan helpers, the
# compile-time-unrolled comprehension loop) simply keeps today's behaviour: the
# container leaks, nothing is freed twice. `break`/`continue` free only the
# entries whose recorded loop depth equals the current `len(gen.loop_stack)`, so
# a `break` in an unhooked inner loop can never free an enclosing loop's locals.
# What `gen._scope_live*` records per declared name is the free function chosen
# AT THE DECLARATION (matching the thunk that was pushed), not re-derived at the
# exit from `var_types`, so the push and its cancel cannot disagree.

def _reset_scope_state(gen) -> None:
    """Per-function block-scope state. `_scope_live*` are parallel lists (name,
    loop depth at the declaration, free function or '' when nothing was
    pushed) in declaration order; `_scope_armed` is the set of names whose
    declaring body is being lowered right now."""
    gen._literal_storage = ''
    gen._literal_storage_ctype = ''
    gen._own_fn_body = []
    gen._scoped_free_candidates = set()
    gen._scope_armed = set()
    gen._scope_live = []
    gen._scope_live_depth = []
    gen._scope_live_fn = []
    # Per-FUNCTION ownership state, reset here and NOT in `_reset_func`:
    # a lifted closure runs `_reset_func` in the middle of its parent, and the
    # parent's entries have to survive that intact (they are what the parent's
    # own scope exit frees). `_owned_str_elem_vals` is a table of temps but
    # belongs to the same decision as `_owned_str_elem_names` — a push and its
    # cancel must not disagree — so it moves with it.
    gen._owned_str_elem_names = set()
    gen._owned_str_elem_vals = set()
    gen._owned_closure_names = set()
    # See `begin_function`'s note: self-hosting cannot infer a set/list
    # field's element type from an assignment, only from this table.
    _fet = gen._field_elem_types.setdefault('GimpleGen', {})
    _fet['_scoped_free_candidates'] = 'char *'
    _fet['_scope_armed'] = 'char *'
    _fet['_scope_live'] = 'char *'
    _fet['_scope_live_fn'] = 'char *'
    _fet['_owned_str_elem_names'] = 'char *'
    _fet['_owned_str_elem_vals'] = 'char *'
    _fet['_owned_closure_names'] = 'char *'
    _fet['_fresh_vals'] = 'char *'
    _fet['_fresh_str_tmps'] = 'char *'
    _fet['_boxed_vals'] = 'char *'


def _scope_register(gen, name: str, fn: str) -> None:
    """Record that `name` is now live in the enclosing loop body, to be freed by
    `fn` (a runtime free/destroy function name) at every exit of that body."""
    gen._scope_live.append(name)
    gen._scope_live_depth.append(len(gen.loop_stack))
    gen._scope_live_fn.append(fn)


def _emit_scope_frees(gen, lo: int) -> int:
    """Emit the free of every live entry from index `lo` to the end (newest
    first) and return how many frees were emitted — the caller adds the
    matching `mojo_cleanup_cancel_n`. An entry whose declaration pushed no
    thunk has fn '' and is skipped, so frees and cancels always pair."""
    n = 0
    i = len(gen._scope_live) - 1
    while i >= lo:
        fn = gen._scope_live_fn[i]
        if fn != '':
            gen._emit(f"  {fn} ({gen._cname(gen._scope_live[i])});")
            n += 1
        i -= 1
    return n


def _emit_scope_end(gen, mark: int) -> None:
    """Close a loop body: free what it declared (unless the body already ended
    in a jump/return, in which case every exit was handled where it happened)
    and forget those entries."""
    if len(gen._scope_live) <= mark:
        return
    if not gen._last_was_terminal:
        n = _emit_scope_frees(gen, mark)
        if n:
            gen._emit(f"  mojo_cleanup_cancel_n ({n});")
    gen._scope_live = gen._scope_live[:mark]
    gen._scope_live_depth = gen._scope_live_depth[:mark]
    gen._scope_live_fn = gen._scope_live_fn[:mark]


def gen_loop_body(gen, body: list) -> None:
    """THE way to lower the statements of a `for`/`while` body. Every loop
    lowering routes through here so block-scoped locals have exactly one place
    where their scope opens and closes (a body that declares none costs one
    set lookup)."""
    scoped = gen._scoped_free_candidates
    if not scoped:
        for s in body:
            gen.gen_stmt(s)
        return
    names: list = []
    for s in body:
        nm = _scope_decl_name(s)
        if nm != '' and nm in scoped:
            names.append(nm)
    mark = len(gen._scope_live)
    for nm in names:
        gen._scope_armed.add(nm)
        # A body can be lowered more than once (the dict-vs-list dynamic
        # dispatch lowers it once per arm): each lowering is its own emission
        # of the declaration, with its own storage, push and free.
        gen._owned_free_pushed.discard(nm)
        gen._owned_stack_allocated.discard(nm)
    for s in body:
        gen.gen_stmt(s)
    _emit_scope_end(gen, mark)
    for nm in names:
        gen._scope_armed.discard(nm)


def emit_loop_exit_frees(gen) -> None:
    """Call from `break`/`continue` lowering, before the jump: free the locals
    declared directly in the loop body being left (the entries recorded at the
    current loop depth, which are always the newest ones)."""
    if not gen._scope_live or gen._last_was_terminal:
        return
    cur = len(gen.loop_stack)
    end = len(gen._scope_live)
    lo = end
    while lo > 0 and gen._scope_live_depth[lo - 1] == cur:
        lo -= 1
    if lo == end:
        return
    n = _emit_scope_frees(gen, lo)
    if n:
        gen._emit(f"  mojo_cleanup_cancel_n ({n});")


# ── Phase 6 (doc/OWNERSHIP_MODEL.md) — stack allocation ─────────────────
#
# Scope, deliberately narrow (directed to start here, ahead of Phases 4-5,
# 2026-09-15): only a Phase-3 candidate whose single constructing
# assignment is an EMPTY container literal/call (`{}`, `[]`, `set()`,
# bare `dict()`/`list()`/`set()` with no args) gets stack-allocated. This
# sidesteps reusing `_lower_dict_literal`/`_lower_list_literal`/
# `_lower_set_literal`'s much more involved non-empty-population logic
# (element-type inference, spread handling, per-element append dispatch)
# entirely — an empty container needs no population at all, just an
# `_init` call, and every subsequent statement that fills it in
# (`d[k] = v`, `lst.append(x)`) already works identically against a
# stack-backed `MojoDict *`/`MojoList *` as it does against a heap one,
# since those go through the exact same runtime setter calls either way.
# A non-empty-literal candidate (e.g. `l: List[Int] = [1]`, a real
# ownership_destruct.py-validated stdlib example) is simply NOT stack-
# allocated in this v0 — it keeps today's exact heap alloc + `mojo_*_free`
# behavior, tracked via `_owned_stack_allocated` staying empty for it, so
# nothing here can ever leak or double-free a case it doesn't explicitly
# handle: the "did this get stack-allocated" question always has a
# concrete, per-name answer, never an assumption.
#
# Verified safe to take `&<local struct>` here at all (this project's own
# history has a real precedent for `-fgimple` REJECTING address-taken
# locals — see `_seed_addressed_locals`/`general-mut-closure-capture-fix`
# in memory): confirmed empirically via `gcc -fgimple -fsyntax-only` that
# an ordinary, non-`__GIMPLE`-tagged function accepts this exact pattern
# (`MojoDict __d_storage; MojoDict * d; d = &__d_storage;`) while the
# identical code marked `__GIMPLE` does not. Phase-3 candidates only ever
# live in plain top-level functions — `_is_free_eligible_function`
# excludes any function containing a nested `def`/`lambda`/being itself
# `async`/a generator, and `gen_func`'s own top-level function header
# emission never applies the `__GIMPLE` tag at all (only struct methods
# and a few synthesized helpers do, via `gimple_gen_funcs.py`'s
# `_gen_struct_method`/`gimple_module_gen.py`'s `_alloc_<sn>` — neither of
# which Phase 3 ever computes candidates for; see `reset_no_candidates`
# above) — so this is unconditionally safe for every candidate this
# module can ever produce, not just the cases actually tested.

_OWNED_STACK_KIND = {
    'MojoDict *': ('mojo_dict_init', 'MojoDict'),
    'MojoList *': ('mojo_list_init', 'MojoList'),
    'MojoSet *':  ('mojo_set_init',  'MojoSet'),
}

def ann_container_ctype(gen, ann):
    """The container ctype a binding statement's OWN annotation names, when
    it names one of the three owned-stack container kinds; else None.

    `var s: Set[Int] = {}` — the annotation is the ground truth about what
    `s` is, and an EMPTY `{}` is evidence for no kind at all (an empty dict,
    list and set are equally "nothing"), so the destination's declared kind
    is what both the storage decision (`maybe_stack_alloc_owned_ctor` below)
    and the coercion (`gimple_ctypes.reify_empty_container_literal`) have to
    build. Resolving the annotation to `MojoDict *` because the literal's own
    default lowering is a dict is what made `s.add(i)` a silent no-op on a
    `MojoDict` header and the variable print `{}` forever. A non-container
    annotation, or one this codegen cannot resolve, answers None and leaves
    every existing decision exactly as it was.

    Lives here, beside the `_OWNED_STACK_KIND` table whose keys it is
    restricted to, because that table is the whole answer: the question is
    only ever "is this annotation one of the three container kinds this
    feature stack-allocates?", and both consumers (the storage decision and
    the `AssignStmt` ctype override) ask it from different modules."""
    if not isinstance(ann, str) or not ann:
        return None
    try:
        _ct = gen._resolve_type(ann)
    except Exception:
        return None
    return _ct if _ct in _OWNED_STACK_KIND else None


_OWNED_DESTROY_RUNTIME_FN = {
    'MojoDict *': 'mojo_dict_destroy',
    'MojoList *': 'mojo_list_destroy',
    'MojoSet *':  'mojo_set_destroy',
}


def _owned_destroy_runtime_fn(ctype) -> str:
    """`_OWNED_DESTROY_RUNTIME_FN.get(ctype)` — see `_owned_free_
    runtime_fn`'s docstring for why this can't be a dict `.get()` call
    under self-hosting."""
    if ctype == 'MojoDict *':
        return 'mojo_dict_destroy'
    if ctype == 'MojoList *':
        return 'mojo_list_destroy'
    if ctype == 'MojoSet *':
        return 'mojo_set_destroy'
    return ''

_OWNED_STACK_PUSH_RUNTIME_FN = {
    'MojoDict *': 'mojo_cleanup_push_dict_stack',
    'MojoList *': 'mojo_cleanup_push_list_stack',
    'MojoSet *':  'mojo_cleanup_push_set_stack',
}




def _vetted_struct_ctor_name(gen, value) -> str:
    """`S` when `value` is a constructor call `S(...)` of a struct the ownership
    analysis vetted (its `__init__` retains nothing, no base class) and whose
    layout codegen knows; '' otherwise."""
    if not (isinstance(value, CallExpr) and isinstance(value.func, IdentExpr)):
        return ''
    sname = _as_str(value.func.name)
    if sname in gen._analysis_structs and sname in gen.struct_field_types \
            and sname not in gen._dict_subclass_structs:
        return sname
    return ''


def maybe_stack_alloc_owned_ctor(gen, name: str, value, ann=None) -> bool:
    """Call from gimple_gen_stmts.py's central `gen_stmt` dispatcher
    BEFORE lowering a `VarDecl`/single-target `AssignStmt` normally (a
    plain identifier `name` bound to `value`) — returns True if it fully
    handled the statement (stack-allocated `name`), in which case the
    caller must SKIP its own normal lowering of this statement entirely;
    False means "not applicable, lower it normally" (not a candidate, not
    an empty-constructor shape, or — belt-and-suspenders — already
    handled, which single static assignment should make impossible).

    `ann` is the binding statement's OWN type annotation, and BOTH of the
    things this path decides from it exist because this path handles the
    statement WHOLE: the two ordinary statement paths in
    gimple_gen_stmts.py never see a binding this function claims.

    * The CONTAINER KIND. `_empty_ctor_ctype` answers `MojoDict *` for every
      `{}` because `{}` is a dict DISPLAY — the right answer for a display,
      the wrong one for `var s: Set[Int] = {}`, where the storage allocated
      here, the C type the variable is declared with, and the runtime
      push/destroy pair all followed the display: `s.add(i)` became a no-op
      against a `MojoDict` header and `print(s)` said `{}` no matter what
      was added. An empty literal is evidence for NO kind, so the
      declaration's own annotation decides (`ann_container_ctype` above) —
      the same premise `reify_empty_container_literal` is built on for the
      non-stack-allocated path.

    * The ELEMENT TYPE (`_annotation_container_elem_type` in
      mojo/middle/stmts_shared.py). So `kept: List[String] = []` — the shape
      that IS stack-allocated, because `[]` is an empty constructor — lost
      the one piece of type information its own annotation carried, and a
      list filled only from a callee read back as ints
      (bugs/CODEGEN_list_of_string_read_as_int_when_filled_in_a_callee.md,
      closed and removed with the annotation-seeding fix)."""
    # Direct attribute access — see `maybe_push_owned_local`'s note.
    candidates = gen._owned_free_candidates
    if name not in candidates and name not in gen._scope_armed:
        return False
    pushed = gen._owned_free_pushed
    if name in pushed:
        return False
    ctype = _empty_ctor_ctype(value)
    _ann_ct = ann_container_ctype(gen, ann) if ctype is not None else None
    if _ann_ct is not None:
        ctype = _ann_ct
    _kind = ctype if ctype is not None else _literal_ctor_ctype(value)
    if _kind is not None and not _container_keys_safe(gen, name, _kind):
        _drop_owned_candidate(gen, name)
        return False
    if ctype is None:
        # A NON-EMPTY literal (`[1, 2, i]`, `{"a": 1}`, `{1, 2}`) keeps its own
        # element-type inference and per-element population, so it is not
        # lowered here; instead this reserves stack storage and posts a
        # request that the literal's own lowering consumes at entry
        # (`emit_container_new`), turning its `mojo_*_new()` into an `_init` of
        # this storage. `maybe_push_owned_local` runs right after the
        # statement and finishes the job — or, if the request was never
        # consumed (some other lowering path took the value), falls back to the
        # ordinary heap candidate. Returns False: the caller lowers normally.
        lit = _literal_ctor_ctype(value)
        if lit is None:
            # A constructor call of a vetted struct: reserve frame storage for
            # the instance the same way (consumed by `_lower_struct_constructor`).
            _sname = _vetted_struct_ctor_name(gen, value)
            if _sname == '':
                return False
            gen.temp_counter += 1
            gen.decls.append(f"  {_sname} _owned_storage{gen.temp_counter}_{name};")
            gen._literal_storage = f'_owned_storage{gen.temp_counter}_{name}'
            gen._literal_storage_ctype = f"{_sname} *"
            return False
        _init_fn, _struct = _OWNED_STACK_KIND[lit]
        gen.temp_counter += 1
        gen.decls.append(f"  {_struct} _owned_storage{gen.temp_counter}_{name};")
        gen._literal_storage = f'_owned_storage{gen.temp_counter}_{name}'
        gen._literal_storage_ctype = lit
        return False
    init_fn, struct_name = _OWNED_STACK_KIND[ctype]
    gen.temp_counter += 1
    storage = f'_owned_storage{gen.temp_counter}_{name}'
    gen.decls.append(f"  {struct_name} {storage};")
    gen._emit(f"  {init_fn} (&{storage});")
    gen._declare_var(name, ctype,
                     _annotation_container_elem_type(gen, ann, ctype))
    gen._emit(f"  {gen._write_dest(name)} = &{storage};")
    push_fn = _OWNED_STACK_PUSH_RUNTIME_FN[ctype]
    gen._emit(f"  {push_fn} ({gen._cname(name)});")
    pushed.add(name)
    gen._owned_stack_allocated.add(name)
    if name in gen._scope_armed:
        _scope_register(gen, name, _owned_destroy_runtime_fn(ctype))
    return True


# ── Public entry points — the ONLY things gimple_gen_funcs.py/
# gimple_gen_stmts.py should call for this feature. Everything above this
# line (the eligibility check, the candidate analysis, the runtime-
# function table, `gen._owned_free_candidates` as the storage attribute)
# is a private implementation detail of THIS module; a caller needing a
# behavior change here should never need to know that attribute name or
# reach past these public entry points. Keeping the whole feature's logic
# in this one file (this section plus the private helpers just above it) —
# not spread across the two codegen files that merely call in at the two
# points they naturally own (a function's start, and each return
# statement) — is deliberate, per doc/OWNERSHIP_MODEL.md's engineering
# standard for this project's own code, not just the Mojo semantics it
# implements.

def begin_function(gen, fn) -> None:
    """Call once, in gimple_gen_funcs.py's `gen_func`, before lowering
    `fn`'s body. Must run before any statement is lowered, since
    `emit_return_frees` below needs the result available at every
    `return` encountered DURING that lowering, not just after it.

    The `_field_elem_types` line below is LOAD-BEARING, not stylistic.
    `_owned_free_candidates` is assigned here from a value returned by a
    long call chain (`ownership_destruct.py`'s `_FuncFacts.candidates()`
    -> `analyze_function()` -> `_definitely_assigned()` ->
    `_compute_owned_free_candidates()`), and every hop in that chain now
    has its OUTER return type correctly annotated `-> set` — but this
    self-hosted compiler has no general mechanism that carries a
    container's ELEMENT type across a `self.field = <call result>`
    assignment (`_field_elem_types`, the mechanism that WOULD carry it,
    is only ever populated by `.append()`/`.add()` call sites that
    already know they're writing through a tracked struct field — see
    gimple_gen_methods.py — never by a plain assignment). Left unset,
    every later read of this field (`_emit_owned_local_frees`'s
    `sorted(gen._owned_free_candidates)` loop) defaulted its elements to
    the generic `int64_t` fallback and segfaulted downstream (`gen.
    var_types.get(name)` handed a raw boxed pointer mislabeled as an
    int to a string-keyed dict lookup — confirmed via lldb: `strcmp`
    with a NULL operand inside `mojo_dict_get_int`). `_owned_free_
    candidates`'s elements are ALWAYS local-variable-name strings, an
    invariant of `ownership_destruct.py`'s own algorithm (never anything
    else), so hardcoding this one field's element type here — the exact
    established pattern `.append()`'s own propagation already uses,
    just triggered manually instead of automatically at the one
    assignment site automatic propagation can't reach — is correct
    permanently, not a one-off workaround for today's specific bug."""
    gen._owned_free_candidates = (_compute_owned_free_candidates(fn, gen._analysis_funcs, gen._analysis_structs)
                                  | _compute_closure_candidates(fn))
    gen._field_elem_types.setdefault('GimpleGen', {})['_owned_free_candidates'] = 'char *'
    gen._owned_free_pushed = set()
    gen._owned_stack_allocated = set()
    _reset_scope_state(gen)
    gen._own_fn_body = fn.body
    gen._int_keyed_dicts = _compute_int_keyed_dicts(fn)
    gen._scoped_free_candidates = _compute_scoped_free_candidates(fn, gen._owned_free_candidates, gen._analysis_funcs, gen._analysis_structs)
    # A lambda local declared in a LOOP BODY is owned by the body, on the same
    # terms as a container local there (`analyze_scoped_locals`' credit: its one
    # binding is a direct child statement of the body and the name is mentioned
    # nowhere outside it), so the same arming and the same three exit points
    # apply. Computed from the same body, so the two sets cannot disagree.
    gen._scoped_free_candidates = (gen._scoped_free_candidates
                                   | _compute_scoped_closure_candidates(fn, gen._owned_free_candidates))


def reset_no_candidates(gen) -> None:
    """Call once, before lowering any OTHER function-like body that shares
    `gen.gen_stmt`'s statement dispatcher (and therefore
    `_gen_stmt_ReturnStmt`/`emit_return_frees`) but that this feature
    doesn't (yet) analyze — currently `gimple_gen_funcs.py`'s
    `_gen_struct_method` and `_gen_toplevel`. Without this, `emit_return_
    frees` runs against WHATEVER `_owned_free_candidates`/`_owned_free_
    pushed` a PREVIOUSLY processed ordinary function (the one and only
    thing that calls `begin_function`) left behind — a real, confirmed
    bug found 2026-09-15 investigating Phase 6: a struct method sharing a
    local's bare NAME with an unrelated free function's genuine Phase-3
    candidate got that stale candidate's `mojo_*_free` silently spliced
    into ITS OWN return, freeing a value that had just escaped via
    `self.field = local` two lines earlier — confirmed via `lldb`/
    `MallocScribble` as a real, reproducible use-after-free (segfault),
    not just a theoretical risk. `reset_no_candidates` is intentionally
    the ONLY option here (as opposed to running the real analysis on
    method/toplevel bodies) — Phase 3 doesn't support methods yet (see
    `_is_free_eligible_function`'s docstring), so the safe, correct
    behavior for them today is exactly zero candidates, not stale ones."""
    gen._owned_free_candidates = set()
    gen._owned_free_pushed = set()
    gen._owned_stack_allocated = set()
    gen._int_keyed_dicts = set()
    _reset_scope_state(gen)


def emit_return_frees(gen) -> None:
    """Call at the top of gimple_gen_stmts.py's `_gen_stmt_ReturnStmt`,
    before anything else in that function runs (see that call site for
    why it's safe to run unconditionally before evaluating the returned
    expression)."""
    # Direct attribute access — see `maybe_push_owned_local`'s note.
    if gen._owned_free_candidates or gen._scope_live:
        _emit_owned_local_frees(gen)


def emit_fallthrough_frees(gen, fn) -> None:
    """Call once in `gen_func`, immediately after lowering every statement
    in `fn`'s body, before anything else (the `main`-specific implicit-
    return patch, assembling the final `lines` list) runs. A no-op unless
    `fn` both has eligible candidates AND can actually fall off its own
    end (see `_function_has_reachable_fallthrough` — a function whose
    every path already returns has nothing left for this to do; whatever
    follows in `gen.body_lines` would be unreachable C)."""
    # Split into two plain `if`s rather than one `and` expression —
    # self-hosted codegen for a boolean `and` combining a SET truthiness
    # check (LHS) with a plain int/bool result (RHS,
    # `_function_has_reachable_fallthrough`) was found to miscompile:
    # `mojo_set_len` ended up called with the RHS's own 0/1 result
    # instead of the LHS set pointer (confirmed via lldb: `mojo_set_len`
    # crashed with x0=1, i.e. it was handed the boolean `True`, not a
    # real MojoSet*). Two nested `if`s side-step whatever code path
    # combines mixed-type `and` operands.
    # Direct attribute access — see `maybe_push_owned_local`'s note.
    if not gen._owned_free_candidates:
        return
    if not _function_has_reachable_fallthrough(fn):
        return
    _emit_owned_local_frees(gen)
