# Consolidated root-cause bug index (2026-07-16 Python-3.14.6 full tree scan)

> **2026-07-30 status:** ~60 COMPILE_FAIL bug reports removed after verification.
> All Lib/ modules that can produce `.ci` output now compile without GCC errors.
> The file counts in the table below are from the original scan — a full rescan
> has not been performed since the fixes below. Remaining bug reports are for
> modules that crash during `compile_to_gimple` itself (generator/async function
> infrastructure gap, not GCC compilation errors).

**2026-07-30 fixes applied (see commits 74e9502, 12e9ebf, f93602b, 759623d):**
- `TstringLiteral` missing from `_EXPR_DISPATCH` (BUG-002) — added dispatch + handler
- `for` with tuple target on `range()` (BUG-013) — falls through to `_gen_for_iter`
- Indirect call stub (BUG-027) — explicit `(int64_t)0` + `_debug_note` instead of silent `(int, 0)`
- `MultiAssignStmt` dropped at top level (BUG-008) — added to top-level collector
- `MultiAssignStmt` scan_nodes crash — `targets` vs `target` attribute
- `_Bool` non-trivial conversion — explicit `(_Bool)` cast for integer literals
- `finally` body not run on normal try path (BUG-024) — inline finally body before `else`/`after`
- `void *` member write (`_funcptr_X.attr = val`) — routed through `_mojo_dispatch_setattr`
- Missing `return` in `_lower_MemberExpr` else branch — `lower_expr` returned `None` for opaque struct member reads

**RESOLVED (verified full compile):** abc, opcode, token, selectors, reprlib, cmd, colorsys, hashlib, hmac, io, numbers, operator, shlex, textwrap, wave, random, codeop, copy, copyreg, csv, curses/textpad, doctest, filecmp, fileinput, fnmatch, fractions, functools (Lib), getpass, gzip, lzma, netrc, ntpath, optparse, pickle, plistlib, posixpath, pty, queue, quopri, rlcompleter, sched, signal, smtplib, socket, socketserver, sre_compile, sre_constants, sre_parse, stat, string/templatelib, sysconfig, threading, timeit, trace, tracemalloc, warnings, webbrowser

**2026-07-25 update:** All PARSE_FAIL categories fully resolved. Only COMPILE_FAIL and TIMEOUT remain.

