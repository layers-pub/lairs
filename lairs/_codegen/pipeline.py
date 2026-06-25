"""Top-level codegen pipeline.

Drives lexicon JSON through panproto parsing, the Schema-to-spec mapping, and
module emission, writing one committed module per ``pub.layers.*`` namespace
into :mod:`lairs.records._generated`. Cross-namespace embeds (for example
``annotation`` embedding ``defs#anchor``) are resolved to imports so each module
type-checks in isolation. The ``check`` entry powers the ``lairs gen --check``
drift gate.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

import panproto as pp

from lairs._codegen.emit import emit_module
from lairs._codegen.manifest import load_manifest
from lairs._codegen.schema_to_spec import schema_to_specs

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from lairs._codegen.schema_to_spec import FieldSpec, ModelSpec
    from lairs._types import JsonValue

__all__ = ["check", "generate", "namespace_specs"]

_MANIFEST_NAME = "MANIFEST.toml"


def generate(lexicon_root: Path, out_root: Path) -> list[Path]:
    """Generate model modules from a vendored lexicon tree.

    Parameters
    ----------
    lexicon_root : pathlib.Path
        The root of the vendored lexicon tree (the directory that contains the
        ``pub`` package and ``MANIFEST.toml``).
    out_root : pathlib.Path
        The output directory for emitted modules, normally
        ``lairs/records/_generated``.

    Returns
    -------
    list of pathlib.Path
        The paths of the generated module files, in stable order.
    """
    out_root.mkdir(parents=True, exist_ok=True)
    rendered = _render_all(lexicon_root)
    written: list[Path] = []
    for namespace, text in sorted(rendered.items()):
        path = out_root / f"{namespace}.py"
        path.write_text(text, encoding="utf-8")
        written.append(path)
    _write_generated_init(out_root, sorted(rendered))
    _prune_orphans(out_root, set(rendered))
    _canonicalise(out_root)
    return sorted([*written, out_root / "__init__.py"])


def _prune_orphans(out_root: Path, namespaces: set[str]) -> None:
    """Delete generated modules for namespaces no longer rendered.

    Removing a lexicon namespace upstream must not leave an orphan module
    behind: the stale ``<namespace>.py`` would still be importable and would no
    longer reflect any lexicon. Only freshly rendered namespace modules and the
    package ``__init__`` survive; every other ``*.py`` (including a namespace
    that was dropped) is removed.
    """
    keep = {f"{namespace}.py" for namespace in namespaces}
    keep.add("__init__.py")
    for path in out_root.glob("*.py"):
        if path.name not in keep:
            path.unlink()


def check(lexicon_root: Path, out_root: Path) -> bool:
    """Check whether committed modules match a fresh generation.

    Parameters
    ----------
    lexicon_root : pathlib.Path
        The root of the vendored lexicon tree.
    out_root : pathlib.Path
        The directory holding the committed generated modules.

    Returns
    -------
    bool
        ``True`` if the committed ``*.py`` set is exactly the freshly generated
        set and every committed module (and the package ``__init__``) is
        byte-identical to its fresh counterpart. An orphan committed module with
        no fresh counterpart (left behind after a lexicon namespace was removed
        upstream) counts as drift and returns ``False``.
    """
    with tempfile.TemporaryDirectory() as tmp:
        fresh_root = Path(tmp)
        generate(lexicon_root, fresh_root)
        fresh_names = {path.name for path in fresh_root.glob("*.py")}
        committed_names = {path.name for path in out_root.glob("*.py")}
        if committed_names != fresh_names:
            return False
        for fresh in sorted(fresh_root.glob("*.py")):
            committed = out_root / fresh.name
            if committed.read_text(encoding="utf-8") != fresh.read_text(
                encoding="utf-8"
            ):
                return False
    return True


def namespace_specs(lexicon_root: Path) -> dict[str, list[ModelSpec]]:
    """Return the codegen specs for each namespace, for inspection and tests.

    Parameters
    ----------
    lexicon_root : pathlib.Path
        The root of the vendored lexicon tree.

    Returns
    -------
    dict of str to list of lairs._codegen.schema_to_spec.ModelSpec
        A mapping of namespace name to its specs.
    """
    grouped: dict[str, list[ModelSpec]] = defaultdict(list)
    for document in _load_documents(lexicon_root):
        schema = pp.parse_atproto_lexicon(document)
        namespace = _namespace_of(_document_id(document))
        grouped[namespace].extend(schema_to_specs(schema, document))
    # Drop namespaces that contribute no models (e.g. method-only namespaces
    # such as `integration`, whose lexicons are all queries) so the generated
    # tree carries no empty modules.
    return {namespace: specs for namespace, specs in grouped.items() if specs}


def _canonicalise(out_root: Path) -> None:
    """Format and lint-fix the generated modules into their canonical form.

    The emitted text is close to compliant, but ``ruff format`` reflows long
    container literals and normalises quoting and blank lines, and a follow-up
    ``ruff check --fix`` drops any now-redundant suppression. Running format,
    then fix, then format again converges to a stable, lint-clean form so the
    committed modules and a fresh generation are byte-identical, which is what
    the ``lairs gen --check`` drift gate compares.

    Parameters
    ----------
    out_root : pathlib.Path
        The directory holding the freshly emitted modules.
    """
    ruff = shutil.which("ruff")
    base: list[str] = [ruff] if ruff is not None else ["uv", "run", "ruff"]
    target = str(out_root)
    _run_ruff([*base, "format", target])
    _run_ruff([*base, "check", "--fix", "--quiet", target])
    _run_ruff([*base, "format", target])


def _run_ruff(command: list[str]) -> None:
    """Run a ruff command, raising on a hard failure.

    A non-zero exit from ``ruff check`` because findings remain is tolerated
    (the follow-up format pass resolves the formatting-driven ones); only a
    failure to launch ruff at all is fatal.
    """
    try:
        subprocess.run(command, check=False, capture_output=True)  # noqa: S603
    except FileNotFoundError as error:
        msg = "ruff is required to canonicalise generated modules"
        raise RuntimeError(msg) from error


def _render_all(lexicon_root: Path) -> dict[str, str]:
    """Render every namespace module to source text, keyed by namespace."""
    manifest = load_manifest(lexicon_root / _MANIFEST_NAME)
    grouped = namespace_specs(lexicon_root)
    name_to_namespace = _name_index(grouped)
    rendered: dict[str, str] = {}
    for namespace, specs in grouped.items():
        text = emit_module(specs, manifest_hash=manifest.lexicon_tree_hash)
        imports = _cross_namespace_imports(namespace, specs, name_to_namespace)
        rendered[namespace] = _inject_imports(text, imports)
    return rendered


def _name_index(grouped: Mapping[str, Sequence[ModelSpec]]) -> dict[str, str]:
    """Return a mapping of every emitted class name to its namespace."""
    index: dict[str, str] = {}
    for namespace, specs in grouped.items():
        for spec in specs:
            index[spec.name] = namespace
            for variant in spec.variants:
                index[variant.class_name] = namespace
    return index


def _cross_namespace_imports(
    namespace: str,
    specs: Sequence[ModelSpec],
    name_to_namespace: Mapping[str, str],
) -> dict[str, list[str]]:
    """Return the imports a namespace module needs from sibling modules.

    The result maps a module name to the sorted class names it must import. Only
    embed and union targets that live in another generated namespace are
    imported; same-namespace targets resolve in-module.
    """
    local = {spec.name for spec in specs}
    needed: dict[str, set[str]] = defaultdict(set)
    for spec in specs:
        for field in spec.fields:
            target = _field_target(field)
            if target is None or target in local:
                continue
            owner = name_to_namespace.get(target)
            if owner is not None and owner != namespace:
                needed[owner].add(target)
    return {module: sorted(names) for module, names in sorted(needed.items())}


def _field_target(field: FieldSpec) -> str | None:
    """Return the model a field embeds or unions over, recursing into arrays."""
    if field.type_kind in {"embed", "union"}:
        return field.target
    if field.type_kind == "array" and field.item is not None:
        return _field_target(field.item)
    return None


def _inject_imports(text: str, imports: Mapping[str, Sequence[str]]) -> str:
    """Insert sibling-namespace imports after the didactic import line.

    The emitter always writes ``import didactic.api as dx`` on its own line; the
    sibling imports are inserted directly after it so the import block stays
    grouped and ruff-formatted. Sibling embed targets are used only in
    annotations but must stay at runtime for didactic, so a ``TC001``
    suppression is added to the file-level directive.
    """
    if not imports:
        return text
    lines = _ensure_tc001(text.split("\n"))
    anchor = "import didactic.api as dx"
    try:
        index = lines.index(anchor)
    except ValueError:
        return "\n".join(lines)
    additions: list[str] = []
    for module, names in imports.items():
        joined = ", ".join(names)
        additions.append(f"from lairs.records._generated.{module} import {joined}")
    lines[index + 1 : index + 1] = additions
    return "\n".join(lines)


_NOQA_PREFIX = "# ruff: noqa: "


def _ensure_tc001(lines: list[str]) -> list[str]:
    """Ensure the file-level ruff directive lists ``TC001``.

    The directive is added (or extended) right after the two-line generated
    header when sibling embed imports are injected.
    """
    for index, line in enumerate(lines):
        if line.startswith(_NOQA_PREFIX):
            codes = {code.strip() for code in line[len(_NOQA_PREFIX) :].split(",")}
            codes.add("TC001")
            lines[index] = _NOQA_PREFIX + ", ".join(sorted(codes))
            return lines
    # no directive yet: insert one after the header hash line (second line)
    header_lines = 2
    lines.insert(header_lines, f"{_NOQA_PREFIX}TC001")
    return lines


def _write_generated_init(out_root: Path, namespaces: Sequence[str]) -> None:
    """Write the generated package ``__init__`` re-exporting every module."""
    (out_root / "__init__.py").write_text(
        _generated_init_text(namespaces),
        encoding="utf-8",
    )


def _generated_init_text(namespaces: Sequence[str]) -> str:
    """Return the source text for the generated package ``__init__``."""
    ordered = sorted(namespaces)
    lines = [
        "# generated by lairs gen; do not edit",
        '"""Generated record models, one module per ``pub.layers.*`` namespace.',
        "",
        "This package is emitted by ``lairs gen`` from the vendored lexicons. Each",
        "module mirrors one lexicon namespace; nothing here is hand-authored.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
    ]
    lines.extend(
        f"from lairs.records._generated import {namespace}" for namespace in ordered
    )
    lines.append("")
    quoted = ",\n    ".join(f'"{namespace}"' for namespace in ordered)
    if ordered:
        lines.append(f"__all__ = [\n    {quoted},\n]")
    else:
        lines.append("__all__: list[str] = []")
    return "\n".join(lines) + "\n"


