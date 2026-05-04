"""Entry point: read .md spec files, print AST dump, then print generated compiler."""
import os
from fe_reader import FormalEnglishReader
from compiler_gen import dump_spec, PythonCompilerGen

HERE = os.path.dirname(os.path.abspath(__file__))

MD_FILES = [
    'mojo-literals.md',
    'mojo-operators.md',
    'mojo-compound-statements.md',
    'mojo-function-declarations.md',
    'mojo-simple-statements.md',
    'mojo-expressions.md',
    'mojo-keywords.md',
    'mojo-manual-language-basics.md',
    'mojo-manual-values.md',
    'mojo-manual-metaprogramming.md',
    'mojo-manual-pointers.md',
    'mojo-manual-python.md',
    'mojo-manual-gpu.md',
    'mojo-tools-and-faq.md',
]

def main():
    reader = FormalEnglishReader()
    for f in MD_FILES:
        reader.read(os.path.join(HERE, f))

    spec = reader.spec

    print('=' * 60)
    print('LANGUAGE SPEC AST')
    print('=' * 60)
    print(dump_spec(spec))

    print()
    print('=' * 60)
    print('GENERATED PYTHON COMPILER')
    print('=' * 60)
    code = PythonCompilerGen(spec).generate()
    print(code)

    out = os.path.join(HERE, 'mojo_compiler.py')
    with open(out, 'w') as fh:
        fh.write(code)
    print(f'\n(also written to {out})')

if __name__ == '__main__':
    main()
