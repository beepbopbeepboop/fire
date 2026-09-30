#!/usr/bin/env python3
"""Tests for tools/md2html.py.

The failure this file exists for is not a crash. A converter that drops a
table row, or replaces a wrapped list item with its trailing clause, produces
a page that renders perfectly and is quietly missing content -- which is
exactly the failure mode a hand-written sibling HTML file has, and the reason
the HTML is generated here in the first place. So these assert on CONTENT
survival, not on "it returned a string".
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'tools'))

import md2html as M  # noqa: E402

PLAN = os.path.join(HERE, 'doc', 'GPU_OFFLOAD_PLAN.md')
PLAN_HTML = os.path.join(HERE, 'doc', 'GPU_OFFLOAD_PLAN.html')

VOID = {'meta', 'br', 'hr', 'img', 'link', 'input'}


class _Balance(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack:
            self.errors.append(f'stray </{tag}>')
        elif self.stack[-1] != tag:
            self.errors.append(f'</{tag}> closes <{self.stack[-1]}>')
        else:
            self.stack.pop()


def visible_text(html: str) -> str:
    """`html` reduced to the text a reader actually sees.

    Block-level tags become newlines and INLINE tags become nothing -- the
    distinction matters: replacing `<code>x</code>` with a space turns
    "a `float *` has none" into "a float *  has none" with a stray space, and
    every content assertion below then fails for a reason that has nothing to
    do with the converter.
    """
    body = re.sub(r'</?(?:p|div|h[1-6]|li|tr|td|th|pre|table|thead|'
                  r'tbody|ul|ol|br)\b[^>]*>', '\n', html.split('</style>', 1)[-1])
    return re.sub(r'\s+', ' ', _unescape(re.sub(r'<[^>]+>', '', body)))


def _unescape(s: str) -> str:
    import html as _h
    return _h.unescape(s)


class TestStructure(unittest.TestCase):
    def test_generated_page_has_balanced_tags(self):
        out = M.convert('# T\n\ntext\n', 't.md')
        p = _Balance()
        p.feed(out)
        self.assertEqual(p.errors, [], f'mismatched tags: {p.errors[:4]}')
        self.assertEqual(p.stack, [], f'unclosed tags: {p.stack[:4]}')

    def test_markup_in_the_source_is_escaped_not_interpreted(self):
        out = M.convert('a < b & c > d `x < y`\n', 't.md')
        self.assertIn('&lt;', out)
        self.assertIn('&amp;', out)
        self.assertNotIn('<code>x < y</code>', out)   # the raw < must not escape

    def test_code_spans_win_over_emphasis(self):
        out = M.convert('`*a*` and *b*\n', 't.md')
        self.assertIn('<code>*a*</code>', out)
        self.assertIn('<em>b</em>', out)


class TestContentSurvival(unittest.TestCase):
    """Every construct rendered keeps its own words.

    Each case is a bug that shipped once and looked fine in a browser.
    """

    def test_table_keeps_its_FIRST_body_row(self):
        """A dropped table row is invisible in the output.

        The caller collects `[header, separator, *body]` and
        `_render_table` slices `rows[2:]`. When the caller left the separator
        OUT of `rows`, that slice silently ate the first body row: the
        "build wiring" row of the GPU offload plan's offline-vs-runtime
        comparison table simply did not exist in the HTML, and no assertion
        anywhere noticed.
        """
        src = ('| | A | B |\n'
               '|---|---|---|\n'
               '| first | one | two |\n'
               '| second | three | four |\n')
        out = M.convert(src, 't.md')
        self.assertIn('<td>first</td>', out)
        self.assertIn('<td>one</td>', out)
        self.assertIn('<td>second</td>', out)
        self.assertEqual(out.count('<tr>'), 3, 'header + 2 body rows')

    def test_wrapped_list_item_keeps_its_own_leading_text(self):
        """Lazy continuation must APPEND, not replace.

        The item's text is emitted first and the indented continuation lines
        are joined onto it. An earlier renderer rebuilt the `<li>` from the
        continuation alone, so every wrapped item in the document rendered as
        its trailing clause and nothing else.
        """
        src = ('- **Increment 2 — the hand-written speciality code.** With a\n'
               '  device emitter that exists, make the primitives lower:\n'
               '  `llvm.air.*` next.\n')
        out = M.convert(src, 't.md')
        self.assertIn('Increment 2', out)
        self.assertIn('the hand-written speciality code', out)
        self.assertIn('device emitter that exists', out)
        self.assertIn('llvm.air.', out)
        self.assertEqual(out.count('<li>'), 1, 'a wrapped item is still ONE item')

    def test_fenced_code_is_literal(self):
        src = '```python\nx = a * b  # <not a tag>\nif x < 1: pass\n```\n'
        out = M.convert(src, 't.md')
        self.assertIn('&lt;not a tag&gt;', out)
        self.assertIn('&lt; 1', out)
        self.assertNotIn('<not a tag>', out)
        self.assertEqual(out.count('<pre>'), 1)

    def test_a_code_span_may_cross_a_source_line_break(self):
        """Real prose does this, and it must not split the code span.

        The GPU offload plan writes `` `@gpu def` `` / newline / `` `matvec(...)`
        `` in one code span. A regex that stops at a newline renders the two
        halves as text and silently drops the code formatting.

        The line break becomes a SPACE, not a newline: the paragraph is
        joined before inline rendering, and carrying the break into a
        `<code>` would make the code's own line structure depend on where the
        source happened to wrap.
        """
        src = 'text `@gpu def\nmatvec(...)` more\n'
        out = M.convert(src, 't.md')
        self.assertIn('<code>@gpu def matvec(...)</code>', out)
        self.assertIn('more', out)


class TestRealDocument(unittest.TestCase):
    """Checks against the document this was written for.

    A fixture-only test proves the renderer works on the constructs someone
    thought of. These run the real plan through the real renderer, which is
    the only thing that catches a construct the fixture forgot.
    """

    def setUp(self):
        if not os.path.exists(PLAN):
            self.skipTest('plan markdown not present')
        with open(PLAN, encoding='utf-8') as f:
            self.md = f.read()
        with open(PLAN_HTML, encoding='utf-8') as f:
            self.html = f.read()

    def test_every_source_line_survives_into_the_html(self):
        text = visible_text(self.html)
        missing = []
        for raw in self.md.split('\n'):
            s = raw.strip()
            if not s or s.startswith(('```', '|---', '---')):
                continue
            if s.startswith('|'):
                probes = [c for c in (c.strip() for c in s.strip('|').split('|'))
                          if len(c) > 8]
            else:
                probes = [re.sub(r'^\s*(?:[-*]|\d+\.)\s+', '',
                                 re.sub(r'^#{1,6}\s+', '', s))]
            for probe in probes:
                # A code span that crosses a line break cannot be probed
                # per-line -- the renderer correctly joins it, so the source
                # fragment does not appear anywhere. Skip those.
                if probe.count('`') % 2:
                    continue
                q = _plain(probe)
                if len(q) < 8:
                    continue
                if q[:50] not in text:
                    missing.append(q[:60])
        self.assertEqual(missing, [], f'content lost from the HTML: {missing}')

    def test_committed_html_is_up_to_date_with_the_markdown(self):
        self.assertEqual(
            M.convert(self.md, os.path.basename(PLAN)), self.html,
            'doc/GPU_OFFLOAD_PLAN.html is stale -- regenerate with '
            '`python3 tools/md2html.py doc/GPU_OFFLOAD_PLAN.md`')

    def test_check_mode_reports_a_stale_file(self):
        tmp = os.path.join(HERE, 'build', '_md2html_stale.md')
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write('# T\n\nbody\n')
        devnull = open(os.devnull, 'w')
        real_err, sys.stderr = sys.stderr, devnull
        try:
            rc = M.main([tmp, '--check'])
            self.assertEqual(rc, 1, '--check must fail for a missing .html')
            M.main([tmp])
            self.assertEqual(M.main([tmp, '--check']), 0,
                             '--check must pass once regenerated')
        finally:
            sys.stderr = real_err
            devnull.close()
            for p in (tmp, tmp[:-3] + '.html'):
                if os.path.exists(p):
                    os.unlink(p)


def _plain(s: str) -> str:
    """The visible text of a markdown fragment, mirroring `M._inline`."""
    spans: list[str] = []

    def stash(m):
        spans.append(m.group(1))
        return f'\x00{len(spans) - 1}\x00'

    s = re.sub(r'`([^`]+)`', stash, s)
    s = s.replace('**', '').replace('*', '')
    for i, c in enumerate(spans):
        s = s.replace(f'\x00{i}\x00', c)
    return re.sub(r'\s+', ' ', s).strip()


if __name__ == '__main__':
    unittest.main()