def _load_documents(lexicon_root: Path) -> list[dict[str, JsonValue]]:
    """Load every generatable lexicon JSON document under the tree, in stable order.

    Permission-set lexicons (OAuth scope definitions) are skipped: they are not
    record, query, or object schemas, and the ATProto lexicon parser does not
    model them. This mirrors the Rust codegen, which skips unsupported def kinds
    rather than failing on them.
    """
    pub = lexicon_root / "pub"
    documents: list[dict[str, JsonValue]] = []
    for path in sorted(pub.rglob("*.json")):
        with path.open(encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict) and not _is_unsupported_lexicon(loaded):
            documents.append(loaded)
    return documents


# Main-definition kinds the codegen does not model; their lexicons are skipped.
_UNSUPPORTED_MAIN_TYPES = frozenset({"permission-set"})


def _is_unsupported_lexicon(document: Mapping[str, JsonValue]) -> bool:
    """Return whether the codegen skips this lexicon (e.g. a permission set)."""
    defs = document.get("defs")
    if not isinstance(defs, dict):
        return False
    main = defs.get("main")
    if not isinstance(main, dict):
        return False
    return main.get("type") in _UNSUPPORTED_MAIN_TYPES


def _document_id(document: Mapping[str, JsonValue]) -> str:
    """Return the lexicon namespace identifier of a document."""
    value = document.get("id")
    return value if isinstance(value, str) else ""


def _namespace_of(nsid: str) -> str:
    """Return the namespace module name for a lexicon namespace identifier.

    ``pub.layers.defs`` -> ``defs``; ``pub.layers.expression.expression`` ->
    ``expression``; the third dotted component is the namespace.
    """
    parts = nsid.split(".")
    minimum_record_parts = 4
    if len(parts) >= minimum_record_parts:
        return parts[2]
    return parts[-1]
