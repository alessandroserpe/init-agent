'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const ts = require(path.join(__dirname, 'node_modules', 'typescript', 'lib', 'typescript.js'));

// The parent caps V8 heap and process lifetime. These limits also apply before
// TypeScript parses any workspace source.
const MAX_FILES = 1000;
const MAX_FILE_BYTES = 2 * 1024 * 1024;
const MAX_TOTAL_BYTES = 20 * 1024 * 1024;
const MAX_OUTPUT_BYTES = 2 * 1024 * 1024;
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const root = fs.realpathSync(input.root);
const target = path.resolve(root, input.path);
const compilerLib = path.join(__dirname, 'node_modules', 'typescript', 'lib') + path.sep;
const gaps = [], consumed = new Map(), contentCache = new Map();
let totalBytes = 0, fileCount = 0, fatal = null;
function within(base, p) {
  const r = path.relative(base, p);
  return r === '' || (!r.startsWith('..' + path.sep) && r !== '..' && !path.isAbsolute(r));
}
function safePath(p, allowCompilerLib = false) {
  const abs = path.resolve(p);
  if (allowCompilerLib && abs.startsWith(compilerLib)) return abs;
  if (!within(root, abs)) return null;
  try {
    let cursor = root;
    for (const part of path.relative(root, abs).split(path.sep).filter(Boolean)) {
      cursor = path.join(cursor, part);
      if (fs.lstatSync(cursor).isSymbolicLink()) return null;
    }
    const real = fs.realpathSync(abs);
    if (!within(root, real) || real.split(path.sep).includes('node_modules')) return null;
    return real;
  } catch (_) { return null; }
}
function relative(p) { return path.relative(root, p).split(path.sep).join('/'); }
function readWorkspace(p) {
  const safe = safePath(p);
  if (!safe) return undefined;
  if (contentCache.has(safe)) return contentCache.get(safe);
  let stat;
  try { stat = fs.statSync(safe); } catch (_) { return undefined; }
  if (!stat.isFile() || stat.size > MAX_FILE_BYTES || fileCount >= MAX_FILES || totalBytes + stat.size > MAX_TOTAL_BYTES) {
    fatal = 'TypeScript source/configuration resource limit exceeded';
    return undefined;
  }
  let raw, text;
  try { raw = fs.readFileSync(safe); text = raw.toString('utf8'); } catch (_) { return undefined; }
  const bytes = raw.length;
  if (bytes > MAX_FILE_BYTES || totalBytes + bytes > MAX_TOTAL_BYTES) {
    fatal = 'TypeScript source/configuration resource limit exceeded';
    return undefined;
  }
  fileCount += 1; totalBytes += bytes;
  contentCache.set(safe, text);
  consumed.set(relative(safe), crypto.createHash('sha256').update(raw).digest('hex'));
  return text;
}
if (!safePath(target) || !fs.statSync(target).isFile()) throw new Error('unsafe or missing target');
const gapsOut = (message) => process.stdout.write(JSON.stringify({ analyzer: 'typescript-compiler', version: ts.version, structural: false,
  symbols: [], edges: [], gaps: [message], dependencies: Object.fromEntries(consumed), config_fingerprint: fingerprint() }));
function fingerprint() { return crypto.createHash('sha256').update(ts.version + '\0' + JSON.stringify(options || {})).digest('hex'); }

// Find config only between the target and root. Never follow a config symlink
// outside the workspace, and never use TypeScript's unrestricted default host.
let configPath = null;
for (let dir = path.dirname(target); within(root, dir); dir = path.dirname(dir)) {
  const candidate = path.join(dir, 'tsconfig.json');
  if (fs.existsSync(candidate)) {
    if (!safePath(candidate)) { gapsOut('tsconfig path contains an unsafe symlink'); process.exit(0); }
    configPath = candidate; break;
  }
  if (dir === root) break;
}
let options = { allowJs: true, checkJs: false, jsx: ts.JsxEmit.Preserve,
  target: ts.ScriptTarget.Latest, moduleResolution: ts.ModuleResolutionKind.Node10 };
