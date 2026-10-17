"""Bounded, read-only Python test evidence; never import or execute repository tests."""
import ast
import json
from pathlib import Path
from .repo_files import repo_snapshot
from .scanner import iter_project_files
from .repo_budget import bounded_operation, checkpoint
from .parse_budget import preflight
from .contracts import TOOL_CONTRACT_VERSION


@bounded_operation
def find_tests(root, module, symbol, limit=3):
    if not isinstance(module, str) or len(module) > 200 or not all(p.isidentifier() for p in module.split(".")):
        raise ValueError("module must be a dotted Python module name")
    if not isinstance(symbol, str) or len(symbol) > 200 or not symbol.isidentifier():
        raise ValueError("symbol must be a top-level Python function name")
    root = Path(root).resolve(strict=True)
    if type(limit) is not int or not 1 <= limit <= 5:
        raise ValueError('limit must be an integer from 1 to 5')
    candidates, skipped, warnings = [], [], []
    paths = sorted(p for p in iter_project_files(root, warnings=warnings)
                   if p.suffix == '.py' and p.relative_to(root).parts[0] == 'tests')
    for path in paths[:1000]:
        checkpoint()
        relative = path.relative_to(root).as_posix()
        try:
            snap = repo_snapshot(root, relative)
            if snap.content is None or len(snap.content) > 256000:
                raise ValueError("test file exceeds parse limit")
            preflight(snap.content, "python")
            tree = ast.parse(snap.content)
            for index, _ in enumerate(ast.walk(tree)):
                checkpoint()
                if index >= 20000:
                    raise ValueError("test AST exceeds node limit")
        except (OSError, SyntaxError, TypeError, ValueError, RecursionError):
            if len(skipped) < 50: skipped.append(relative)
            warnings.append("Some test files could not be analyzed; results may be incomplete.")
            continue
        aliases = {}
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and not node.level:
                for name in node.names:
                    if node.module == module and name.name == symbol:
                        aliases[name.asname or name.name] = name.asname or name.name
                    elif node.module and module.startswith(node.module + '.') and name.name == module[len(node.module)+1:]:
                        alias = name.asname or name.name
                        aliases[alias + '.' + symbol] = alias
            elif isinstance(node, ast.Import):
                for name in node.names:
                    if name.name == module:
                        alias = name.asname or name.name
                        aliases[alias + '.' + symbol] = alias.split('.')[0]
        if not aliases:
            continue
        # Reject module-level rebindings of imported aliases, even if conditional.
        def walk_scope(node):
            yield node
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                    yield child
                else:
                    yield from walk_scope(child)
        rebound = {n.id for n in walk_scope(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del))}
        rebound.update(n.name for n in walk_scope(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
        rebound.update(_capture_names(walk_scope(tree)))
        imports = {}
        for n in walk_scope(tree):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                for name in n.names:
                    bound = name.asname or (name.name.split('.')[0] if isinstance(n,ast.Import) else name.name)
                    imports[bound] = imports.get(bound, 0) + 1
        rebound.update(name for name, count in imports.items() if count > 1)
        aliases = {key: value for key, value in aliases.items() if value not in rebound}
        tests = [(None,n) for n in tree.body if isinstance(n,ast.FunctionDef) and n.name.startswith('test_')]
        tests += [(c,n) for c in tree.body if isinstance(c,ast.ClassDef) for n in c.body
                  if isinstance(n,ast.FunctionDef) and n.name.startswith('test_')]
        lines = snap.content.splitlines()
        for cls, test in tests:
            checkpoint()
            nodes = list(walk_scope(test))
            shadowed = {n.id for n in nodes if isinstance(n,ast.Name) and isinstance(n.ctx,(ast.Store,ast.Del))}
            shadowed.update(a.arg for a in ast.walk(test.args) if isinstance(a,ast.arg))
            shadowed.update(n.name for n in nodes if n is not test and isinstance(n,(ast.FunctionDef,ast.ClassDef)))
            shadowed.update(_capture_names(nodes))
            for n in nodes:
                if isinstance(n,(ast.Import,ast.ImportFrom)):
                    shadowed.update(a.asname or a.name.split('.')[0] for a in n.names)
            calls = [n for n in nodes if isinstance(n,ast.Call) and _call_name(n.func) in aliases
                     and aliases[_call_name(n.func)] not in shadowed]
            if not calls:
                continue
            assertions = [n for n in nodes if isinstance(n,ast.Assert) or
                          (isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and
                           isinstance(n.func.value,ast.Name) and n.func.value.id=='self' and n.func.attr.startswith('assert'))]
            direct = [n for n in assertions if any(c in list(ast.walk(n)) for c in calls)]
            start_line = min([test.lineno] + [d.lineno for d in test.decorator_list])
            text = '\n'.join(lines[start_line-1:test.end_lineno])
            name = (cls.name + '.' if cls else '') + test.name
            unittest_base = cls and any(_call_name(base).split('.')[-1].endswith('TestCase') for base in cls.bases)
            if unittest_base:
                command = ['python3','-m','unittest',relative[:-3].replace('/','.')+'.'+name]
            elif cls is None or cls.name.startswith('Test'):
                command = ['python3','-m','pytest',relative+'::'+name.replace('.', '::')]
            else:
                command = None
            if len(name) > 200:
                warnings.append('Some oversized test names were omitted; results may be incomplete.')
                continue
            candidates.append({'path':relative,'test':name,'line':start_line,'end_line':test.end_lineno,
                'sha256':snap.sha256,'call_lines':sorted(set(c.lineno for c in calls))[:40],
                'call_expressions':sorted(set(_call_name(c.func)[:200] for c in calls))[:20],
                'assertion_lines':sorted(set(n.lineno for n in direct))[:40],
                'evidence_truncated':len(calls)>40 or len(direct)>40 or any(len(_call_name(c.func))>200 for c in calls),
                'evidence':'result used directly in assertion' if direct else 'direct call only; assertion linkage not established',
                'command_candidate':command, 'command_executed':False,
                'test_source':text if len(text)<=8000 else None,
                'source_omitted':len(text)>8000,
                'runner_status':'candidate_not_verified' if command else 'unknown'})
    candidates.sort(key=lambda c:(not bool(c['assertion_lines']),c['path'],c['line']))
    result = {'tool':'repo_test_candidates','contract':TOOL_CONTRACT_VERSION,'target':module+'.'+symbol,'status':'candidates' if candidates else 'no_direct_test_found',
            'candidates':candidates[:limit],'candidate_count':len(candidates),'scanned_test_files':min(len(paths),1000),
            'truncated':len(candidates)>limit or len(paths)>1000,'skipped_paths':skipped,
            'warnings':list(dict.fromkeys(warnings)),'limitations':'Static direct imports/calls only; no wildcard imports, fixtures or indirect calls. Dynamic patching/overridden assertion methods are not resolved. Assertion evidence does not prove scenario coverage. Runner commands are candidates, not imported or executed.'}

    # Keep selected metadata and complete test bodies within a shared envelope.
    for candidate in reversed(result['candidates']):
        if len(json.dumps(result, ensure_ascii=False)) <= 24000:
            break
        candidate['test_source'] = None
        candidate['source_omitted'] = True
        result['truncated'] = True
    while len(json.dumps(result, ensure_ascii=False)) > 24000:
        result['truncated'] = True
        if result['skipped_paths']:
            result['skipped_paths'].pop()
        elif result['candidates']:
            result['candidates'].pop()
        else:
            break
    if candidates and not result['candidates']:
        result['status'] = 'output_budget_exceeded'
    return result


def _call_name(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return ''
    return '.'.join([node.id, *reversed(parts)])


def _capture_names(nodes):
    for node in nodes:
        if isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name:
            yield node.name
        elif isinstance(node, ast.MatchMapping) and node.rest:
            yield node.rest


def handle_test_candidates(root, arguments):
    if set(arguments) - {'module', 'symbol', 'limit'}:
        raise ValueError('Unknown repo_test_candidates argument')
    return find_tests(root, arguments.get('module'), arguments.get('symbol'), arguments.get('limit', 3))