| Category | Root cause | Files affected (2026-07-16 scan) | Report |
|---|---|---|---|---|
| COMPILE_FAIL | CC ERROR: 'X' has no member named 'X' | 379 | consolidated/COMPILE_FAIL_cc_error_x_has_no_member_named_x.md |
| COMPILE_FAIL | CC ERROR: ld returned N exit status | 340 | consolidated/COMPILE_FAIL_cc_error_ld_returned_n_exit_status.md |
| COMPILE_FAIL | CC ERROR: expected 'X' before 'X' | 85 | consolidated/COMPILE_FAIL_cc_error_expected_x_before_x.md |
| COMPILE_FAIL | CC ERROR: invalid types for 'X' | 73 | consolidated/COMPILE_FAIL_cc_error_invalid_types_for_x.md |
| COMPILE_FAIL | CC ERROR: request for member 'X' in something not a structure or union | 59 | consolidated/COMPILE_FAIL_cc_error_request_for_member_x_in_something_not_a_structure_o.md |
| COMPILE_FAIL | CC ERROR: non-trivial conversion in 'X' | 52 | consolidated/COMPILE_FAIL_cc_error_non_trivial_conversion_in_x.md |
| COMPILE_FAIL | CC ERROR: expected 'X' before 'X' token | 43 | consolidated/COMPILE_FAIL_cc_error_expected_x_before_x_token.md |
| COMPILE_FAIL | CC ERROR: invalid operands to binary % (have 'X' and 'X') | 40 | consolidated/COMPILE_FAIL_cc_error_invalid_operands_to_binary_have_x_and_x.md |
| COMPILE_FAIL | CC ERROR: expected identifier or 'X' before 'X' | 37 | consolidated/COMPILE_FAIL_cc_error_expected_identifier_or_x_before_x.md |
| COMPILE_FAIL | CC ERROR: invalid conversion in gimple call | 29 | consolidated/COMPILE_FAIL_cc_error_invalid_conversion_in_gimple_call.md |
| TIMEOUT | TIMEOUT (build exceeded 90s) — **ALL RESOLVED** | 0 | consolidated/TIMEOUT_timeout_build_exceeded_90s.md |
| COMPILE_FAIL | CC ERROR: invalid operands to binary % (have 'X' and 'X' {aka 'X'}) | 20 | consolidated/COMPILE_FAIL_cc_error_invalid_operands_to_binary_have_x_and_x_aka_x.md |
| COMPILE_FAIL | CC ERROR: variable or field 'X' declared void | 18 | consolidated/COMPILE_FAIL_cc_error_variable_or_field_x_declared_void.md |
| COMPILE_FAIL | CC ERROR: 'X' has no member named 'X'; did you mean 'X'? | 17 | consolidated/COMPILE_FAIL_cc_error_x_has_no_member_named_x_did_you_mean_x.md |
| COMPILE_FAIL | CC ERROR: implicit declaration of function 'X' [-Wimplicit-function-declaration] | 17 | consolidated/COMPILE_FAIL_cc_error_implicit_declaration_of_function_x_wimplicit_functi.md |
| COMPILE_FAIL | CC ERROR: conflicting types for 'X'; have 'X' | 17 | consolidated/COMPILE_FAIL_cc_error_conflicting_types_for_x_have_x.md |
| COMPILE_FAIL | CC ERROR: conflicting types for 'X'; have 'X' {aka 'X'} | 15 | consolidated/COMPILE_FAIL_cc_error_conflicting_types_for_x_have_x_aka_x.md |
| COMPILE_FAIL | CC ERROR: passing argument N of 'X' makes integer from pointer without a cast [- | 12 | consolidated/COMPILE_FAIL_cc_error_passing_argument_n_of_x_makes_integer_from_pointer_.md |
| COMPILE_FAIL | CC ERROR: passing argument N of 'X' makes pointer from integer without a cast [- | 12 | consolidated/COMPILE_FAIL_cc_error_passing_argument_n_of_x_makes_pointer_from_integer_.md |
| COMPILE_FAIL | CC ERROR: too many arguments to function 'X'; expected N, have N | 10 | consolidated/COMPILE_FAIL_cc_error_too_many_arguments_to_function_x_expected_n_have_n.md |
| COMPILE_FAIL | CC ERROR: assignment to 'X' {aka 'X'} from 'X' makes integer from pointer withou | 10 | consolidated/COMPILE_FAIL_cc_error_assignment_to_x_aka_x_from_x_makes_integer_from_poi.md |
| COMPILE_FAIL | CC ERROR: 'X' undeclared (first use in this function) | 10 | consolidated/COMPILE_FAIL_cc_error_x_undeclared_first_use_in_this_function.md |
| COMPILE_FAIL | CC ERROR: in buildN, at tree.cc:N | 8 | consolidated/COMPILE_FAIL_cc_error_in_buildn_at_tree_cc_n.md |
| COMPILE_FAIL | CC ERROR: returning 'X' from a function with return type 'X' makes integer from  | 8 | consolidated/COMPILE_FAIL_cc_error_returning_x_from_a_function_with_return_type_x_make.md |
| COMPILE_FAIL | CC ERROR: too few arguments to function 'X'; expected N, have N | 7 | consolidated/COMPILE_FAIL_cc_error_too_few_arguments_to_function_x_expected_n_have_n.md |
| COMPILE_FAIL | CC ERROR:  | 7 | consolidated/COMPILE_FAIL_cc_error.md |
| COMPILE_FAIL | CC ERROR: expected identifier or 'X' before numeric constant | 7 | consolidated/COMPILE_FAIL_cc_error_expected_identifier_or_x_before_numeric_constant.md |
| COMPILE_FAIL | CC ERROR: implicit declaration of function 'X'; did you mean 'X'? [-Wimplicit-fu | 7 | consolidated/COMPILE_FAIL_cc_error_implicit_declaration_of_function_x_did_you_mean_x_w.md |
| COMPILE_FAIL | CC ERROR: invalid types in conversion to integer | 6 | consolidated/COMPILE_FAIL_cc_error_invalid_types_in_conversion_to_integer.md |
| COMPILE_FAIL | CC ERROR: 'X' undeclared (first use in this function); did you mean 'X'? | 5 | consolidated/COMPILE_FAIL_cc_error_x_undeclared_first_use_in_this_function_did_you_mea.md |
| COMPILE_FAIL | CC ERROR: lvalue required as left operand of assignment | 5 | consolidated/COMPILE_FAIL_cc_error_lvalue_required_as_left_operand_of_assignment.md |
| COMPILE_FAIL | CC ERROR: expected expression before 'X' | 5 | consolidated/COMPILE_FAIL_cc_error_expected_expression_before_x.md |
| COMPILE_FAIL | CC ERROR: 'X' undeclared here (not in a function); did you mean 'X'? | 4 | consolidated/COMPILE_FAIL_cc_error_x_undeclared_here_not_in_a_function_did_you_mean_x.md |
| COMPILE_FAIL | CC ERROR: non-register as LHS of unary operation | 4 | consolidated/COMPILE_FAIL_cc_error_non_register_as_lhs_of_unary_operation.md |
| COMPILE_FAIL | CC ERROR: expected expression before 'X' token | 4 | consolidated/COMPILE_FAIL_cc_error_expected_expression_before_x_token.md |
| COMPILE_FAIL | CC ERROR: invalid conversion in return statement | 2 | consolidated/COMPILE_FAIL_cc_error_invalid_conversion_in_return_statement.md |
| COMPILE_FAIL | CC ERROR: assignment to 'X' from 'X' {aka 'X'} makes pointer from integer withou | 2 | consolidated/COMPILE_FAIL_cc_error_assignment_to_x_from_x_aka_x_makes_pointer_from_int.md |
| COMPILE_FAIL | CC ERROR: cannot convert to a pointer type | 2 | consolidated/COMPILE_FAIL_cc_error_cannot_convert_to_a_pointer_type.md |
| COMPILE_FAIL | CC ERROR: expected declaration specifiers or 'X' before 'X' token | 2 | consolidated/COMPILE_FAIL_cc_error_expected_declaration_specifiers_or_x_before_x_token.md |
| COMPILE_FAIL | CC ERROR: invalid use of void expression | 2 | consolidated/COMPILE_FAIL_cc_error_invalid_use_of_void_expression.md |
| COMPILE_FAIL | CC ERROR: 'X' undeclared here (not in a function) | 2 | consolidated/COMPILE_FAIL_cc_error_x_undeclared_here_not_in_a_function.md |
| COMPILE_FAIL | CC ERROR: expected declaration specifiers or 'X' before string constant | 2 | consolidated/COMPILE_FAIL_cc_error_expected_declaration_specifiers_or_x_before_string_.md |
| COMPILE_FAIL | CC ERROR: invalid call to non-function before 'X' token | 2 | consolidated/COMPILE_FAIL_cc_error_invalid_call_to_non_function_before_x_token.md |
| COMPILE_FAIL | CC ERROR: invalid operands to binary * (have 'X' and 'X') | 1 | consolidated/COMPILE_FAIL_cc_error_invalid_operands_to_binary_have_x_and_x_2.md |
| COMPILE_FAIL | CC ERROR: redefinition of 'X' | 1 | consolidated/COMPILE_FAIL_cc_error_redefinition_of_x.md |
| COMPILE_FAIL | CC ERROR: expected 'X', 'X' or 'X' before 'X' | 1 | consolidated/COMPILE_FAIL_cc_error_expected_x_x_or_x_before_x.md |
| COMPILE_FAIL | CC ERROR: field 'X' declared as a function | 1 | consolidated/COMPILE_FAIL_cc_error_field_x_declared_as_a_function.md |
| COMPILE_FAIL | CC ERROR: invalid type argument of unary 'X' (have 'X' {aka 'X'}) | 1 | consolidated/COMPILE_FAIL_cc_error_invalid_type_argument_of_unary_x_have_x_aka_x.md |
| COMPILE_FAIL | CC ERROR: unknown type name 'X' | 1 | consolidated/COMPILE_FAIL_cc_error_unknown_type_name_x.md |
| COMPILE_FAIL | CC ERROR: 'X' redeclared as different kind of symbol | 1 | consolidated/COMPILE_FAIL_cc_error_x_redeclared_as_different_kind_of_symbol.md |
| COMPILE_FAIL | CC ERROR: invalid operands to binary / (have 'X' and 'X' {aka 'X'}) | 1 | consolidated/COMPILE_FAIL_cc_error_invalid_operands_to_binary_have_x_and_x_aka_x_2.md |
| COMPILE_FAIL | CC ERROR: invalid operands to binary + (have 'X' and 'X') | 1 | consolidated/COMPILE_FAIL_cc_error_invalid_operands_to_binary_have_x_and_x_3.md |
| COMPILE_FAIL | CC ERROR: too many decimal points in number | 1 | consolidated/COMPILE_FAIL_cc_error_too_many_decimal_points_in_number.md |
| COMPILE_FAIL | CC ERROR: type mismatch in binary expression | 1 | consolidated/COMPILE_FAIL_cc_error_type_mismatch_in_binary_expression.md |
| COMPILE_FAIL | CC ERROR: assignment to 'X' from incompatible pointer type 'X' [-Wincompatible-p | 1 | consolidated/COMPILE_FAIL_cc_error_assignment_to_x_from_incompatible_pointer_type_x_wi.md |
| COMPILE_FAIL | CC ERROR: duplicate member 'X' | 1 | consolidated/COMPILE_FAIL_cc_error_duplicate_member_x.md |
| COMPILE_FAIL | CC ERROR: missing terminating " character | 1 | consolidated/COMPILE_FAIL_cc_error_missing_terminating_character.md |
| COMPILE_FAIL | CC ERROR: expected identifier before 'X' token | 1 | consolidated/COMPILE_FAIL_cc_error_expected_identifier_before_x_token.md |
| COMPILE_FAIL | CC ERROR: pipe seems to be closed, but still returns data') | 1 | consolidated/COMPILE_FAIL_cc_error_pipe_seems_to_be_closed_but_still_returns_data.md |
| COMPILE_FAIL | Error building: invalid literal for int() with base N: 'X' | 1 | consolidated/COMPILE_FAIL_error_building_invalid_literal_for_int_with_base_n_x.md |
| COMPILE_FAIL | CC ERROR: %s" % (e[N], error)) | 1 | consolidated/COMPILE_FAIL_cc_error_s_e_n_error.md |
| COMPILE_FAIL | Error building: 'X' codec can't decode byte NxfN in position N: invalid start by | 1 | consolidated/COMPILE_FAIL_error_building_x_codec_can_t_decode_byte_nxfn_in_position_n_.md |
| COMPILE_FAIL | CC ERROR: passing argument N of 'X' from incompatible pointer type [-Wincompatib | 1 | consolidated/COMPILE_FAIL_cc_error_passing_argument_n_of_x_from_incompatible_pointer_t.md |
| COMPILE_FAIL | CC ERROR: assignment to 'X' from 'X' makes pointer from integer without a cast [ | 1 | consolidated/COMPILE_FAIL_cc_error_assignment_to_x_from_x_makes_pointer_from_integer_w.md |
| COMPILE_FAIL | CC ERROR: invalid operands to binary % (have 'X' {aka 'X'} and 'X') | 1 | consolidated/COMPILE_FAIL_cc_error_invalid_operands_to_binary_have_x_aka_x_and_x.md |
