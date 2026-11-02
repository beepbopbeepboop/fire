import gimple_codegen

SRC = (
"class C:\n"
"    def m(self, x: int) -> int:\n"
"        return x\n"
"    def m(self, x: str) -> str:\n"
"        return x\n"
"\n"
"def main():\n"
"    c = C()\n"
"    f = c.m\n"
"    print(f(1))\n"
"\n"
"main()\n"
)


def test_overloaded_method_value_does_not_emit_bare_symbol():
    try:
        gimple_codegen.compile_to_gimple(SRC, do_imports=False, filename='ovl.mojo')
    except RuntimeError as e:
        assert 'cannot compile module' in str(e)
        return
    raise AssertionError('expected RuntimeError for overloaded method value')


if __name__ == '__main__':
    test_overloaded_method_value_does_not_emit_bare_symbol()
    print('OK')