if (configPath) {
  const parseHost = {
    useCaseSensitiveFileNames: ts.sys.useCaseSensitiveFileNames,
    getCurrentDirectory: () => root,
    getCanonicalFileName: p => p,
    onUnRecoverableConfigFileDiagnostic: () => {},
    fileExists: p => !!safePath(p) && fs.existsSync(safePath(p)),
    readFile: p => readWorkspace(p),
    // The target is the only root name. Globs in tsconfig must not trigger a
    // workspace crawl; inherited compiler options are still parsed normally.
    readDirectory: () => [],
  };
  const parsed = ts.getParsedCommandLineOfConfigFile(configPath, {}, parseHost);
  if (!parsed || parsed.errors.some(d => d.code !== 18003) || fatal) {
    gapsOut(fatal || 'tsconfig could not be safely resolved'); process.exit(0);
  }
  if (parsed.projectReferences && parsed.projectReferences.length) {
    gapsOut('tsconfig project references are unsupported'); process.exit(0);
  }
  options = { ...options, ...parsed.options, noResolve: false };
} else gaps.push('tsconfig.json not found; using conservative defaults');

const host = ts.createCompilerHost(options, true);
const originalRead = host.readFile.bind(host);
host.readFile = p => safePath(p, true) ? (safePath(p, true).startsWith(compilerLib) ? originalRead(p) : readWorkspace(p)) : undefined;
host.fileExists = p => !!safePath(p, true) && fs.existsSync(safePath(p, true));
host.getSourceFile = (fileName, languageVersion, onError) => {
  const safe = safePath(fileName, true);
  if (!safe) return undefined;
  let sourceText;
  if (safe.startsWith(compilerLib)) {
    try { sourceText = originalRead(safe); } catch (e) { if (onError) onError(String(e)); return undefined; }
  } else sourceText = readWorkspace(safe);
  if (sourceText === undefined) return undefined;
  return ts.createSourceFile(fileName, sourceText, languageVersion, true);
};

