"""`itcursor.cursor_for` hands the cursor record back through `_as_dict`.

In the compiled compiler `gen._list_iter_cursor.get(cname)` (no default, an
untyped value domain) is the boxed read, and the record reached `remaining` as a
box: `rec['full']` read the box's magic word as the dict header and
`mojo_dict_subscript_boxed` crashed (address 0x4d4a424f58311b01, "MJBOX1") on the
first `len(x)` the self-hosted compiler lowered. Behaviour check for the Python
reference plus a source pin that the record goes through `_as_dict`.
"""
import sys

import mojo.middle.itcursor as itc


class _Gen:
    def __init__(self):
        self._list_iter_cursor = {'it': {'kind': 'list', 'full': 'f', 'cursor': 'c'}}


def main() -> int:
    g = _Gen()
    rec = itc.cursor_for(g, 'it')
    if rec is not g._list_iter_cursor['it']:
        print('FAIL: cursor_for did not return the stored record')
        return 1
    if itc.cursor_for(g, 'missing') is not None:
        print('FAIL: cursor_for of an unknown name is not None')
        return 1
    src = open(itc.__file__).read()
    body = src[src.index('def cursor_for'):src.index('def slot_ctype')]
    if '_as_dict(_rec)' not in body:
        print('FAIL: the record is not viewed through _as_dict')
        return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
