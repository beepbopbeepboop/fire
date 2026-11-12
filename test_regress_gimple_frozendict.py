# Regression: Python 3.15 frozendict builtin (compiled/GIMPLE path).
import sys
sys.path.insert(0, '.')
import test_gimple_runner as tgr

CASES = [
    ('gimple_frozendict_basic', '''\
def main():
    fd = frozendict({'a': 1, 'b': 2})
    print(fd['a'])
    print(len(fd))
    print('a' in fd)
    print('z' in fd)
    print(fd.get('a'))
    print(fd.get('z', 9))
    print(fd == {'a': 1, 'b': 2})
    print({'a': 1, 'b': 2} == fd)
    print(list(fd))
main()
'''),
    ('gimple_frozendict_constructors', '''\
def main():
    print(frozendict())
    print(frozendict({'a': 1}))
    print(frozendict(a=1, b=2))
    print(frozendict([('a', 1), ('b', 2)]))
    print(frozendict(frozendict({'a': 1})))
main()
'''),
    ('gimple_frozendict_isinstance', '''\
def main():
    fd = frozendict({'a': 1})
    d = {'a': 1}
    print(isinstance(fd, frozendict))
    print(isinstance(fd, dict))
    print(isinstance(d, frozendict))
    print(isinstance(d, dict))
    print(isinstance(fd, (dict, frozendict)))
    print(isinstance(d, (list, frozendict)))
main()
'''),
    ('gimple_frozendict_or_method', '''\
def main():
    fd = frozendict({'a': 1})
    print(fd.__or__({'b': 2}))
    print(fd | {'b': 2})
main()
'''),
    ('gimple_frozendict_fromkeys', '''\
def main():
    print(frozendict.fromkeys(['a', 'b'], 0))
    print(frozendict.fromkeys(['x']))
    print(frozendict.fromkeys([1, 2], 7))
    d = dict.fromkeys([1, 2], 'v')
    print(d[1], d[2])
    fd = frozendict.fromkeys([b'a', b'b'], 1)
    print(fd[b'a'], fd[b'b'])
    print(b'b' in fd)
    print(len(fd))
    db = dict.fromkeys([b'x'], 7)
    print(db[b'x'])
main()
'''),
    ('gimple_frozendict_fromkeys_iterables', '''\
def main():
    print(frozendict.fromkeys(range(3), 'x'))
    print(frozendict.fromkeys((1, 2), 0))
    print(dict.fromkeys(range(3), 7))
    fd = frozendict({}).fromkeys([1, 2], 0)
    print(fd)
    print(isinstance(fd, frozendict))
    d = {}.fromkeys(['a'], 1)
    print(d)
    print(isinstance(d, dict))
main()
'''),
    ('gimple_frozendict_fromkeys_callable_value', '''\
def main():
    fk = frozendict.fromkeys
    print(fk([1, 2], 0))
    print(fk([None, 'a'], 5)[None])
main()
'''),
]

ERROR_CASES = [
    ('gimple_frozendict_del', '''\
def main():
    fd = frozendict({'a': 1})
    del fd['a']
main()
''', 'does not support item deletion'),
    ('gimple_frozendict_ior', '''\
def main():
    fd = frozendict({'a': 1})
    fd |= {'b': 2}
main()
''', "__ior__"),
    ('gimple_frozendict_popitem', '''\
def main():
    fd = frozendict({'a': 1})
    fd.popitem()
main()
''', "popitem"),
    ('gimple_frozendict_delitem_method', '''\
def main():
    fd = frozendict({'a': 1})
    fd.__delitem__('a')
main()
''', 'does not support item deletion'),
]

if __name__ == '__main__':
    for name, src in CASES:
        tgr.test_gimple_matches_cpython(name, src)
    for name, src, sub in ERROR_CASES:
        tgr.test_gimple_runtime_error(name, src, sub)
    if tgr._FAIL or tgr._TIMEOUT:
        sys.exit(1)

