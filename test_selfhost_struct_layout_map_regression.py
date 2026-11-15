"""Regression pin: the self-host AST layout map must cover every field the
source class declares.

`mojo/backend_gimple/module_gen.py` hardcodes
`self.struct_field_types['<Node>'] = { ... }` for this compiler's own AST
nodes. A field declared on the source class but absent from that row is
dropped from the emitted C struct, so a read of it in the closure's generated
C names a member the struct does not have and gcc rejects the self-host
translation unit. That is the defect class the self-host closure bug's item 1
belongs to, and it recurred three times in one session:

    Parser._lazy_import_blockers   Parser._last_bracket_variadics
    Parser.errors                  ImportStmt.lazy
    FromImportStmt.lazy            FunctionDef.variadic_bracket_params
    StructDef.where_clause         StructDef.bracket_types
    StructDef.align_expr           StructDef.presence_fields

all reported by gcc as `'X' has no member named 'Y'` while building the
closure.

The readers are `tools/audit_selfhost_struct_fields.py`'s, so the tool and
this pin cannot disagree: the map comes from the source text (a field added
without a row is what we look for), and the class fields come from class-level
ANNOTATIONS rather than `@dataclass` decorators — `Parser` is a plain class
whose annotations are its fields, and a dataclass-only reader silently stops
watching the three `Parser` fields above. The second test pins that coverage
because without it the first test would keep passing after such a regression.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _audit():
    path = os.path.join(HERE, 'tools', 'audit_selfhost_struct_fields.py')
    spec = importlib.util.spec_from_file_location(
        'audit_selfhost_struct_fields', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _missing():
    audit = _audit()
    fields = audit.annotated_fields(os.path.join(HERE, 'fire_compiler.py'))
    layout = audit.struct_field_map(
        os.path.join(HERE, 'mojo', 'backend_gimple', 'module_gen.py'))
    return audit.missing_fields(fields, layout)


def test_the_check_reports_a_missing_field():
    # A guard whose reader silently returns nothing cannot fail. Keep the
    # control on the pure comparison so it costs nothing and cannot drift.
    audit = _audit()
    got = audit.missing_fields(
        {'Parser': ['_tok', '_lazy_import_blockers']},
        {'Parser': ['_tok']})
    assert got == {'Parser': ['_lazy_import_blockers']}, got


def test_the_reader_covers_plain_classes_not_just_dataclasses():
    audit = _audit()
    fields = audit.annotated_fields(os.path.join(HERE, 'fire_compiler.py'))
    assert 'Parser' in fields, (
        "the layout-map check no longer reads plain classes; Parser's own "
        "fields would go unwatched")
    for name in ('_lazy_import_blockers', '_last_bracket_variadics', 'errors'):
        assert name in fields['Parser'], (
            f"the layout-map check cannot see Parser.{name}")


def test_every_annotated_field_has_a_layout_row():
    missing = _missing()
    assert not missing, (
        "field(s) declared in fire_compiler.py but absent from "
        "mojo/backend_gimple/module_gen.py's hardcoded struct_field_types "
        "map — the emitted struct will have no such member and the self-host "
        "closure will not compile: "
        + '; '.join(f'{s}: {fs}' for s, fs in sorted(missing.items())))


if __name__ == "__main__":
    test_the_check_reports_a_missing_field()
    test_the_reader_covers_plain_classes_not_just_dataclasses()
    test_every_annotated_field_has_a_layout_row()
    print("PASS")
