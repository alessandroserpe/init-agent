"""On-demand local retrieval for MCP; maintenance belongs to Python."""
from contextlib import redirect_stdout
from pathlib import Path
import sys

from .contracts import TOOL_CONTRACT_VERSION
from .local_search import search
from .local_watch import Maintainer, maintenance_lock
from .metadata_limits import bounded_metadata


def make_repo_search_handler():
    # Each MCP server owns its cache. No global repository registry or background
    # worker is needed; expiry/reconciliation remains Maintainer's responsibility.
    worker = None
    last_warnings = []

    @bounded_metadata
    def handle(root: Path, arguments: dict):
        nonlocal worker, last_warnings
        if set(arguments) - {'query', 'limit', 'path_prefixes'}:
            raise ValueError('Unknown repo_search argument')
        query = arguments.get('query')
        limit = arguments.get('limit', 3)
        prefixes = arguments.get('path_prefixes', [])
        if not isinstance(query, str) or not query.strip() or len(query) > 1000:
            raise ValueError('repo_search requires a nonempty query of at most 1000 characters')
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError('repo_search limit must be an integer from 1 to 10')
        if not isinstance(prefixes, list) or len(prefixes) > 8 or any(
            not isinstance(p, str) or not p or Path(p).is_absolute() or '..' in Path(p).parts
            for p in prefixes
        ):
            raise ValueError('Use at most eight nonempty repository-relative path prefixes')
        resolved = root.resolve(strict=True)
        if worker is None or worker.root != resolved:
            worker = Maintainer(resolved)
            last_warnings = []
        with maintenance_lock(resolved):
            # Existing initialization/map diagnostics must never corrupt MCP stdout.
            with redirect_stdout(sys.stderr):
                event = worker.tick()
            if event is not None and event['status'] == 'error':
                raise RuntimeError('Repository maintenance failed; retry after resolving index errors')
            result = search(resolved, query.strip(), limit, prefixes)
        if event is not None:
            last_warnings = list(event.get('preparation', {}).get('warnings', []))
            if (event.get('search_index') or {}).get('skipped_count'):
                last_warnings.append('Some files could not be indexed; results may be incomplete.')
        result['warnings'] = list(dict.fromkeys([*last_warnings, *result['warnings']]))
        return {'tool': 'repo_search', 'contract': TOOL_CONTRACT_VERSION, **result,
                'maintenance': {'status': event['status'] if event else 'unchanged'}}

    return handle
