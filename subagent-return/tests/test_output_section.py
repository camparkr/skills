"""Controls for the output section's parser, to the grammar the brief's instruction states (TC-8, R-13).

Each case pairs a section that must be read with one of the same shape that must not be: an empty section, a missing
heading, a near-miss heading, `none` beside a path, and a path named only in prose. They were committed before the
parser existed, and each failed then.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import unittest

import world  # noqa: F401  (puts the skill's scripts on the import path)
import output_section as grammar


class Grammar(unittest.TestCase):

    def test_tc8_a_section_listing_paths_claims_each_once_in_order(self):
        found = grammar.parse('Done.\n\n## Output\n- `docs/a.md`\n* b.md\n`c.md`\nd.md  \ndocs/a.md\n')
        self.assertEqual((found.state, found.claims), ('claims', ['docs/a.md', 'b.md', 'c.md', 'd.md']))

    def test_tc8_empty_no_heading_is_no_output_section(self):
        self.assertEqual(grammar.parse('I wrote docs/a.md and nothing more.').state, 'missing')

    def test_tc8_likeness_a_near_miss_heading_opens_no_section(self):
        for heading in ('## Output:', '## Outputs', '### Output', '## Output ', ' ## Output', '## output'):
            with self.subTest(heading=heading):
                self.assertEqual(grammar.parse('Done.\n%s\na.md\n' % heading).state, 'missing')

    def test_tc8_empty_a_heading_with_no_line_under_it_is_malformed(self):
        for text in ('Done.\n## Output\n', 'Done.\n## Output\n   \n\t\n', 'Done.\n## Output\n## Next\na.md\n'):
            with self.subTest(text=text):
                found = grammar.parse(text)
                self.assertEqual((found.state, found.reason), ('malformed', grammar.NO_LINE))

    def test_tc8_likeness_none_beside_a_path_is_malformed(self):
        found = grammar.parse('## Output\nnone\na.md\n')
        self.assertEqual((found.state, found.reason), ('malformed', grammar.NONE_BESIDE_PATH))

    def test_tc8_none_alone_claims_nothing(self):
        for text in ('## Output\nnone\n', '## Output\n- none\n', '## Output\n`none`\n'):
            with self.subTest(text=text):
                self.assertEqual(grammar.parse(text).state, 'none')

    def test_tc8_likeness_none_in_capitals_is_a_path(self):
        self.assertEqual(grammar.parse('## Output\nNone\n').claims, ['None'])

    def test_tc8_a_path_named_in_prose_is_claimed_only_from_the_section(self):
        found = grammar.parse("I checked `report.md` and `notes.md`.\n\n## Output\n- `report.md`\n")
        self.assertEqual(found.claims, ['report.md'])

    def test_tc8_likeness_prose_naming_a_path_with_section_none_claims_nothing(self):
        found = grammar.parse('The inputs (`a.md`, `b.md`) agree.\n\n## Output\nnone\n')
        self.assertEqual((found.state, found.claims), ('none', []))

    def test_tc8_the_last_heading_opens_the_section(self):
        found = grammar.parse('## Output\ndraft.md\n\nRevised after review.\n\n## Output\nfinal.md\n')
        self.assertEqual(found.claims, ['final.md'])

    def test_tc8_the_section_ends_at_the_next_heading(self):
        found = grammar.parse('## Output\nnotes.md\n## Appendix\nappendix.md\n')
        self.assertEqual(found.claims, ['notes.md'])

    def test_tc8_likeness_an_indented_hash_does_not_end_the_section(self):
        found = grammar.parse('## Output\nnotes.md\n  # not a heading\n')
        self.assertEqual(found.claims, ['notes.md', '# not a heading'])

    def test_tc8_a_code_fence_inside_the_section_is_read_as_paths(self):
        # A fence line is a path once its one pair of backticks is removed, and fails as a file that does not exist.
        found = grammar.parse('## Output\n```\na.md\n```\n')
        self.assertEqual(found.claims, ['`', 'a.md'])

    def test_tc8_a_path_holding_spaces_is_read_whole(self):
        self.assertEqual(grammar.parse('## Output\n- `my notes/a b.md`\n').claims, ['my notes/a b.md'])

    def test_tc8_empty_text_that_is_not_text_has_no_section(self):
        self.assertEqual(grammar.parse(None).state, 'missing')

    def test_tc8_windows_line_endings_are_read_the_same(self):
        self.assertEqual(grammar.parse('Done.\r\n## Output\r\na.md\r\n').claims, ['a.md'])


if __name__ == '__main__':
    unittest.main()
