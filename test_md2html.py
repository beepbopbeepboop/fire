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

# The documents this generator produced, and the only place they are checked
# against anything. The `.md` sources have been removed -- the HTML is the
# document now -- so there is deliberately NO source to compare against here
# any more, and the three checks below are what is left:
#
#   - the renderer still handles every construct (TestStructure,
#     TestContentSurvival: fixtures, not documents);
#   - each page is well-formed and its load-bearing content is intact
#     (TestRenderedDocuments);
#   - the tool still works (TestTooling).
#
# What is gone is the strongest check these files ever had: proving no word
# of a source document was dropped in conversion, which is why the three
# content-loss bugs this renderer had were caught at all. From here they are
# guarded by fixture tests only.
DOCS = ('doc/GPU_OFFLOAD_PLAN.html', 'doc/METAL.html')

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


class TestRenderedDocuments(unittest.TestCase):
    """Checks on the two pages themselves, now that their sources are gone.

    A fixture-only test proves the renderer handles the constructs someone
    thought of. These assert that each real page is well-formed and still
    contains the specific things it exists to contain -- which is the check
    that stays meaningful without a `.md` to diff against.
    """

    def _html(self, rel: str) -> str:
        path = os.path.join(HERE, rel)
        if not os.path.exists(path):
            self.skipTest(f'{rel} not present')
        with open(path, encoding='utf-8') as f:
            return f.read()

    def test_every_page_is_well_formed(self):
        for rel in DOCS:
            with self.subTest(doc=rel):
                p = _Balance()
                p.feed(self._html(rel))
                self.assertEqual(p.errors, [], f'{rel}: {p.errors[:4]}')
                self.assertEqual(p.stack, [], f'{rel} unclosed: {p.stack[:4]}')

    def test_plan_keeps_its_whole_comparison_table(self):
        """The table whose first body row was once dropped.

        A row that fails to render leaves no trace: no empty cell, no broken
        border, no error. Four rows where there should be four is the whole
        test.
        """
        htm = self._html('doc/GPU_OFFLOAD_PLAN.html')
        seg = htm[htm.find('<table>'):htm.find('</table>')]
        for row in ('build wiring', 'artifact', 'portability', 'debuggability'):
            self.assertIn(f'<td>{row}</td>', seg, f'table lost its {row!r} row')
        self.assertEqual(seg.count('<tr>'), 5, 'header + 4 body rows')

    def test_plan_still_renders_its_code_blocks(self):
        htm = self._html('doc/GPU_OFFLOAD_PLAN.html')
        self.assertGreaterEqual(htm.count('<pre>'), 2,
                                'the _DEFERRED_PREFIXES quote and the '
                                'lists-offload example are both load-bearing')
        self.assertIn('_DEFERRED_PREFIXES', htm)
        self.assertIn('vec_add(a, b, o, 4)', htm)

    def test_metals_ascii_diagram_is_intact(self):
        """The pipeline diagram only works if reproduced exactly.

        It lives in a fence, so nothing else here would notice if the fence
        stopped being recognised and the diagram reflowed into a paragraph.
        """
        htm = self._html('doc/METAL.html')
        seg = htm[htm.find('<pre>'):htm.find('</pre>')]
        for probe in ('Mojo source', 'identify kernels', 'xcrun metal / metallib',
                      'foo.metallib', "binary for THIS Mac's GPU",
                      'GIMPLE C  (already done)'):
            self.assertIn(probe, seg, f'diagram lost {probe!r}')

    def test_status_blockquote_is_present(self):
        """The blockquote whose first line was once dropped.

        The status line is what tells a reader this document is a design note
        rather than a description of working code, so losing its opening line
        would misrepresent the document, not just truncate it.
        """
        htm = self._html('doc/METAL.html')
        seg = htm[htm.find('<blockquote>'):htm.find('</blockquote>')]
        self.assertIn('Status:', seg)
        self.assertIn('design note / parking lot', seg)


if __name__ == '__main__':
    unittest.main()
