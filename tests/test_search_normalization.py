from pathlib import Path
import tempfile
import unittest
import unicodedata
from unittest.mock import patch
from init_agent.graph_store import GraphStore
from init_agent.local_search import update_search_index

from init_agent.local_search import search, terms
from init_agent.local_watch import Maintainer, maintenance_lock
from init_agent.memory import add_note
from init_agent.search_tokens import search_terms
from init_agent.text_tokens import FUNCTION_WORDS, identifier_terms


class SearchNormalizationTests(unittest.TestCase):
    def test_unicode_words_identifiers_and_composed_forms(self):
        cases = [
            ('Perché', []), ('già', ['già']),
            ('HTTPÉtatService', ['http','état','service']),
            ('prüfeÜbertragung', ['prüfe','übertragung']),
            ('validaciónUsuario_v2', ['validación','usuario','v','2']),
            ('ΔοκιμήΧρήστη', ['δοκιμή','χρήστη']),
            ('用户认证', ['用户认证']),
        ]
        for value, expected in cases:
            for form in ('NFC','NFD'):
                with self.subTest(value=value,form=form):
                    self.assertEqual(terms(unicodedata.normalize(form,value)),expected)

    def test_ascii_technical_terms_remain_identical(self):
        for value in ('MCPServerStartup repoGraphSearch','foo_bar/path-name.py',
                      'HTTP2Server v2 x i sql db UI', 'skill install but retry too',
                      'search_index_meta SEARCH_INDEX_VERSION'):
            self.assertEqual(search_terms(value),[t for t in identifier_terms(value) if t not in FUNCTION_WORDS])

    def test_legacy_source_index_is_rebuilt_without_source_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'impl.py').write_text('MESSAGE="café"\n')
            legacy=lambda text: [t for t in identifier_terms(text) if t not in FUNCTION_WORDS]
            with patch('init_agent.local_search.terms',legacy), maintenance_lock(root):
                Maintainer(root).tick()
            with GraphStore(root) as store:
                store.connection.execute("UPDATE search_index_meta SET value=3 WHERE key='version'")
                store.connection.commit()
            self.assertFalse(search(root,'café')['results'])
            result=update_search_index(root)
            self.assertTrue(result['rebuilt'])
            self.assertEqual(result['updated'],1)
            self.assertEqual(search(root,'café')['results'][0]['path'],'impl.py')

    def test_accented_and_non_latin_source_and_notes_are_retrievable(self):
        for word in ('café','übertragung','validación','δοκιμή','用户认证'):
            with self.subTest(word=word), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                (root/'impl.py').write_text(f'MESSAGE="{word}"\n')
                (root/'noise.py').write_text('MESSAGE="caf"\n')
                with maintenance_lock(root):Maintainer(root).tick()
                note=add_note(root,None,f'Decision: {word}',scope='repo')
                for query in (word,unicodedata.normalize('NFD',word)):
                    answer=search(root,query)
                    self.assertEqual([h['path'] for h in answer['results']],['impl.py'])
                    self.assertEqual(answer['memories'][0]['id'],note['id'])

if __name__=='__main__':unittest.main()
