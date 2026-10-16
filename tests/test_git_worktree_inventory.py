"""Main checkout inventory with linked worktrees and confined Git metadata."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from init_agent.git_boundary import validated_git_dir
from init_agent.graph_store import GraphStore
from init_agent.local_search import search
from init_agent.local_watch import Maintainer, maintenance_lock
from init_agent.utils import git_read_environment, iter_indexable_files, run_git_read


class GitWorktreeInventoryTests(unittest.TestCase):
    def fixture(self, parent):
        root=parent/'main';linked=parent/'linked';root.mkdir()
        def git(*args):
            return subprocess.run(['/usr/bin/git','-C',str(root),*args],env=git_read_environment(),capture_output=True,text=True,check=True)
        git('init','-q')
        (root/'app.py').write_text('MESSAGE="sourceneedle"\n')
        (root/'nested').mkdir()
        (root/'nested/.gitignore').write_text('/generated/\n*.log\n!keep.log\n')
        (root/'tracked.log').write_text('tracked content\n')
        git('add','.')
        git('-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','fixture')
        (root/'.gitignore').write_text('*.log\n')
        (root/'nested/generated').mkdir()
        (root/'nested/generated/output.py').write_text('MESSAGE="ignoredneedle"\n')
        (root/'nested/drop.log').write_text('ignored log\n')
        (root/'nested/keep.log').write_text('keep override\n')
        (root/'new.py').write_text('MESSAGE="newneedle"\n')
        git('worktree','add','--detach',str(linked),'HEAD')
        return root,linked

    def test_main_checkout_respects_gitignore_with_linked_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,linked=self.fixture(Path(tmp))
            self.assertEqual(validated_git_dir(root),root.resolve()/'.git')
            result=run_git_read(root,'ls-files','-co','--exclude-standard')
            self.assertEqual(result.returncode,0)
            paths={p.relative_to(root).as_posix() for p in iter_indexable_files(root)}
            self.assertTrue({'app.py','new.py','tracked.log','nested/keep.log'} <= paths)
            self.assertNotIn('nested/generated/output.py',paths)
            self.assertNotIn('nested/drop.log',paths)
            # Linked checkout still has an external admin path and is unsupported.
            with self.assertRaises(OSError):validated_git_dir(linked)

    def test_refresh_removes_previously_indexed_ignored_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,_=self.fixture(Path(tmp))
            with patch('init_agent.utils._git_indexable_paths',return_value=None), maintenance_lock(root):
                Maintainer(root).tick()
            self.assertTrue(search(root,'ignoredneedle')['results'])
            with maintenance_lock(root):event=Maintainer(root).tick()
            self.assertGreater(event['counts']['removed'],0)
            self.assertFalse(search(root,'ignoredneedle')['results'])
            self.assertTrue(search(root,'sourceneedle')['results'])
            with GraphStore(root) as store:
                self.assertFalse(store.connection.execute("SELECT 1 FROM files WHERE path='nested/generated/output.py'").fetchone())

    def test_only_canonical_internal_worktree_common_directory_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,_=self.fixture(Path(tmp))
            pointer=next((root/'.git/worktrees').glob('*/commondir'))
            for value in ('../../..', '/tmp', '../outside', '../../other', '../..\nextra'):
                pointer.write_text(value)
                with self.subTest(value=value), patch('init_agent.utils.run_bounded') as spawn:
                    with self.assertRaises(OSError):run_git_read(root,'status','--short')
                    spawn.assert_not_called()
            pointer.write_text('../..\n')
            self.assertEqual(validated_git_dir(root),root.resolve()/'.git')
            (root/'.git/commondir').write_text('../..\n')
            with self.assertRaises(OSError):validated_git_dir(root)
            (root/'.git/commondir').unlink()
            pointer.unlink();pointer.symlink_to(root/'.git/config')
            with self.assertRaises(OSError):validated_git_dir(root)

if __name__=='__main__':unittest.main()
