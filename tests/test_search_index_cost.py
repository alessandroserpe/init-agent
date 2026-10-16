"""Bound the SQL work of indexing many files; no model calls."""
from pathlib import Path
import tempfile
import unittest

from init_agent.local_search import update_search_index, search
from init_agent.run import prepare_repository
from init_agent.repo_budget import RepoBudget, budget_scope


class SearchIndexCostTests(unittest.TestCase):
    def test_many_new_files_and_batch_replacements_fit_sql_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for i in range(160):
                (root/f'file{i}.py').write_text('def worker():\n'+'    x=1\n'*240+'    return "oldneedle"\n')
            prepare_repository(root)
            budget=RepoBudget();budget.limits['sql_steps']=400_000
            with budget_scope(budget):
                result=update_search_index(root)
            self.assertEqual(result['updated'],160)
            for i in range(160):
                p=root/f'file{i}.py'
                if i%2:p.unlink()
                else:p.write_text(p.read_text().replace('oldneedle','newneedle'))
            prepare_repository(root)
            budget=RepoBudget();budget.limits['sql_steps']=800_000
            with budget_scope(budget):
                result=update_search_index(root)
            self.assertEqual((result['updated'],result['removed']),(80,80))
            self.assertFalse(search(root,'oldneedle')['results'])
            self.assertTrue(search(root,'newneedle')['results'])

    def test_oversized_line_does_not_abort_other_files_or_leave_partial_hits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'good.py').write_text('x="usefulneedle"\n')
            (root/'large.txt').write_text('partialneedle\n'+'x'*20000+'\n')
            prepare_repository(root)
            result=update_search_index(root)
            self.assertIn('large.txt',result['skipped'])
            self.assertTrue(search(root,'usefulneedle')['results'])
            self.assertFalse(search(root,'partialneedle')['results'])

if __name__=='__main__':unittest.main()
