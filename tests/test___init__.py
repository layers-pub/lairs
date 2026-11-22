"""Public-package and executable-documentation tests for lairs."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import didactic.api as dx
import httpx
import pytest

import lairs
from lairs.integrations.registry import UnknownAdapterError
from lairs.records.blobref import BlobRef

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from conftest import DocumentationConfig, DocumentationRuntime

_PROJECT_ROOT = Path(__file__).parents[1]
_EXAMPLE_LANGUAGES = {
    "python": "python",
    "python3": "python",
    "py": "python",
    "bash": "bash",
    "shell": "bash",
    "sh": "bash",
}
_EXAMPLE_FENCE = re.compile(r"^([ \t]*)(`{3,}|~{3,})\s*([\w+-]*)[^\n]*$")
_EXAMPLE_DIRECTIVE = "<!-- lairs-test:"


class _DocumentationDirective(dx.Model):
    """The explicit execution policy attached to a documentation fence."""

    mode: str = dx.field(default="invalid", description="run, check, or skip")
    fixture: str = dx.field(default="core", description="fixture profile")
    requires: tuple[str, ...] = dx.field(
        default_factory=tuple, description="optional import modules"
    )
    reason: str = dx.field(default="", description="why code is not executed")
    error: str | None = dx.field(default=None, description="invalid policy diagnostic")


class _DocumentationBlock(dx.Model):
    """A fenced program with its document location and execution policy."""

    path: str = dx.field(description="project-relative document path")
    line: int = dx.field(description="one-based first source line")
    language: str = dx.field(description="python or bash")
    code: str = dx.field(description="fenced program source")
    directive: dx.Embed[_DocumentationDirective] = dx.field(
        description="explicit execution policy"
    )


class _DocumentationCase(dx.Model):
    """One fence and the earlier Python programs that establish its context."""

    current: dx.Embed[_DocumentationBlock] = dx.field(description="the tested fence")
    previous: tuple[dx.Embed[_DocumentationBlock], ...] = dx.field(
        default_factory=tuple, description="earlier executable Python fences"
    )


def _documentation_options(words: list[str]) -> dict[str, str]:
    """Validate directive keys and require a reason for nonexecution."""
    if not words or words[0] not in {"run", "check", "skip"}:
        msg = "directive mode must be run, check, or skip"
        raise ValueError(msg)
    options: dict[str, str] = {}
    for word in words[1:]:
        key, separator, value = word.partition("=")
        if not separator or key not in {"fixture", "requires", "reason"}:
            msg = f"unknown directive option: {word}"
            raise ValueError(msg)
        if key in options or not value:
            msg = f"empty or repeated option: {key}"
            raise ValueError(msg)
        options[key] = value
    if words[0] != "run" and not options.get("reason"):
        msg = "check and skip require a reason"
        raise ValueError(msg)
    requires = tuple(options["requires"].split(",")) if "requires" in options else ()
    if any(
        re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", name) is None
        for name in requires
    ):
        msg = "requires must contain import module names"
        raise ValueError(msg)
    return options


def _documentation_directive(line: str) -> _DocumentationDirective:
    """Parse the required comment without inferring a policy from the code."""
    stripped = line.strip()
    if not stripped.startswith(_EXAMPLE_DIRECTIVE) or not stripped.endswith("-->"):
        return _DocumentationDirective(error="missing immediate lairs-test directive")
    try:
        words = shlex.split(stripped[len(_EXAMPLE_DIRECTIVE) : -3])
        options = _documentation_options(words)
        requires = (
            tuple(options["requires"].split(",")) if "requires" in options else ()
        )
    except ValueError as exc:
        return _DocumentationDirective(error=str(exc))
    return _DocumentationDirective(
        mode=words[0],
        fixture=options.get("fixture", "core"),
        requires=requires,
        reason=options.get("reason", ""),
    )


def _documentation_fence_end(lines: list[str], start: int, marker: str) -> int:
    """Find a matching closing fence, including longer Markdown delimiters."""
    for index in range(start, len(lines)):
        candidate = lines[index].strip()
        if len(candidate) >= len(marker) and set(candidate) == {marker[0]}:
            return index
    return len(lines)


def _documentation_blocks(path: str, text: str) -> tuple[_DocumentationBlock, ...]:
    """Discover all supported code fences, including unclassified programs."""
    lines = text.splitlines()
    blocks: list[_DocumentationBlock] = []
    index = 0
    while index < len(lines):
        match = _EXAMPLE_FENCE.fullmatch(lines[index])
        if match is None:
            index += 1
            continue
        indent, marker, label = match.groups()
        end = _documentation_fence_end(lines, index + 1, marker)
        language = _EXAMPLE_LANGUAGES.get(label.lower())
        if language is not None:
            directive = _documentation_directive(lines[index - 1] if index else "")
            if end == len(lines):
                directive = _DocumentationDirective(
                    error="unclosed documentation fence"
                )
            code = (
                "\n".join(line.removeprefix(indent) for line in lines[index + 1 : end])
                + "\n"
            )
            blocks.append(
                _DocumentationBlock(
                    path=path,
                    line=index + 2,
                    language=language,
                    code=code,
                    directive=directive,
                )
            )
        index = end + 1
    return tuple(blocks)


def _documentation_cases() -> tuple[_DocumentationCase, ...]:
    """Collect README and documentation examples on every pytest invocation."""
    cases: list[_DocumentationCase] = []
    paths = (
        _PROJECT_ROOT / "README.md",
        *sorted((_PROJECT_ROOT / "docs").rglob("*.md")),
    )
    for path in paths:
        previous: list[_DocumentationBlock] = []
        for block in _documentation_blocks(
            path.relative_to(_PROJECT_ROOT).as_posix(), path.read_text()
        ):
            cases.append(_DocumentationCase(current=block, previous=tuple(previous)))
            if block.language == "python" and block.directive.mode == "run":
                previous.append(block)
    return tuple(cases)


def _documentation_integration(case: _DocumentationCase) -> bool:
    """Require Docker only for cases that actually execute a live-write block."""
    if case.current.language != "python" or case.current.directive.mode != "run":
        return False
    return any(
        block.directive.fixture == "authoring-pds"
        for block in (*case.previous, case.current)
        if block.directive.mode == "run"
    )


def _documentation_missing(block: _DocumentationBlock) -> tuple[str, ...]:
    """Report missing optional imports without skipping unrelated examples."""
    missing: list[str] = []
    for name in block.directive.requires:
        try:
            available = importlib.util.find_spec(name) is not None
        except ImportError, ValueError:
            available = False
        if not available:
            missing.append(name)
    return tuple(missing)


def _documentation_shell_commands(code: str) -> None:
    """Limit executable shell examples to finite, read-only lairs commands."""
    for line in code.splitlines():
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        words = list(lexer)
        if not words:
            continue
        if words == ["lairs", "gen", "--check"]:
            continue
        if words == ["lairs", "--help"]:
            continue
        if (
            len(words) == 3
            and words[0] == "lairs"
            and words[2] == "--help"
            and re.fullmatch(r"[a-z][a-z-]*", words[1])
        ):
            continue
        msg = "executable shell examples must be lairs help or gen --check commands"
        raise ValueError(msg)


def _documentation_environment() -> dict[str, str]:
    """Use the test interpreter's tools while keeping shell commands offline."""
    environment = dict(os.environ)
    environment["PATH"] = os.pathsep.join(
        (str(Path(sys.executable).parent), environment.get("PATH", ""))
    )
    environment["PYTHONPATH"] = str(_PROJECT_ROOT)
    environment["UV_OFFLINE"] = "1"
    environment["NO_PROXY"] = "*"
    environment.pop("BASH_ENV", None)
    environment.pop("ENV", None)
    return environment


