#!/usr/bin/env python3
"""Wave-2 fn-extraction batch 2: delete stmts/loops/funcs methods from
GimpleGen and append delegating methods. Decorator-aware spans."""
import ast
import json
import subprocess

ALL = [
 ('gimple_gen_stmts.py', ['gen_stmt', '_gen_stmt_PassStmt', '_annotation_dict_val_type',
  '_gen_stmt_VarDecl', '_track_pointer_actual_type', '_assign_target',
  '_is_except_as_member_target', '_emit_dynattr_setattr_dispatch', '_gen_stmt_AssignStmt',
  '_gen_stmt_AugAssignStmt', '_gen_stmt_ReturnStmt', '_ensure_bool_cond', '_gen_stmt_IfStmt',
  '_gen_stmt_DelStmt', '_gen_stmt_MatchStmt', '_gen_stmt_WhileStmt', '_gen_stmt_MultiAssignStmt',
  '_gen_stmt_ForStmt', '_gen_stmt_BreakStmt', '_gen_stmt_ContinueStmt', '_gen_stmt_ExprStmt',
  '_gen_stmt_AssertStmt', '_gen_stmt_RaiseStmt', '_handler_exc_name', '_handler_exc_all_names',
  '_handler_bind_name', '_emit_except_handler', '_gen_stmt_TryStmt', '_gen_stmt_WithStmt']),
 ('gimple_gen_loops.py', ['_gen_for_range', '_get_actual_type', '_tuple_elem_value',
  '_emit_unsupported_iter', '_try_const_fold_int', '_try_const_fold_str',
  '_re_sub_repl_is_callback', '_lower_re_sub_callback', '_gen_for_regex_iter', '_gen_for_iter',
  '_gen_for_enumerate', '_gen_for_list', '_gen_for_str', '_gen_for_cstr', '_gen_for_dict',
  '_gen_for_set', '_gen_lifted_closure', '_emit_generator_tuple_unpack',
  '_gen_for_generator_iter', '_emit_generator_pending_exc_check', '_gen_for_struct_iter']),
 ('gimple_gen_funcs.py', ['_gen_stmt_FunctionDef', '_gen_stmt_ImportStmt',
  '_from_import_name_is_submodule', '_gen_stmt_FromImportStmt', '_gen_stmt_ComptimeIfStmt',
  '_gen_stmt_ComptimeVarStmt', '_gen_stmt_GlobalStmt', '_gen_stmt_ComptimeForStmt',
  '_signature_ctypes', '_note_vararg_trailing_param_types', '_fixed_param_ctypes',
  '_param_struct_name', '_param_ctype', 'overload_suffix_for', '_overload_suffix',
  '_note_own_func_home', '_push_import_scope', '_pop_import_scope',
  '_resolve_import_module_qualifier', '_collect_body_import_bindings', '_func_qualifier',
  '_locally_binds_name', '_func_mangleable', '_func_csym', 'gen_func', '_gen_toplevel',
  '_imported_field_ctype', '_materialize_imported_struct', '_resolve_sibling_param_ctype',
  '_register_imported_structs', '_find_imported_struct', '_resolve_test_relative_module',
  '_parsed_import', '_local_sibling_module_exports', '_abs_module', '_find_generic_source',
  '_register_imported_generics', '_register_imported_generic_structs',
  '_struct_method_overload_ids', '_struct_method_qualifier', '_struct_method_csym',
  '_struct_method_csym_static', '_gen_struct_method']),
]
ALIAS = {'gimple_gen_stmts.py': 'gst', 'gimple_gen_loops.py': 'glo',
         'gimple_gen_funcs.py': 'gfn'}

byname = {}
for mod, fam in ALL:
    r = subprocess.run(['python3', 'tools/extract_family.py', 'x'] + fam,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1200:]
    dj = json.loads(r.stdout.rpartition('__DELEGATES__')[2])
    for d in dj:
        d['alias'] = ALIAS[mod]
        byname[d['name']] = d

src = open('gimple_codegen.py').read()
L = src.split('\n')
tree = ast.parse(src)
ggen = next(n for n in tree.body
            if isinstance(n, ast.ClassDef) and n.name == 'GimpleGen')

spans, prev = [], 0
dec = 0
for node in ggen.body:
    if isinstance(node, ast.FunctionDef) and node.name in byname:
        s = node.lineno - 1
        if node.decorator_list:
            s = min(s, min(x.lineno - 1 for x in node.decorator_list))
            dec += 1
        e = node.end_lineno
        while s > prev and (L[s-1].startswith('#') or L[s-1].strip() == ''):
            s -= 1
        spans.append((s, e))
        prev = e
    else:
        prev = max(prev, getattr(node, 'end_lineno', 0))

print("deleting:", len(spans), "decorated:", dec)
assert len(spans) == len(byname), (len(spans), len(byname))
for s, e in sorted(spans, reverse=True):
    del L[s:e]

t2 = ast.parse('\n'.join(L))
gg2 = next(n for n in t2.body
           if isinstance(n, ast.ClassDef) and n.name == 'GimpleGen')
at = max(getattr(x, 'end_lineno', x.lineno) for x in gg2.body)
ins = []
for mod in reversed([m for m, _ in ALL]):
    ds = [d for d in byname.values() if d['alias'] == ALIAS[mod]]
    ins.append(f"\n    # ---- delegates: {mod} ----\n")
    for d in ds:
        sig = d['sig'].replace('(', '(self, ', 1).replace('(self, self,', '(self,')
        ins.append(f"    {sig}:\n        return {d['alias']}.{d['name']}({d['call']})\n")

L2 = '\n'.join(L).split('\n')
for i, t in enumerate(ins):
    L2.insert(at + i, t.rstrip('\n'))
out = '\n'.join(L2)
i = out.index('\nclass GimpleGen:')
imports = ('\nimport gimple_gen_stmts as gst\nimport gimple_gen_loops as glo\n'
           'import gimple_gen_funcs as gfn')
out = out[:i] + imports + out[i:]
ast.parse(out)
open('gimple_codegen.py', 'w').write(out)
print("done; codegen now", len(out.split('\n')), "lines")
