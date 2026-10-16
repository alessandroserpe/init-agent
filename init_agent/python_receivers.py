"""Conservative, function-local receiver facts; no general type inference."""
import ast
from collections import Counter

from .parse_budget import parser_checkpoint


def module_types(tree, resolve_import):
    bindings = {}
    counts = Counter()

    class Bindings(ast.NodeVisitor):
        def visit(self, node):
            parser_checkpoint(node=True)
            return super().visit(node)

        def visit_Name(self, node):
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                counts[node.id] += 1

        def visit_Attribute(self, node):
            if isinstance(node.ctx, (ast.Store, ast.Del)) and isinstance(node.value, ast.Name):
                counts[node.value.id] += 1
            self.generic_visit(node)

        def visit_ExceptHandler(self, node):
            if node.name:
                counts[node.name] += 1
            self.generic_visit(node)

        def visit_MatchAs(self, node):
            if node.name:
                counts[node.name] += 1
            self.generic_visit(node)
        visit_MatchStar = visit_MatchAs

        def visit_MatchMapping(self, node):
            if node.rest:
                counts[node.rest] += 1
            self.generic_visit(node)

        def visit_FunctionDef(self, node):
            counts[node.name] += 1
        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node):
            counts[node.name] += 1

        def visit_Import(self, node):
            for alias in node.names:
                counts[alias.asname or alias.name.split('.')[0]] += 1

        def visit_ImportFrom(self, node):
            for alias in node.names:
                counts[alias.asname or alias.name] += 1

    Bindings().visit(tree)
    forbidden = set()
    for node in ast.walk(tree):
        parser_checkpoint(node=True)
        if isinstance(node, ast.Global):
            forbidden.update(node.names)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bindings[node.name] = {'module':'', 'name':node.name}
        elif isinstance(node, ast.ImportFrom):
            module = resolve_import(node.module or '', node.level)
            for alias in node.names:
                if alias.name != '*':
                    bindings[alias.asname or alias.name] = {'module':module, 'name':alias.name}
        elif isinstance(node, ast.Import):
            for alias in node.names:
                # Unaliased multi-component modules require further attribute
                # resolution and are intentionally outside this first pass.
                if alias.asname or '.' not in alias.name:
                    bindings[alias.asname or alias.name] = {'module':alias.name, 'name':''}
    return {k:v for k,v in bindings.items() if counts[k]==1 and k not in forbidden}


def receiver_facts(function, types):
    """Only unique parameters or unconditional single constructor assignments.

    Any competing binding anywhere in the function subtree suppresses inference,
    including nested scopes. This deliberately prefers missed edges to guesses.
    """
    writes = Counter()
    forbidden = set()
    for node in ast.walk(function):
        parser_checkpoint(node=True)
        if isinstance(node, ast.Name) and isinstance(node.ctx,(ast.Store,ast.Del)):
            writes[node.id] += 1
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx,(ast.Store,ast.Del)) and isinstance(node.value,ast.Name):
            forbidden.add(node.value.id)
        elif isinstance(node, ast.arg):
            writes[node.arg] += 1
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            forbidden.update(node.names)
        elif isinstance(node, (ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and node is not function:
            writes[node.name] += 1
        elif isinstance(node, (ast.Import,ast.ImportFrom)):
            for alias in node.names:
                writes[alias.asname or alias.name.split('.')[0]] += 1
        elif isinstance(node, ast.ExceptHandler) and node.name:
            writes[node.name] += 1
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            writes[node.name] += 1
        elif isinstance(node, ast.MatchMapping) and node.rest:
            writes[node.rest] += 1

    def type_ref(node):
        if isinstance(node, ast.Name):
            root = node.id
            value = types.get(root)
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            root = node.value.id
            module = types.get(root)
            value = ({'module':'.'.join(filter(None,(module['module'],module['name']))),
                      'name':node.attr} if module else None)
        else:
            return None
        if writes[root] or root in forbidden or not value or not value['name']:
            return None
        return value

    facts = {}
    for arg in [*function.args.posonlyargs,*function.args.args,*function.args.kwonlyargs]:
        value = type_ref(arg.annotation)
        if value:
            facts[arg.arg] = {**value,'after_line':function.lineno,'binding':'parameter_annotation'}
    for node in function.body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and isinstance(node.value,ast.Call):
            value = type_ref(node.value.func)
            if value:
                facts[node.targets[0].id] = {**value,'after_line':node.end_lineno,'binding':'local_constructor'}
    return ({k:v for k,v in facts.items() if writes[k]==1 and k not in forbidden},
            {k:v for k,v in types.items() if not writes[k] and k not in forbidden})