const program = ts.createProgram([target], options, host);
if (fatal) { gapsOut(fatal); process.exit(0); }
const sources = program.getSourceFiles().filter(s => safePath(s.fileName) !== null);
const sourceFile = program.getSourceFile(target);
if (!sourceFile || program.getSyntacticDiagnostics(sourceFile).length) {
  gapsOut('target contains TypeScript syntax diagnostics'); process.exit(0);
}
for (const sf of sources) {
  if (sf !== sourceFile && program.getSyntacticDiagnostics(sf).length) {
    gapsOut('imported source contains TypeScript syntax diagnostics'); process.exit(0);
  }
}
const sourceSet = new Set(sources.map(s => path.resolve(s.fileName)));
const symbols = [], edges = [], symbolByNode = new Map(), declToRecord = new Map();
function nameOf(n) { return n && n.name && n.name.getText ? n.name.getText().replace(/^['"]|['"]$/g, '') : undefined; }
function implementationKind(node) {
  if (ts.isFunctionDeclaration(node) && node.body) return 'function';
  if (ts.isMethodDeclaration(node) && node.body) return 'method';
  if (ts.isConstructorDeclaration(node) && node.body) return 'method';
  if (ts.isGetAccessorDeclaration(node) && node.body || ts.isSetAccessorDeclaration(node) && node.body) return 'method';
  if (ts.isClassDeclaration(node)) return 'class';
  if (ts.isVariableDeclaration(node) && node.initializer &&
      ts.isVariableDeclarationList(node.parent) && (node.parent.flags & ts.NodeFlags.Const) &&
      (ts.isArrowFunction(node.initializer) || ts.isFunctionExpression(node.initializer))) return 'function';
  return null;
}
for (const sf of sources) {
  const isTarget = path.resolve(sf.fileName) === target;
  function visit(node, scopes) {
    const kind = ts.isFunctionDeclaration(node) ? 'function' : ts.isClassDeclaration(node) ? 'class' : ts.isInterfaceDeclaration(node) ? 'interface' : ts.isTypeAliasDeclaration(node) ? 'type' : ts.isEnumDeclaration(node) ? 'enum' : ts.isMethodDeclaration(node) ? 'method' : ts.isPropertyDeclaration(node) ? 'property' : ts.isVariableDeclaration(node) ? 'variable' : null;
    const nm = nameOf(node), nested = (kind && nm) ? scopes.concat(nm) : scopes;
    if (kind && nm) {
      const start = sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1;
      const end = sf.getLineAndCharacterOfPosition(node.getEnd()).line + 1;
      const record = { name: nm, qualified_name: nested.join('.'), line: start, end_line: end, kind };
      if (isTarget) { symbols.push(record); symbolByNode.set(node, record); }
      declToRecord.set(node, { record, sf, implementation: implementationKind(node) });
    }
    ts.forEachChild(node, child => visit(child, nested));
  }
  visit(sf, []);
}
const checker = program.getTypeChecker();
function resolveAlias(sym) { if (sym && (sym.flags & ts.SymbolFlags.Alias)) { try { return checker.getAliasedSymbol(sym); } catch (_) { return sym; } } return sym; }
function declRecord(sym, expectedKind) {
  sym = resolveAlias(sym); if (!sym) return null;
  const declarations = sym.getDeclarations() || [];
  if (declarations.length !== 1) return null;
  const d = declarations[0], info = declToRecord.get(d), key = path.resolve(d.getSourceFile().fileName);
  if (!info || info.implementation !== expectedKind || !sourceSet.has(key) || !safePath(key)) return null;
  return { ...info, path: relative(safePath(key)) };
}
function directCallSymbol(expression) {
  if (ts.isIdentifier(expression)) return checker.getSymbolAtLocation(expression);
  if (!ts.isPropertyAccessExpression(expression) || !ts.isIdentifier(expression.expression)) return null;
  const namespace = checker.getSymbolAtLocation(expression.expression);
  if (!namespace || !(namespace.getDeclarations() || []).some(ts.isNamespaceImport)) return null;
  return checker.getSymbolAtLocation(expression.name);
}
const edgeKeys = new Set();
function addEdge(row) { const k = JSON.stringify(row); if (!edgeKeys.has(k)) { edgeKeys.add(k); edges.push(row); } }
function enclosing(node) { for (let p = node; p; p = p.parent) { const r = symbolByNode.get(p); if (r) return r; } return null; }
const currentHash = consumed.get(relative(target));
function endpointHash(p) { return consumed.get(p); }
function visitTarget(node) {
  if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) {
    const spec = node.moduleSpecifier;
    if (spec && ts.isStringLiteral(spec)) {
      const resolved = ts.resolveModuleName(spec.text, target, options, host).resolvedModule;
      if (!resolved) gaps.push('unresolved import: ' + relative(target) + ':' + (sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1));
      else {
        const destSafe = safePath(resolved.resolvedFileName);
        if (destSafe && sourceSet.has(path.resolve(destSafe))) {
          const line = sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1;
          const imported = node.importClause && node.importClause.name ? node.importClause.name.text : '*';
          addEdge({ relation: 'imports', line, source_symbol: enclosing(node)?.qualified_name || '<module>', target_path: relative(destSafe), target_symbol: imported, target_line: 1, method: 'typescript-compiler', source_sha256: currentHash, target_sha256: endpointHash(relative(destSafe)) });
        }
      }
    }
  }
  if (ts.isCallExpression(node) || ts.isNewExpression(node)) {
    const line = sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1;
    let dest = null;
    try {
      if (ts.isNewExpression(node) && ts.isIdentifier(node.expression))
        dest = declRecord(checker.getSymbolAtLocation(node.expression), 'class');
      else if (ts.isCallExpression(node))
        dest = declRecord(directCallSymbol(node.expression), 'function');
    } catch (_) {}
    if (dest) addEdge({ relation: ts.isNewExpression(node) ? 'constructs' : 'calls', line, source_symbol: enclosing(node)?.qualified_name || '<module>', target_path: dest.path, target_symbol: dest.record.qualified_name, target_line: dest.record.line, method: 'typescript-compiler', source_sha256: currentHash, target_sha256: endpointHash(dest.path) });
    else gaps.push('unresolved dynamic or external call: ' + relative(target) + ':' + line);
  }
  ts.forEachChild(node, visitTarget);
}
if (sourceFile) visitTarget(sourceFile);
if (fatal) { gapsOut(fatal); process.exit(0); }
const output = JSON.stringify({ analyzer: 'typescript-compiler', version: ts.version, structural: true,
  symbols, edges, gaps: [...new Set(gaps)], dependencies: Object.fromEntries(consumed), config_fingerprint: fingerprint() });
if (Buffer.byteLength(output) > MAX_OUTPUT_BYTES) throw new Error('output limit exceeded');
process.stdout.write(output);