def _run_documentation_python(
    case: _DocumentationCase, config: DocumentationConfig
) -> subprocess.CompletedProcess[str]:
    """Execute actual document code in a fresh interpreter and working tree."""
    directory = Path(config.work_dir)
    config_path = directory / "documentation-config.json"
    config_path.write_text(config.model_dump_json())
    blocks = [
        {
            "path": str(_PROJECT_ROOT / block.path),
            "line": block.line,
            "code": block.code,
            "fixture": block.directive.fixture,
        }
        for block in (*case.previous, case.current)
        if not _documentation_missing(block)
    ]
    program = directory / "documentation-example.py"
    program.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        f"sys.path[:0] = {[str(_PROJECT_ROOT), str(_PROJECT_ROOT / 'tests')]!r}\n"
        "from conftest import DocumentationConfig, documentation_runtime\n"
        "_lairs_config = DocumentationConfig.model_validate_json(\n"
        f"    Path({str(config_path)!r}).read_text()\n"
        ")\n"
        f"_lairs_blocks = json.loads({json.dumps(blocks)!r})\n"
        "with documentation_runtime(_lairs_config) as _lairs_runtime:\n"
        "    for _lairs_block in _lairs_blocks:\n"
        "        globals().update(_lairs_runtime.setup(_lairs_block['fixture']))\n"
        "        _lairs_source = '\\n' * (_lairs_block['line'] - 1)\n"
        "        _lairs_source += _lairs_block['code']\n"
        "        _lairs_compiled = compile(\n"
        "            _lairs_source, _lairs_block['path'], 'exec'\n"
        "        )\n"
        "        exec(_lairs_compiled, globals())\n"
    )
    return subprocess.run(  # noqa: S603
        [sys.executable, "-I", str(program)],
        cwd=directory,
        env=_documentation_environment(),
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )


