# `compile_linked` reads the link results (dylibs, objects, the needs-C++ box) off the generator
# AFTER `_run_pipeline` returns. The end-of-compile cleanup that frees per-compile state used to
# clear every `_`-prefixed container on that generator, the result containers included, so every
# link-mode compile raised `IndexError: list index out of range` on `_link_needs_cxx_box[0]`;
# `driver.compile_program` then failed and `fire.py build` fell back to its slow inline pipeline
# (the "build in link mode did not finish" symptom). The cleanup must still free the rest.
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gimple_codegen

SRC = '''def main():
    print(1 + 2)
'''


def test_compile_linked_returns_its_five_results():
    code, dylibs, objects, cpp, needs_cxx = gimple_codegen.compile_linked(SRC, filename='cl_probe.mojo')
    assert 'main' in code
    assert isinstance(dylibs, list) and isinstance(objects, list)
    assert needs_cxx in (True, False)


def test_other_per_compile_state_is_still_cleared():
    code, gen = gimple_codegen._run_pipeline(SRC, filename='cl_probe.mojo', link_mode=True)
    assert gen._link_needs_cxx_box and gen._link_needs_cxx_box[0] in (True, False)
    for attr in ('_all_transitive_stmts_ordered', '_module_stmts'):
        assert not getattr(gen, attr, None), f'{attr} survived the end-of-compile cleanup'


if __name__ == '__main__':
    test_compile_linked_returns_its_five_results()
    test_other_per_compile_state_is_still_cleared()
    print('PASS')
