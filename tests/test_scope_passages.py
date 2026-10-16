"""Structural safety checks for indexed source passages."""
import unittest
from init_agent.search_passages import passages, MAX_PASSAGE_CHARS, OversizedPassage


class ScopePassageTests(unittest.TestCase):
    def test_coverage_evidence_and_known_scope_boundaries(self):
        lines = [f'line {i}' for i in range(1, 101)]
        symbols = [dict(name='parent', line=2, end_line=80),
                   dict(name='child', line=25, end_line=49),
                   dict(name='sibling', line=83, end_line=100)]
        covered = set()
        for first, last, excerpt, names in passages(lines, symbols):
            self.assertEqual(excerpt, '\n'.join(lines[first-1:last]))
            self.assertLessEqual(last-first+1, 24)
            covered.update(range(first, last+1))
            for s in symbols:
                if s['name'] in names:
                    self.assertTrue(s['line'] <= first <= last <= s['end_line'])
                self.assertFalse(first < s['line'] <= last)
                self.assertFalse(first <= s['end_line'] < last)
        self.assertEqual(covered, set(range(1, 101)))

    def test_unknown_or_invalid_ends_only_label_declaration_line(self):
        for end in (None, 0, 101):
            with self.subTest(end=end):
                chunks = list(passages(['x']*60, [dict(name='unknown', line=22, end_line=end)]))
                labeled = [(first,last) for first,last,_,names in chunks if 'unknown' in names]
                self.assertEqual(labeled, [(22,22)])
                self.assertEqual(set(i for first,last,_,_ in chunks for i in range(first,last+1)), set(range(1,61)))

    def test_same_name_nested_scopes_do_not_remove_parent_context(self):
        chunks = list(passages(['x']*60, [dict(name='same',line=1,end_line=60), dict(name='same',line=5,end_line=10)]))
        self.assertTrue(all('same' in names for _,_,_,names in chunks))

    def test_long_lines_split_passages_without_losing_line_evidence(self):
        lines = [('marker' + str(i) + ' ' + 'x'*1990) for i in range(40)]
        chunks = list(passages(lines, []))
        self.assertEqual(set(i for first,last,_,_ in chunks for i in range(first,last+1)), set(range(1,41)))
        for first,last,excerpt,_ in chunks:
            self.assertLessEqual(len(excerpt),MAX_PASSAGE_CHARS)
            self.assertEqual(excerpt,'\n'.join(lines[first-1:last]))
        with self.assertRaises(OversizedPassage):
            list(passages(['x'*(MAX_PASSAGE_CHARS+1)], []))

    def test_no_symbols_preserves_fixed_windows_and_empty_input(self):
        chunks = list(passages(['x']*50, []))
        self.assertEqual([(f,l) for f,l,_,_ in chunks], [(1,24),(21,44),(41,50)])
        self.assertEqual(list(passages([], [])), [])

if __name__ == '__main__':
    unittest.main()