@pytest.mark.documentation
@pytest.mark.parametrize(
    "example",
    [
        pytest.param(
            case,
            id=f"{case.current.path}:{case.current.line}-{case.current.directive.mode}",
            marks=pytest.mark.integration if _documentation_integration(case) else (),
        )
        for case in _documentation_cases()
    ],
)
def test_documentation_examples(
    example: _DocumentationCase,
    documentation_config_factory: Callable[[str, bool], DocumentationConfig],
    tmp_path: Path,
) -> None:
    """Execute annotated examples and reject missing or ambiguous policies."""
    block = example.current
    assert block.directive.error is None, (
        f"{block.path}:{block.line}: {block.directive.error}"
    )
    if block.directive.mode == "skip":
        pytest.skip(block.directive.reason)
    if block.language == "python":
        compile("\n" * (block.line - 1) + block.code, block.path, "exec")
        if block.directive.mode == "check":
            return
        missing = _documentation_missing(block)
        if missing:
            pytest.skip(f"optional example dependencies missing: {', '.join(missing)}")
        config = documentation_config_factory(
            block.path, _documentation_integration(example)
        )
        completed = _run_documentation_python(example, config)
    else:
        bash = shutil.which("bash")
        if bash is None:
            pytest.skip("bash is unavailable")
        arguments = [bash, "-n"]
        if block.directive.mode == "run":
            _documentation_shell_commands(block.code)
            arguments = [bash, "-euo", "pipefail"]
        completed = subprocess.run(  # noqa: S603
            arguments,
            input=block.code,
            cwd=_PROJECT_ROOT
            if block.directive.fixture == "codegen-check"
            and block.directive.mode == "run"
            else tmp_path,
            env=_documentation_environment(),
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    assert completed.returncode == 0, (
        f"{block.path}:{block.line}\n{completed.stdout}\n{completed.stderr}"
    )


@pytest.mark.documentation
@pytest.mark.parametrize(
    "directive",
    [
        "",
        "<!-- lairs-test: check -->",
        "<!-- lairs-test: skip -->",
        "<!-- lairs-test: run fixture=core fixture=store -->",
        "<!-- lairs-test: run unknown=value -->",
        '<!-- lairs-test: run reason="unterminated -->',
    ],
)
def test_documentation_rejects_missing_or_invalid_policies(directive: str) -> None:
    assert _documentation_directive(directive).error is not None


@pytest.mark.documentation
def test_documentation_parser_preserves_source_locations_and_language() -> None:
    source = (
        "\n<!-- lairs-test: run fixture=store requires=pyarrow -->\n"
        "```python\nx = 1\n```\n"
    )
    blocks = _documentation_blocks("example.md", source)
    assert len(blocks) == 1
    assert blocks[0].line == 4
    assert blocks[0].language == "python"
    assert blocks[0].code == "x = 1\n"
    assert blocks[0].directive.fixture == "store"
    assert blocks[0].directive.requires == ("pyarrow",)
    assert blocks[0].directive.error is None


@pytest.mark.documentation
def test_documentation_parser_rejects_unclosed_fences() -> None:
    source = "<!-- lairs-test: run -->\n```python\nx = 1\n"
    assert _documentation_blocks("example.md", source)[0].directive.error


@pytest.mark.documentation
@pytest.mark.parametrize(
    "code", ["git push", "curl example.org", "lairs --help; git push"]
)
def test_documentation_shell_run_rejects_write_or_network_commands(code: str) -> None:
    with pytest.raises(ValueError, match=r"read-only|help or gen"):
        _documentation_shell_commands(code)


@pytest.mark.documentation
def test_documentation_runtime_rejects_unrecorded_network_and_fixture_names(
    documentation_config_factory: Callable[[str, bool], DocumentationConfig],
    documentation_runtime_factory: Callable[
        [DocumentationConfig], AbstractContextManager[DocumentationRuntime]
    ],
) -> None:
    needs_pds = False
    config = documentation_config_factory("fixture-boundary-test.md", needs_pds)
    original_transport = httpx.HTTPTransport.handle_request
    with (
        patch.object(
            httpx.HTTPTransport,
            "handle_request",
            side_effect=AssertionError("unrecorded HTTP reached the real transport"),
        ),
        patch(
            "socket.getaddrinfo",
            side_effect=AssertionError("external DNS reached the system resolver"),
        ),
        patch.object(
            socket.socket,
            "connect",
            side_effect=AssertionError("external socket reached the operating system"),
        ),
        documentation_runtime_factory(config) as runtime,
    ):
        with pytest.raises(ValueError, match="unknown documentation fixture"):
            runtime.setup("not-a-fixture")
        with pytest.raises(RuntimeError, match="unexpected external request"):
            httpx.get("https://unrecorded.invalid", timeout=1.0)
        with pytest.raises(RuntimeError, match="external DNS is disabled"):
            socket.getaddrinfo("unrecorded.invalid", 443)
        with (
            socket.socket() as connection,
            pytest.raises(RuntimeError, match="external sockets are disabled"),
        ):
            connection.connect(("192.0.2.1", 443))
    assert httpx.HTTPTransport.handle_request is original_transport


def test_version_matches_distribution_metadata() -> None:
    assert isinstance(lairs.__version__, str)
    try:
        installed = distribution_version("lairs")
    except PackageNotFoundError:
        installed = None
    if installed is not None:
        # __version__ is derived from the installed distribution metadata, so
        # the two can never silently diverge.
        assert lairs.__version__ == installed
    else:
        # In a source tree with no installed distribution the literal fallback
        # is the single source of truth for the release version.
        assert lairs.__version__ == lairs._FALLBACK_VERSION


def test_fallback_version_is_release_target() -> None:
    # The fallback literal is the release version and must stay in step with
    # pyproject.toml's version field.
    assert lairs._FALLBACK_VERSION == "0.10.3"
    parts = lairs._FALLBACK_VERSION.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)


def test_public_surface() -> None:
    assert set(lairs.__all__) == {
        "BlobRef",
        "Corpus",
        "DatasetFilter",
        "DatasetSummary",
        "RepoTableOfContents",
        "Session",
        "__version__",
        "authed_client",
        "codec",
        "conllu",
        "discover_datasets",
        "exporter",
        "knowledge_base",
        "list_datasets",
        "load_corpus",
        "login",
        "table_of_contents",
    }


def test_blobref_reexport() -> None:
    assert lairs.BlobRef is BlobRef


def test_codec_lookup_unknown() -> None:
    with pytest.raises(UnknownAdapterError):
        lairs.codec("definitely-not-registered-xyz")
    with pytest.raises(UnknownAdapterError):
        lairs.exporter("definitely-not-registered-xyz")
    with pytest.raises(UnknownAdapterError):
        lairs.knowledge_base("definitely-not-registered-xyz")
