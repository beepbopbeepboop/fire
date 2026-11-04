import os
import subprocess
import tempfile


def test_fstring_printf_transformed():
    src = '''def main() -> Int:
    x = 42
    printf("x=%d\\n", x)
    return 0
'''
    # Also test the f-string form
    src2 = '''def main() -> Int:
    x = 42
    printf(f"x={x}\\n")
    return 0
'''
    # Both should compile
    import subprocess, sys, os
    for s in [src, src2]:
        fd, path = tempfile.mkstemp(suffix='.mojo')
        os.close(fd)
        try:
            with open(path, 'w') as f:
                f.write(s)
            r = subprocess.run([sys.executable, 'fire.py', 'build', '--formal', 
                               '--no-prove', '-o', path + '.out', path],
                              cwd='/Users/mrs/net/chatgpt/claude/work-4588',
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=60)
            assert r.returncode == 0, (r.stdout, r.stderr)
            assert os.path.exists(path + '.out')
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass
            try:
                os.unlink(path + '.out')
            except Exception:
                pass


if __name__ == '__main__':
    test_fstring_printf_transformed()
    print("ok")
