"""SQLite lifetime guard for owner-only, non-shared metadata directories.

Unlike ordinary files, stdlib SQLite cannot consume an open directory handle.
We retain the handles, verify identity on handoff/use, and reject paths where
another OS principal has rename rights. Same-UID hostile processes are outside
this boundary: they can already read/write the owner's private metadata.
"""
import os
import sqlite3

from .private_files import MetadataDirectory, require_private_sqlite_path
from .repo_budget import BudgetConnection


class MetadataConnection(BudgetConnection):
    def __init__(self, *args, anchor, leaf, **kwargs):
        self.metadata_anchor = anchor
        self.metadata_leaf = leaf
        super().__init__(*args, **kwargs)

    def validate_metadata(self):
        self.metadata_anchor.verify_identity()
        opened = os.fstat(self.metadata_leaf.fileno())
        current = os.stat('graph.sqlite', dir_fd=self.metadata_anchor.fd, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise OSError('SQLite database changed during metadata access')

    def close(self):
        try:
            super().close()
        finally:
            context = getattr(self, 'metadata_leaf_context', None)
            if context is not None:
                context.__exit__(None, None, None)
                self.metadata_leaf_context = None
            else:
                self.metadata_leaf.close()
            self.metadata_anchor.close()


def connect_metadata(root, *, readonly=False, timeout=1):
    anchor = MetadataDirectory(root)
    leaf_context = None
    conn = None
    try:
        require_private_sqlite_path(anchor.path)
        leaf_context = anchor.open('graph.sqlite', 'rb' if readonly else 'ab')
        leaf = leaf_context.__enter__()
        anchor.verify_identity()
        uri = (anchor.path / 'graph.sqlite').as_uri() + ('?mode=ro' if readonly else '?mode=rw')
        def factory(*args, **kwargs):
            return MetadataConnection(*args, anchor=anchor, leaf=leaf, **kwargs)
        conn = sqlite3.connect(uri, uri=True, timeout=timeout, factory=factory)
        # Keep the context manager alive until the connection is closed.
        conn.metadata_leaf_context = leaf_context
        conn.validate_metadata()
        return conn
    except BaseException:
        if conn is not None:
            conn.close()
        if leaf_context is not None:
            leaf_context.__exit__(None, None, None)
        anchor.close()
        raise
