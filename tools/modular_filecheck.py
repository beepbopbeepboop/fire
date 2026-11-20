#!/usr/bin/env python3
"""Run modular test files (by name, found under the modular checkout's test/)
through `fire.py build` and their own FileCheck lines, one verdict per file:

    python3 tools/modular_filecheck.py tuple_first_of_error.mojo where_message.mojo

Only RUN lines of the shape `[not] <tool> [flags] %s [2>&1] | FileCheck
[--check-prefix=X]` are supported (the tool being %mojo, %mojo-build,
%parse-mojo-isolated, mojo build/run or kgen); split-input-file and
-verify-diagnostics tests are reported UNSUPPORTED. A test whose expected output
is an MLIR dump rather than a diagnostic cannot pass by construction."""
import os, re, subprocess, sys, shutil, tempfile, glob
# The tree the tests are read from must be the one whose stdlib this repo compiles
# against (`new-modular/Mojo`): the older `modular/mojo/test` tree carries tests for
# language rules the current stdlib no longer has (Tuple.__contains__'s `where`,
# EnumLike's `_enum_is_exhaustive`), which passed their FileCheck lines and then
# rejected valid stdlib code. Override with MODULAR_TEST_ROOT.
ROOT=os.environ.get('MODULAR_TEST_ROOT', '/Users/mrs/net/chatgpt/claude/new-modular/Mojo/test')
FIRE=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'fire.py')
FC='/opt/homebrew/opt/llvm/bin/FileCheck'
PARSE_ONLY = '''
import sys
sys.path.insert(0, sys.argv[1])
from gimple_codegen import compile_to_gimple
f = sys.argv[2]
try:
    compile_to_gimple(open(f).read(), do_imports=True, filename=f)
except Exception as e:
    print('Error building: %s' % e, file=sys.stderr)
    sys.exit(1)
'''
TOOL=r'(?:%mojo-build|%mojo|%parse-mojo-isolated|mojo build|mojo run|kgen -elaborate|kgen)'
for n in sys.argv[1:]:
    hits=glob.glob(ROOT+'/**/'+n, recursive=True)
    if not hits: print(f"{n}: NOT FOUND"); continue
    f=hits[0]; txt=open(f).read()
    runs=[l.split('RUN:',1)[1].strip() for l in txt.splitlines() if 'RUN:' in l and l.lstrip().startswith(('#','//'))]
    cmd=[r for r in runs if 'FileCheck' in r]
    if not cmd: print(f"{n}: no FileCheck RUN ({runs[:1]})"); continue
    cmd=cmd[-1]
    if 'split-input-file' in cmd or '-verify-diagnostics' in cmd: print(f"{n}: UNSUPPORTED(split/verify)"); continue
    m=re.search(r'(?:not )?'+TOOL+r'\s*(.*?)%s(.*?)\|\s*FileCheck\s*(.*)$',cmd)
    if not m: print(f"{n}: UNSUPPORTED RUN: {cmd[:90]}"); continue
    flags=[a for a in (m.group(1)+m.group(2)).split() if a=='--Werror']
    if 'Werror' in cmd or 'warnings-as-errors' in cmd: flags=['--Werror']
    fcargs=[a for a in m.group(3).split() if a.startswith('--check-prefix')]
    d=tempfile.mkdtemp(); t=os.path.join(d,os.path.basename(n)); shutil.copy(f,t)
    inp=os.path.join(os.path.dirname(f),'inputs')
    # Only a test that names `inputs` gets them: copying a directory with dozens of
    # packages next to a test that needs none made every build crawl past its 60 s
    # budget (a TIMEOUT that read as "the compiler accepted the file").
    if os.path.isdir(inp) and 'inputs' in txt:
        for e in os.listdir(inp):
            s=os.path.join(inp,e)
            (shutil.copytree if os.path.isdir(s) else shutil.copy)(s,os.path.join(d,e))
    try:
        if '%parse-mojo-isolated' in cmd:
            # A parse test has no `main` and expects only diagnostics: `fire.py build` would
            # run on into the link stage and time out, which reads as "accepted". Compile
            # in-process and print what a failed build prints.
            argv=[sys.executable,'-c',PARSE_ONLY,os.path.dirname(FIRE),t]
        else:
            argv=[sys.executable,FIRE]+flags+['build',t,'-o',os.path.join(d,'out')]
        p=subprocess.run(argv,capture_output=True,text=True,timeout=60,cwd=d)
        out=p.stdout+p.stderr
    except subprocess.TimeoutExpired:
        print(f"{n}: TIMEOUT"); continue
    fc=subprocess.run([FC,f]+fcargs,input=out,capture_output=True,text=True)
    first=[l for l in fc.stderr.splitlines() if 'error: CHECK' in l][:1]
    print(f"{n}: {'PASS' if fc.returncode==0 else 'FAIL'} rc={p.returncode} {first[0][-110:] if first else ''}")
