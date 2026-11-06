from __future__ import annotations

import ast
import inspect
import re
import textwrap
import tokenize
from importlib import import_module
from pathlib import Path
from typing import cast

from modelscape.core.files import parse_yaml
from modelscape.spec import Spec

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "modelscape"

ALLOWED: dict[str, set[str]] = {
    "core": {"core"},
    "grammar": {"core", "grammar"},
    "space": {"core", "grammar"},
    "targets": {"core", "targets"},
    "measures": {"core", "targets", "measures"},
    "storage": {"core", "storage"},
    "analysis": {"core", "storage", "analysis"},
    "execution": {
        "core",
        "grammar",
        "space",
        "targets",
        "measures",
        "storage",
        "analysis",
        "execution",
    },
}
ALLOWED["template"] = {"core", "grammar", "space", "template"}
ALLOWED["lexicons"] = ALLOWED["template"] | {"lexicons"}
ALLOWED["report"] = {"core", "storage", "analysis", "report"}
ALLOWED["scenario"] = ALLOWED["execution"] | {"report", "scenario"}
ALLOWED["spec"] = ALLOWED["scenario"] | {"template", "lexicons", "spec"}
ALLOWED["builder"] = ALLOWED["spec"] | {"scenarios", "builder"}
ALLOWED["scenarios"] = ALLOWED["spec"] | {"scenarios"}
ALLOWED["gate"] = ALLOWED["scenario"] | {"gate"}
ALLOWED["cli"] = ALLOWED["scenarios"] | {"gate", "page", "cli"}
ALLOWED["page"] = ALLOWED["scenario"] | {"page"}
ALLOWED["__main__"] = {"cli"}

PROVIDER_SDKS = {
    "anthropic": {"anthropic_messages.py"},
    "azure": {"azure_openai.py"},
    "boto3": {"bedrock.py"},
    "google": {"google_genai.py"},
    "openai": {"openai_responses.py", "azure_openai.py"},
    "types_boto3_bedrock_runtime": {"bedrock.py"},
}
OPTIONAL = {sdk: {"targets"} for sdk in PROVIDER_SDKS} | {
    "anywidget": {"builder"},
    "traitlets": {"builder"},
}
FENCE = r"^( *)```{}\n(.*?)^\1```"
PUBLIC = [
    import_module(f"modelscape{suffix}")
    for suffix in ("", ".analysis", ".measures", ".storage", ".targets")
]


def layer(path: Path) -> str:
    relative = path.relative_to(PACKAGE)
    return relative.parts[0].removesuffix(".py")


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def modules() -> list[Path]:
    return [
        path
        for path in PACKAGE.rglob("*.py")
        if path.parent != PACKAGE or path.name != "__init__.py"
    ]


def test_layers_depend_only_downward() -> None:
    violations = [
        f"{path.relative_to(PACKAGE)} imports {name}"
        for path in modules()
        for name in imports(path)
        if name.startswith("modelscape.")
        and name.split(".")[1].removesuffix(".py") not in ALLOWED[layer(path)]
    ]
    assert violations == []


def test_optional_dependencies_stay_isolated() -> None:
    for path in modules():
        for name in imports(path):
            root = name.split(".")[0]
            if root in OPTIONAL:
                assert layer(path) in OPTIONAL[root], f"{path} imports {name}"
    for sdk, allowed in PROVIDER_SDKS.items():
        users = {
            path.name
            for path in modules()
            if any(name.split(".")[0] == sdk for name in imports(path))
        }
        assert users == allowed, sdk


def test_source_and_tests_contain_no_comments() -> None:
    commented = [
        f"{path.relative_to(ROOT)}:{token.start[0]}"
        for folder in ("src", "tests")
        for path in (ROOT / folder).rglob("*.py")
        for token in tokens(path)
        if token.type == tokenize.COMMENT
    ]
    assert commented == []


def tokens(path: Path) -> list[tokenize.TokenInfo]:
    with path.open("rb") as handle:
        return list(tokenize.tokenize(handle.readline))


def test_text_files_are_read_and_written_as_utf8() -> None:
    unspecified = [
        f"{path.relative_to(ROOT)}:{node.lineno}"
        for folder in ("src", "tests")
        for path in (ROOT / folder).rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call) and opens_text(node)
        if not any(keyword.arg == "encoding" for keyword in node.keywords)
    ]
    assert unspecified == []


def opens_text(call: ast.Call) -> bool:
    name = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")
    if name in {"read_text", "write_text"}:
        return True
    modes = [argument for argument in call.args if isinstance(argument, ast.Constant)]
    return name == "open" and not any("b" in str(mode.value) for mode in modes)


def test_configuration_files_contain_no_comments() -> None:
    files = [ROOT / "pyproject.toml", *(ROOT / ".github").rglob("*.yml")]
    commented = [
        f"{path.relative_to(ROOT)}:{number}"
        for path in files
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if line.lstrip().startswith("#")
    ]
    assert commented == []


def documented(language: str) -> list[tuple[str, str]]:
    pages = [ROOT / "README.md", *(ROOT / "docs").rglob("*.md"), *PACKAGE.rglob("SKILL.md")]
    fence = re.compile(FENCE.format(language), re.DOTALL | re.MULTILINE)
    return [
        (f"{page.relative_to(ROOT)}:{index}", textwrap.dedent(found.group(2)))
        for page in pages
        for index, found in enumerate(fence.finditer(page.read_text(encoding="utf-8")))
    ]


def test_documented_python_compiles() -> None:
    blocks = documented("python")
    assert blocks
    for name, source in blocks:
        compile(source, name, "exec")


def test_documented_specs_compile() -> None:
    documents: list[object] = [parse_yaml(block) for _, block in documented("yaml")]
    mappings = [cast(dict[str, object], data) for data in documents if isinstance(data, dict)]
    specs = [data for data in mappings if "prompt" in data]
    assert len(specs) >= 4
    for data in specs:
        assert "all checked" in Spec.of(data).scenario().describe()


def test_page_sources_contain_no_comments() -> None:
    commented = [
        f"{path.relative_to(ROOT)}:{number}"
        for path in sorted([*(ROOT / "page").glob("*.*"), *(ROOT / "page" / "src").rglob("*")])
        if path.suffix in {".ts", ".js", ".css"} or path.name == "tsconfig.json"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if line.lstrip().startswith(("//", "/*", "*"))
    ]
    assert commented == []


def test_public_api_is_documented() -> None:
    undocumented = [
        f"{module.__name__}.{name}"
        for module in PUBLIC
        for name in module.__all__
        for item in [getattr(module, name)]
        if (inspect.isclass(item) and not vars(item).get("__doc__"))
        or (inspect.isfunction(item) and not item.__doc__)
    ]
    assert undocumented == []
