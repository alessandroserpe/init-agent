"""Git history lists touched paths, not change types or current inventory."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from init_agent.git_reader import commit_files


@unittest.skipUnless(Path('/usr/bin/git').is_file(), 'Requires system Git')
class GitCommitPathsTests(unittest.TestCase):
    def test_rename_and_deletion_return_destination_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def git(*args):
                return subprocess.check_output([
                    '/usr/bin/git', '-c', 'core.hooksPath=/dev/null',
                    '-c', 'commit.gpgSign=false', '-c', 'user.name=Local test',
                    '-c', 'user.email=local@example.invalid', *args,
                ], cwd=root, text=True).strip()
            git('init', '-q')
            (root/'original.py').write_text('value = 1\n')
            git('add', 'original.py')
            git('commit', '-qm', 'Initial file')
            git('mv', 'original.py', 'renamed.py')
            git('commit', '-qm', 'Rename file')
            self.assertEqual(commit_files(root, git('rev-parse', 'HEAD')), ['renamed.py'])
            git('rm', '-q', 'renamed.py')
            git('commit', '-qm', 'Delete file')
            self.assertFalse((root/'renamed.py').exists())
            self.assertEqual(commit_files(root, git('rev-parse', 'HEAD')), ['renamed.py'])

    def test_paths_preserve_whitespace_unicode_and_git_quoting_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def git(*args):
                return subprocess.check_output([
                    '/usr/bin/git', '-c', 'core.hooksPath=/dev/null',
                    '-c', 'commit.gpgSign=false', '-c', 'user.name=Local test',
                    '-c', 'user.email=local@example.invalid', *args,
                ], cwd=root, text=True).strip()
            git('init', '-q')
            names = [' leading.py', 'trailing.py ', 'tab\tname.py',
                     'line\nbreak.py', 'quote"name.py', 'back\\slash.py', 'café.py']
            for name in names:
                (root/name).write_text('value = 1\n')
            git('add', '--', *names)
            git('commit', '-qm', 'Unusual file names')
            self.assertCountEqual(commit_files(root, git('rev-parse', 'HEAD')), names)
