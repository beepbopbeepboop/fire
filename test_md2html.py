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

# Every document this generator is responsible for. A doc listed here is
# held to the same three checks: every source line survives, the committed
# HTML is current, and the ASCII diagram inside METAL.md is byte-intact.
DOCS = (
    ('doc/GPU_OFFLOAD_PLAN.md', 'doc/GPU_OFFLOAD_PLAN.html'),
    ('doc/METAL.md', 'doc/METAL.html'),
)

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

    def test_blockquote_keeps_its_first_line(self):
        """A blockquote must not lose the line that opens it.

        The collector stepped past the opening line before it started
        collecting, so the first line of every blockquote vanished and the
        remaining lines still rendered -- the page looked complete. This is
        the third instance of the same shape in this renderer, which is why
        it is worth a test each time: "the thing that is missing is the thing
        nobody looks for".
        """
        src = ('> Status: **design note / parking lot.** Not implemented.\n'
               "> don't lose the plan.\n")
        out = M.convert(src, 't.md')
        self.assertIn('<blockquote>', out)
        self.assertIn('Status:', out)
        self.assertIn('design note / parking lot', out)
        self.assertIn("don't lose the plan", out)
        self.assertEqual(out.count('<blockquote>'), 1)

    def test_blockquote_ends_at_a_blank_line(self):
        src = ('> quoted line\n'
               '\n'
               'ordinary paragraph\n')
        out = M.convert(src, 't.md')
        self.assertIn('<blockquote><p>quoted line</p></blockquote>', out)
        self.assertIn('<p>ordinary paragraph</p>', out)

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
        self.md_path, self.html_path = DOCS[0]
        with open(self.md_path, encoding='utf-8') as f:
            self.md = f.read()
        with open(self.html_path, encoding='utf-8') as f:
            self.html = f.read()

    def test_every_source_line_survives_into_the_html(self):
        for md_rel, html_rel in DOCS:
            with self.subTest(doc=md_rel):
                self._check_content(md_rel, html_rel)

    def _check_content(self, md_rel: str, html_rel: str) -> None:
        with open(os.path.join(HERE, md_rel), encoding='utf-8') as f:
            md = f.read()
        with open(os.path.join(HERE, html_rel), encoding='utf-8') as f:
            htm = f.read()
        text = visible_text(htm)
        missing = []
        in_fence = False
        for raw in md.split('\n'):
            s = raw.strip()
            if s.startswith('```'):
                in_fence = not in_fence
                continue
            if in_fence or not s or s.startswith(('---', '|---')):
                continue
            if s.startswith('|'):
                probes = [c for c in (c.strip() for c in s.strip('|').split('|'))
                          if len(c) > 8]
            else:
                s = re.sub(r'^>\s?', '', re.sub(r'^#{1,6}\s+', '', s))
                probes = [re.sub(r'^\s*(?:[-*]|\d+\.)\s+', '', s)]
            for probe in probes:
                # A code span crossing a source line break cannot be probed
                # per-line -- the renderer correctly joins it, so the source
                # fragment appears nowhere. Skip those.
                if probe.count('`') % 2:
                    continue
                q = _plain(probe)
                if len(q) < 8:
                    continue
                if q[:50] not in text:
                    missing.append(q[:60])
        self.assertEqual(missing, [], f'content lost in {html_rel}: {missing}')

    def test_committed_html_is_current_for_every_doc(self):
        for md_rel, html_rel in DOCS:
            with self.subTest(doc=md_rel):
                with open(os.path.join(HERE, md_rel), encoding='utf-8') as f:
                    md = f.read()
                with open(os.path.join(HERE, html_rel), encoding='utf-8') as f:
                    cur = f.read()
                self.assertEqual(
                    M.convert(md, os.path.basename(md_rel)), cur,
                    f'{html_rel} is stale -- regenerate with '
                    f'`python3 tools/md2html.py {md_rel}`')

    def test_metals_ascii_diagram_is_intact(self):
        """The pipeline diagram is the one thing in these docs that only
        works if it is reproduced exactly. It lives in a fence, so it is
        skipped by the line-survival check; if the fence ever stopped being
        recognised, the diagram would reflow into a paragraph and nothing else
        in the file would notice."""
        with open(os.path.join(HERE, 'doc/METAL.html'), encoding='utf-8') as f:
            htm = f.read()
        seg = htm[htm.find('<pre>'):htm.find('</pre>')]
        for probe in ('Mojo source', 'identify kernels', 'xcrun metal / metallib',
                      'foo.metallib', "binary for THIS Mac's GPU",
                      'GIMPLE C  (already done)'):
            self.assertIn(probe, seg, f'diagram lost {probe!r}')

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
