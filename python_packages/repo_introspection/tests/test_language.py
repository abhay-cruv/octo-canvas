from repo_introspection.language import detect_primary_language


def test_returns_none_for_empty_set() -> None:
    assert detect_primary_language(set()) is None


def test_picks_typescript_in_ts_repo() -> None:
    paths = {"src/index.ts", "src/app.tsx", "src/lib.ts", "README.md"}
    assert detect_primary_language(paths) == "TypeScript"


def test_picks_python_in_py_repo() -> None:
    paths = {"app/main.py", "app/util.py", "tests/test_main.py"}
    assert detect_primary_language(paths) == "Python"


def test_typescript_wins_over_javascript_when_more_files() -> None:
    paths = {"a.ts", "b.ts", "c.ts", "x.js"}
    assert detect_primary_language(paths) == "TypeScript"


def test_alphabetical_tiebreak() -> None:
    paths = {"a.py", "b.rs"}
    # Python and Rust tie at 1 each → alphabetical → "Python"
    assert detect_primary_language(paths) == "Python"


def test_ignores_node_modules() -> None:
    paths = {"src/index.ts"} | {f"node_modules/foo/{i}.js" for i in range(50)}
    assert detect_primary_language(paths) == "TypeScript"


def test_ignores_unknown_extensions() -> None:
    paths = {"README.md", "LICENSE", ".gitignore"}
    assert detect_primary_language(paths) is None


def test_ignores_dist_and_venv() -> None:
    paths = {
        "src/main.py",
        "dist/bundle.js",
        "dist/bundle.js.map",
        ".venv/lib/python3.12/site-packages/foo.py",
    }
    assert detect_primary_language(paths) == "Python"
