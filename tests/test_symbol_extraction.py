from tests.support import *


class SymbolExtractionTests(InitAgentTestCase):
    def test_python_symbol_extraction(self) -> None:
        content = "import os\nfrom pathlib import Path\nclass Runner:\n    pass\ndef run(value):\n    return value\n"
        symbols, relations = extract_symbols_and_relations(content, "python")
        self.assertIn(("Runner", "class"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("run", "function"), [(item.name, item.kind) for item in symbols])
        self.assertIn("os", [item.target for item in relations])
        self.assertIn("pathlib", [item.target for item in relations])

    def test_python_multiline_function_signature_extraction(self) -> None:
        content = "class Session:\n    def resolve_redirects(\n        self,\n        response,\n    ):\n        return []\n"
        symbols, _ = extract_symbols_and_relations(content, "python")
        self.assertIn(("Session", "class"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("resolve_redirects", "method"), [(item.name, item.kind) for item in symbols])

    def test_python_ast_call_and_syntax_fallback_extraction(self) -> None:
        content = (
            "from service import build\n"
            "async def load():\n"
            "    return build().save()\n"
            "class Runner:\n"
            "    def run(self):\n"
            "        return self.execute()\n"
        )
        symbols, relations = extract_symbols_and_relations(content, "python")
        self.assertIn(("load", "function"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("run", "method"), [(item.name, item.kind) for item in symbols])
        calls = [item.target for item in relations if item.relation == "calls"]
        self.assertIn("build", calls)
        self.assertIn("save", calls)
        self.assertIn("execute", calls)

        fallback_symbols, fallback_relations = extract_symbols_and_relations("import os\ndef broken(:\n", "python")
        self.assertIn("os", [item.target for item in fallback_relations])
        self.assertIn(("broken", "function"), [(item.name, item.kind) for item in fallback_symbols])

    def test_python_relative_import_and_template_render_relations(self) -> None:
        content = (
            "from .models import Post\n"
            "from ..services.mail import send\n"
            "def detail(request):\n"
            "    return render(request, 'blog/detail.html', {'post': Post()})\n"
        )
        _, relations = extract_symbols_and_relations(content, "python", "blog/views.py")
        imports = [item.target for item in relations if item.relation == "imports"]
        templates = [item.target for item in relations if item.relation == "renders_template"]
        self.assertIn("blog.models", imports)
        self.assertIn("services.mail", imports)
        self.assertIn("blog/detail.html", templates)

    def test_go_symbol_extraction(self) -> None:
        content = 'package main\nimport (\n  "net/http"\n)\ntype Engine struct {}\nfunc (e *Engine) ServeHTTP() {}\nfunc New() {}\n'
        symbols, relations = extract_symbols_and_relations(content, "go")
        self.assertIn(("Engine", "struct"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("ServeHTTP", "function"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("New", "function"), [(item.name, item.kind) for item in symbols])
        self.assertIn("net/http", [item.target for item in relations])

    def test_rust_symbol_extraction(self) -> None:
        content = "use tokio::net::TcpListener;\nstruct Listener {}\nimpl Listener {}\npub async fn run() {}\n"
        symbols, relations = extract_symbols_and_relations(content, "rust")
        self.assertIn(("Listener", "struct"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("Listener", "impl"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("run", "function"), [(item.name, item.kind) for item in symbols])
        self.assertIn("tokio", [item.target for item in relations])

    def test_markdown_heading_and_readme_command_extraction(self) -> None:
        content = "# Project\n\n## Install\n\n```bash\npython3 -m pip install -e .\ninit-agent run login\n```\n"
        symbols, relations = extract_symbols_and_relations(content, "markdown", "README.md")
        pairs = {(item.name, item.kind) for item in symbols}
        self.assertIn(("Project", "heading"), pairs)
        self.assertIn(("Install", "heading"), pairs)
        self.assertIn(("python3 -m pip install -e .", "command_example"), pairs)
        self.assertIn(("init-agent run login", "command_example"), pairs)
        self.assertEqual(relations, [])

    def test_non_readme_markdown_only_extracts_headings(self) -> None:
        content = "# Guide\n\n```bash\nmake publish\n```\n"
        symbols, _ = extract_symbols_and_relations(content, "markdown", "docs/guide.md")
        pairs = {(item.name, item.kind) for item in symbols}
        self.assertIn(("Guide", "heading"), pairs)
        self.assertNotIn(("make publish", "command_example"), pairs)

    def test_json_toml_yaml_config_symbol_extraction(self) -> None:
        json_symbols, _ = extract_symbols_and_relations(
            '{"name": "demo", "scripts": {"test": "pytest", "build": "vite build"}}',
            "json",
            "package.json",
        )
        self.assertIn(("name", "config_key"), [(item.name, item.kind) for item in json_symbols])
        self.assertIn(("test", "package_script"), [(item.name, item.kind) for item in json_symbols])
        self.assertIn(("build", "package_script"), [(item.name, item.kind) for item in json_symbols])

        toml_symbols, _ = extract_symbols_and_relations(
            "[project]\nname = 'demo'\n[project.scripts]\ndemo = 'demo.cli:main'\n[tool.demo]\nflag = true\n",
            "toml",
            "pyproject.toml",
        )
        self.assertIn(("project", "config_key"), [(item.name, item.kind) for item in toml_symbols])
        self.assertIn(("tool", "config_key"), [(item.name, item.kind) for item in toml_symbols])
        self.assertIn(("demo", "project_script"), [(item.name, item.kind) for item in toml_symbols])

        yaml_symbols, _ = extract_symbols_and_relations("name: demo\nservices:\n  web: {}\n", "yaml", "compose.yaml")
        self.assertIn(("name", "config_key"), [(item.name, item.kind) for item in yaml_symbols])
        self.assertIn(("services", "config_key"), [(item.name, item.kind) for item in yaml_symbols])

    def test_php_route_extraction(self) -> None:
        content = (
            "<?php\n"
            "Route::get('/login', 'AuthController@login');\n"
            "$router->post('/sessions', 'SessionController@store');\n"
            "$routes = ['/admin' => 'AdminController@index'];\n"
        )
        symbols, relations = extract_symbols_and_relations(content, "php")
        self.assertIn(("/login", "route"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("/sessions", "route"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("/admin", "route"), [(item.name, item.kind) for item in symbols])
        handlers = [item.target for item in relations if item.relation == "route_to_handler"]
        self.assertIn("login", handlers)
        self.assertIn("store", handlers)
        self.assertIn("index", handlers)

    def test_php_stub_maps_are_not_routes(self) -> None:
        content = "<?php\n$stubs = [__DIR__.'/stubs/class.stub' => 'class.stub'];\n"
        symbols, relations = extract_symbols_and_relations(content, "php")
        self.assertNotIn(("/stubs/class.stub", "route"), [(item.name, item.kind) for item in symbols])
        self.assertNotIn("class.stub", [item.target for item in relations if item.relation == "route_to_handler"])

    def test_js_express_and_fastify_route_extraction(self) -> None:
        content = (
            "function showUser(req, res) {}\n"
            "app.get('/users/:id', showUser)\n"
            "fastify.route({\n"
            "  method: 'POST',\n"
            "  url: '/sessions',\n"
            "  handler: createSession\n"
            "})\n"
        )
        symbols, relations = extract_symbols_and_relations(content, "javascript")
        self.assertIn(("/users/:id", "route"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("/sessions", "route"), [(item.name, item.kind) for item in symbols])
        handlers = [item.target for item in relations if item.relation == "route_to_handler"]
        self.assertIn("showUser", handlers)
        self.assertIn("createSession", handlers)

    def test_js_ts_import_and_call_extraction(self) -> None:
        content = (
            "import { listTasks } from '../api/tasks';\n"
            "export function TaskList() {\n"
            "  listTasks();\n"
            "  return <h1>Tasks</h1>;\n"
            "}\n"
        )
        _, relations = extract_symbols_and_relations(content, "typescript")
        imports = [item.target for item in relations if item.relation == "imports"]
        calls = [item.target for item in relations if item.relation == "calls"]
        self.assertIn("../api/tasks", imports)
        self.assertIn("listTasks", calls)

    def test_python_flask_and_django_route_extraction(self) -> None:
        content = (
            "@app.route('/login')\n"
            "def login_view():\n"
            "    return 'ok'\n"
            "@bp.post('/sessions')\n"
            "def create_session():\n"
            "    return 'ok'\n"
            "urlpatterns = [\n"
            "    path('admin/', views.admin_dashboard),\n"
            "]\n"
        )
        symbols, relations = extract_symbols_and_relations(content, "python")
        self.assertIn(("/login", "route"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("/sessions", "route"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("/admin", "route"), [(item.name, item.kind) for item in symbols])
        handlers = [item.target for item in relations if item.relation == "route_to_handler"]
        self.assertIn("login_view", handlers)
        self.assertIn("create_session", handlers)
        self.assertIn("admin_dashboard", handlers)

    def test_go_gin_route_extraction(self) -> None:
        content = 'package main\nfunc setup(r *gin.Engine) {\n  r.GET("/users/:id", getUser)\n  authorized.POST("/sessions", auth.CreateSession)\n}\n'
        symbols, relations = extract_symbols_and_relations(content, "go")
        self.assertIn(("/users/:id", "route"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("/sessions", "route"), [(item.name, item.kind) for item in symbols])
        handlers = [item.target for item in relations if item.relation == "route_to_handler"]
        self.assertIn("getUser", handlers)
        self.assertIn("CreateSession", handlers)

    def test_php_function_call_relation_extraction(self) -> None:
        content = (
            "<?php\n"
            "require_once 'functions.php';\n"
            "function pageController() { return renderDashboard(); }\n"
            "$result = buildForm($record);\n"
            "if (isset($result)) { echo sanitizeOutput(trim($result)); }\n"
            "$rows = mysqli_num_rows($query);\n"
            "$json = json_decode(file_get_contents($path), true);\n"
            "$service->methodCall();\n"
            "ClassName::staticCall();\n"
        )
        symbols, relations = extract_symbols_and_relations(content, "php")
        self.assertIn(("pageController", "function"), [(item.name, item.kind) for item in symbols])
        calls = [item.target for item in relations if item.relation == "calls"]
        self.assertIn("renderDashboard", calls)
        self.assertIn("buildForm", calls)
        self.assertIn("sanitizeOutput", calls)
        self.assertNotIn("isset", calls)
        self.assertNotIn("trim", calls)
        self.assertNotIn("mysqli_num_rows", calls)
        self.assertNotIn("json_decode", calls)
        self.assertNotIn("file_get_contents", calls)

    def test_php_sql_table_usage_extraction(self) -> None:
        content = (
            "<?php\n"
            "$rows = mysqli_query($db, \"SELECT title FROM pages WHERE id = 1\");\n"
            "$update = mysqli_query($db, 'UPDATE users SET active = 1');\n"
            "$insert = mysqli_query($db, 'INSERT INTO audit_log (event) VALUES (1)');\n"
        )
        _, relations = extract_symbols_and_relations(content, "php")
        tables = [item.target for item in relations if item.relation == "uses_table"]
        self.assertIn("pages", tables)
        self.assertIn("users", tables)
        self.assertIn("audit_log", tables)
