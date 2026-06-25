"""Tests for the all-data-type Browse surface.

Three layers: the record-type registry (a drift guard against the authoritative
publish map), the :class:`RepoBrowser` data layer and the type-aware renderers
over a seeded multi-type repository, and Pilot-driven tests of the Browse pane
wired into the app.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Input, Markdown, TabbedContent, Tree

if TYPE_CHECKING:
    from collections.abc import Mapping

    from textual.widgets.tree import TreeNode

    from lairs._types import JsonValue

import lairs.tui as lairs_tui
from lairs.author.publish import _RECORD_MODELS as PUBLISH_MODELS
from lairs.tui import QueryEngine, _materialize_for_query
from lairs.tui.app import LairsApp
from lairs.tui.browse import BrowseError, RepoBrowser, materialize_repo
from lairs.tui.registry import RECORD_MODELS, label_of, namespace_of
from lairs.tui.screens.browse import BrowsePane
from lairs.tui.views import (
    _ITEM_INDEX,
    _item_index,
    _render_generic,
    _span_text,
    columns_for,
    record_views,
    render_record,
    render_view,
    summarize,
    view_modes,
)

_ONTOLOGY = "pub.layers.ontology.ontology"
_TYPEDEF = "pub.layers.ontology.typeDef"
_EXPERIMENT = "pub.layers.judgment.experimentDef"
_JUDGMENT_SET = "pub.layers.judgment.judgmentSet"
_AGREEMENT = "pub.layers.judgment.agreementReport"
_EDGE_SET = "pub.layers.graph.graphEdgeSet"
_COLLECTION = "pub.layers.resource.collection"
_CORPUS = "pub.layers.corpus.corpus"
_EXPRESSION = "pub.layers.expression.expression"
_LAYER = "pub.layers.annotation.annotationLayer"
_MEDIA = "pub.layers.media.media"
_PERSONA = "pub.layers.persona.persona"
_EPRINT = "pub.layers.eprint.eprint"
_SEGMENTATION = "pub.layers.segmentation.segmentation"


def _first(browser: RepoBrowser, nsid: str) -> str:
    """Render the first record of a collection to Markdown."""
    uri, raw = browser.records_raw(nsid)[0]
    return render_record(browser, nsid, uri, raw)


def _pick(
    browser: RepoBrowser, nsid: str, **match: str
) -> tuple[str, Mapping[str, JsonValue]]:
    """Return the first ``(uri, raw)`` of a collection matching field values."""
    for uri, raw in browser.records_raw(nsid):
        if all(raw.get(key) == value for key, value in match.items()):
            return uri, raw
    message = f"no {nsid} matching {match}"
    raise AssertionError(message)


# ---- registry drift guard -------------------------------------------------


def test_registry_matches_publish_map() -> None:
    """The browser registry must cover exactly the published record types."""
    assert set(RECORD_MODELS) == set(PUBLISH_MODELS)


def test_registry_classes_match_publish_map() -> None:
    """Each registered model is the class the publish map names."""
    for nsid, model in RECORD_MODELS.items():
        module_tail, class_name = PUBLISH_MODELS[nsid]
        assert model.__name__ == class_name
        assert model.__module__.rsplit(".", 1)[-1] == module_tail


def test_namespace_and_label_helpers() -> None:
    """The NSID helpers split namespace and record label."""
    assert namespace_of(_TYPEDEF) == "ontology"
    assert label_of(_TYPEDEF) == "typeDef"
    assert namespace_of("malformed") == "malformed"


# ---- RepoBrowser data layer -----------------------------------------------


def test_open_bad_path_raises(tmp_path: Path) -> None:
    """Opening a non-repository directory raises BrowseError."""
    with pytest.raises(BrowseError, match="could not open repository"):
        RepoBrowser.open(tmp_path / "absent")


def test_type_counts_lists_present_types(repo_dir: Path) -> None:
    """type_counts reports each present collection with its record count."""
    browser = RepoBrowser.open(repo_dir)
    counts = dict(browser.type_counts())
    assert counts[_EXPRESSION] == 3
    assert counts[_TYPEDEF] == 2
    assert counts[_CORPUS] == 1
    assert counts[_SEGMENTATION] == 1


def test_type_counts_orders_known_types_first(repo_dir: Path) -> None:
    """Known types appear in registry order before any unknown extras."""
    browser = RepoBrowser.open(repo_dir)
    present = [nsid for nsid, _ in browser.type_counts()]
    known_order = [nsid for nsid in RECORD_MODELS if nsid in present]
    assert present[: len(known_order)] == known_order


def test_load_returns_typed_model(repo_dir: Path) -> None:
    """Decode a record into its registered model class."""
    browser = RepoBrowser.open(repo_dir)
    uri = browser.uris_of(_CORPUS)[0]
    model = browser.load(uri)
    assert type(model) is RECORD_MODELS[_CORPUS]


def test_records_raw_and_related(repo_dir: Path) -> None:
    """records_raw returns raw JSON; related_raw filters by a field value."""
    browser = RepoBrowser.open(repo_dir)
    onto_uri = browser.uris_of(_ONTOLOGY)[0]
    type_defs = browser.related_raw(_TYPEDEF, "ontologyRef", onto_uri)
    assert len(type_defs) == 2
    kinds = {raw.get("typeKind") for _, raw in type_defs}
    assert kinds == {"relation", "entity"}


# ---- type-aware renderers -------------------------------------------------


def test_ontology_renders_type_hierarchy(repo_dir: Path) -> None:
    """The ontology view groups type definitions by kind with glosses."""
    md = _first(RepoBrowser.open(repo_dir), _ONTOLOGY)
    assert "Type hierarchy (2)" in md
    assert "nominal subject" in md
    assert "### entity" in md
    assert "### relation" in md


def test_experiment_renders_design_and_responses(repo_dir: Path) -> None:
    """The experiment view shows its design, materials, and response sets."""
    md = _first(RepoBrowser.open(repo_dir), _EXPERIMENT)
    assert "1..7" in md
    assert "1 judgment sets" in md
    assert "fleiss-kappa" in md


def test_judgment_set_renders_responses(repo_dir: Path) -> None:
    """The judgment-set Responses view lists the annotator's item responses."""
    browser = RepoBrowser.open(repo_dir)
    uri, raw = browser.records_raw(_JUDGMENT_SET)[0]
    md = render_view(browser, _JUDGMENT_SET, uri, raw, "Responses")
    assert "annotator A" in md
    assert "The quick brown fox jumps." in md
    assert "yes" in md


def test_graph_edge_set_renders_edges(repo_dir: Path) -> None:
    """The edge-set Graph view renders source -> type -> target adjacency."""
    browser = RepoBrowser.open(repo_dir)
    uri, raw = browser.records_raw(_EDGE_SET)[0]
    md = render_view(browser, _EDGE_SET, uri, raw, "Graph")
    assert "causal" in md
    assert "expression/s1" in md
    assert "expression/s2" in md


def test_collection_renders_entries(repo_dir: Path) -> None:
    """The collection view lists its entries via collection memberships."""
    md = _first(RepoBrowser.open(repo_dir), _COLLECTION)
    assert "Entries (1)" in md
    assert "run" in md


def test_corpus_renders_members_and_licensing(repo_dir: Path) -> None:
    """The corpus view shows licensing and its membership list."""
    md = _first(RepoBrowser.open(repo_dir), _CORPUS)
    assert "CC-BY-SA-4.0" in md
    assert "Members (1)" in md
    assert "expression/s1" in md


def test_token_tag_layer_renders_interlinear(repo_dir: Path) -> None:
    """A token-tag layer's Tags view aligns labels under each token."""
    browser = RepoBrowser.open(repo_dir)
    uri, raw = _pick(browser, _LAYER, subkind="pos")
    md = render_view(browser, _LAYER, uri, raw, "Tags")
    assert "DET" in md
    assert "NOUN" in md
    assert "fox" in md


def test_dependency_layer_renders_tree_and_grid(repo_dir: Path) -> None:
    """A dependency layer offers Tree and Grid views over its tokens."""
    browser = RepoBrowser.open(repo_dir)
    uri, raw = _pick(browser, _LAYER, subkind="dependency")
    modes = view_modes(browser, _LAYER, uri, raw)
    assert "Tree" in modes
    assert "Grid" in modes
    tree = render_view(browser, _LAYER, uri, raw, "Tree")
    assert "nsubj" in tree
    assert "root" in tree


def test_span_text_handles_token_anchors() -> None:
    """A token reference renders as its index; a sequence as an index range."""
    text = "The quick brown fox jumps."
    assert _span_text({"textSpan": {"byteStart": 0, "byteEnd": 3}}, text) == "The"
    assert _span_text({"tokenRef": {"tokenIndex": 2}}, text) == "token 2"
    assert (
        _span_text({"tokenRefSequence": {"tokenIndexes": [1, 2, 3]}}, text)
        == "tokens 1..3"
    )
    assert _span_text({"tokenRefSequence": {"tokenIndexes": [4]}}, text) == "token 4"
    assert _span_text({}, text) == ""


def test_expression_offers_reading_views(repo_dir: Path) -> None:
    """An annotated sentence offers Text, Grid, Tree, Layers, and Detail views."""
    browser = RepoBrowser.open(repo_dir)
    uri, raw = _pick(browser, _EXPRESSION, id="s1")
    modes = view_modes(browser, _EXPRESSION, uri, raw)
    assert modes[0] == "Text"
    for expected in ("Grid", "Tree", "Layers", "Detail"):
        assert expected in modes
    assert "fox" in render_view(browser, _EXPRESSION, uri, raw, "Text")
    grid = render_view(browser, _EXPRESSION, uri, raw, "Grid")
    assert "UPOS" in grid
    assert "DEPREL" in grid
    layers = render_view(browser, _EXPRESSION, uri, raw, "Layers")
    assert "token-tag" in layers
    assert "relation" in layers


def test_media_renders_technical_metadata(repo_dir: Path) -> None:
    """The media view shows its mime type and duration."""
    md = _first(RepoBrowser.open(repo_dir), _MEDIA)
    assert "audio/wav" in md
    assert "5000" in md


def test_persona_renders_guidelines(repo_dir: Path) -> None:
    """The persona view shows its framework and guidelines."""
    md = _first(RepoBrowser.open(repo_dir), _PERSONA)
    assert "Syntax expert" in md
    assert "Annotate dependency relations." in md


def test_eprint_renders_citation(repo_dir: Path) -> None:
    """The eprint view renders the structured citation's creators and venue."""
    md = _first(RepoBrowser.open(repo_dir), _EPRINT)
    assert "Universal Dependencies" in md
    assert "Nivre" in md
    assert "LREC" in md


def test_segmentation_renders_tokens(repo_dir: Path) -> None:
    """The segmentation Tokens view tabulates each tokenization's tokens."""
    browser = RepoBrowser.open(repo_dir)
    uri, raw = browser.records_raw(_SEGMENTATION)[0]
    assert view_modes(browser, _SEGMENTATION, uri, raw) == ["Tokens", "Detail"]
    md = render_view(browser, _SEGMENTATION, uri, raw, "Tokens")
    assert "The quick brown fox jumps." in md
    assert "6 tokens" in md
    assert columns_for(_SEGMENTATION) == ("Record",)


def test_summarize_is_type_appropriate(repo_dir: Path) -> None:
    """Return type-appropriate cells matching columns_for for each type."""
    browser = RepoBrowser.open(repo_dir)
    for nsid in (_CORPUS, _ONTOLOGY, _EDGE_SET, _MEDIA, _AGREEMENT, _JUDGMENT_SET):
        uri, raw = browser.records_raw(nsid)[0]
        assert len(summarize(nsid, uri, raw)) == len(columns_for(nsid))


# ---- generic fallback renderer and view dispatch --------------------------


def test_render_generic_formats_scalars_nested_and_skips_empty() -> None:
    """The generic view lists scalar fields, headers nested ones, and skips empty."""
    uri = "at://did:plc:x/pub.layers.thing/r"
    data: Mapping[str, JsonValue] = {
        "name": "widget",
        "count": 3,
        "empty_str": "",
        "empty_list": [],
        "missing": None,
        "tags": ["a", "b"],
        "meta": {"k": "v"},
    }
    md = _render_generic(uri, data)
    assert "widget" in md
    assert "## tags (2)" in md
    assert "## meta" in md
    # the empty-valued fields are skipped entirely.
    assert "empty_str" not in md
    assert "empty_list" not in md
    assert "missing" not in md


def test_render_generic_truncates_long_json() -> None:
    """A long nested scalar is truncated rather than dumped in full."""
    uri = "at://did:plc:x/pub.layers.thing/r"
    md = _render_generic(uri, {"blob": {"text": "z" * 1000}})
    assert "## blob" in md
    assert "…" in md


def test_render_view_unknown_mode_falls_back_to_first(repo_dir: Path) -> None:
    """An unknown view label renders the record's first (default) view."""
    browser = RepoBrowser.open(repo_dir)
    uri, raw = browser.records_raw(_SEGMENTATION)[0]
    first = record_views(browser, _SEGMENTATION, uri, raw)[0][0]
    assert first == "Tokens"
    fallback = render_view(browser, _SEGMENTATION, uri, raw, "NoSuchMode")
    expected = render_view(browser, _SEGMENTATION, uri, raw, "Tokens")
    assert fallback == expected


def test_render_record_unknown_type_uses_generic(repo_dir: Path) -> None:
    """A record type with no bespoke renderer falls through to the generic view."""
    browser = RepoBrowser.open(repo_dir)
    uri = "at://did:plc:x/pub.layers.unknown.thing/r"
    data = {"name": "mystery", "flavor": "novel"}
    md = render_record(browser, "pub.layers.unknown.thing", uri, data)
    assert "mystery" in md
    assert view_modes(browser, "pub.layers.unknown.thing", uri, data) == ["Detail"]


def test_item_index_is_per_browser_and_isolated(repo_dir: Path) -> None:
    """The judgment item index is cached per browser, not shared by id()."""
    browser_a = RepoBrowser.open(repo_dir)
    browser_b = RepoBrowser.open(repo_dir)
    index_a = _item_index(browser_a)
    assert browser_a in _ITEM_INDEX
    # a second browser gets its own entry, not browser_a's cached one.
    index_b = _item_index(browser_b)
    assert index_b is not index_a
    # the same browser returns the identical cached object.
    assert _item_index(browser_a) is index_a


# ---- materialization for the Query tab ------------------------------------


def test_materialize_repo_writes_views(repo_dir: Path, tmp_path: Path) -> None:
    """materialize_repo writes expressions, annotations, and per-type tables."""
    out_dir = tmp_path / "views"
    written = materialize_repo(RepoBrowser.open(repo_dir).repo, out_dir)
    names = {path.stem for path in written}
    assert "expressions" in names
    assert "annotations" in names
    assert "pub_layers_ontology_ontology" in names


def test_materialized_views_are_queryable(repo_dir: Path, tmp_path: Path) -> None:
    """The Query engine can open and query the materialized repository."""
    out_dir = tmp_path / "views"
    materialize_repo(RepoBrowser.open(repo_dir).repo, out_dir)
    engine = QueryEngine.open(out_dir)
    try:
        assert "expressions" in engine.tables
        result = engine.run_sql("SELECT count(*) AS n FROM expressions")
        assert result.rows[0].cells[0] == "3"
    finally:
        engine.close()


def test_materialize_for_query_bad_path_returns_none() -> None:
    """The Query-tab materializer returns None for an unopenable repository."""
    assert _materialize_for_query("/no/such/repository/path") is None


def test_materialize_for_query_round_trips(repo_dir: Path) -> None:
    """The Query-tab materializer flattens a repository into a readable dir."""
    out = _materialize_for_query(str(repo_dir))
    assert out is not None
    engine = QueryEngine.open(Path(out))
    try:
        assert "expressions" in engine.tables
    finally:
        engine.close()


def test_materialize_for_query_registers_cleanup(
    repo_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scratch directory is registered for removal at interpreter exit."""
    registered: list[tuple[object, ...]] = []

    def _capture(func: object, *args: object, **_kwargs: object) -> None:
        registered.append((func, *args))

    monkeypatch.setattr(lairs_tui.atexit, "register", _capture)
    out = _materialize_for_query(str(repo_dir))
    assert out is not None
    # the created directory is passed to shutil.rmtree at exit.
    assert any(Path(out) in call for call in registered)


def test_materialize_for_query_cleans_up_on_failure(
    repo_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A materialize failure removes the scratch directory and returns None."""
    created: list[Path] = []
    real_mkdtemp = lairs_tui.tempfile.mkdtemp

    def _record_mkdtemp(
        suffix: str | None = None,
        prefix: str | None = None,
        dir_: str | None = None,
    ) -> str:
        path = real_mkdtemp(suffix, prefix, dir_)
        created.append(Path(path))
        return path

    monkeypatch.setattr(lairs_tui.tempfile, "mkdtemp", _record_mkdtemp)

    def _boom(*_args: object, **_kwargs: object) -> list[Path]:
        message = "disk full"
        raise OSError(message)

    monkeypatch.setattr(lairs_tui, "materialize_repo", _boom)
    assert _materialize_for_query(str(repo_dir)) is None
    assert created
    assert not created[0].exists()


# ---- Browse pane in the app -----------------------------------------------


def _leaves(app: LairsApp) -> list[TreeNode[str | None]]:
    """Return the type-tree leaf nodes (the record-type entries)."""
    tree: Tree[str | None] = app.query_one("#types", Tree)
    return [leaf for ns in tree.root.children for leaf in ns.children]


def _select(app: LairsApp, nsid: str) -> None:
    """Select the type-tree leaf for a collection NSID."""
    leaf = next(leaf for leaf in _leaves(app) if leaf.data == nsid)
    app.query_one(BrowsePane).on_tree_node_selected(Tree.NodeSelected(leaf))


def test_repo_opens_on_browse_tab(repo_dir: Path) -> None:
    async def scenario() -> None:
        app = LairsApp(repo_path=str(repo_dir))
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause()
            assert app.query_one(TabbedContent).active == "browse"

    asyncio.run(scenario())


def test_type_tree_groups_by_namespace(repo_dir: Path) -> None:
    async def scenario() -> None:
        app = LairsApp(repo_path=str(repo_dir))
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause()
            tree: Tree[str | None] = app.query_one("#types", Tree)
            namespaces = {str(node.label) for node in tree.root.children}
            assert "ontology" in namespaces
            assert "graph" in namespaces
            assert any(leaf.data == _CORPUS for leaf in _leaves(app))

    asyncio.run(scenario())


def test_selecting_type_populates_records(repo_dir: Path) -> None:
    async def scenario() -> None:
        app = LairsApp(repo_path=str(repo_dir))
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause()
            _select(app, _TYPEDEF)
            await pilot.pause()
            table = app.query_one("#records", DataTable)
            assert [str(c.label) for c in table.columns.values()] == list(
                columns_for(_TYPEDEF)
            )
            assert table.row_count == 2

    asyncio.run(scenario())


def test_highlight_renders_type_aware_detail(repo_dir: Path) -> None:
    async def scenario() -> None:
        app = LairsApp(repo_path=str(repo_dir))
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause()
            _select(app, _ONTOLOGY)
            await pilot.pause()
            detail = app.query_one("#rdetail", Markdown)
            assert "Type hierarchy" in detail._markdown

    asyncio.run(scenario())


def test_browse_safe_render_catches_renderer_error(repo_dir: Path) -> None:
    """A raising renderer degrades to an error note instead of crashing the tab."""

    async def scenario() -> None:
        app = LairsApp(repo_path=str(repo_dir))
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause()
            pane = app.query_one(BrowsePane)

            def _boom() -> str:
                message = "malformed record"
                raise ValueError(message)

            rendered = pane._safe_render("Tree", _boom)
            assert "Could not render the Tree view" in rendered
            assert "malformed record" in rendered

    asyncio.run(scenario())


def test_filter_narrows_records(repo_dir: Path) -> None:
    async def scenario() -> None:
        app = LairsApp(repo_path=str(repo_dir))
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause()
            _select(app, _EXPRESSION)
            await pilot.pause()
            table = app.query_one("#records", DataTable)
            assert table.row_count == 3
            app.query_one("#rfilter", Input).value = "s1a"
            await pilot.pause()
            assert table.row_count == 1

    asyncio.run(scenario())


def test_empty_repo_shows_guidance() -> None:
    async def scenario() -> None:
        app = LairsApp()
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause()
            app.query_one(TabbedContent).active = "browse"
            await pilot.pause()
            pane = app.query_one(BrowsePane)
            assert pane._error is not None
            detail = app.query_one("#rdetail", Markdown)
            assert "No repository loaded" in detail._markdown

    asyncio.run(scenario())


def test_three_tab_keybindings(repo_dir: Path) -> None:
    async def scenario() -> None:
        app = LairsApp(repo_path=str(repo_dir))
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause()
            assert app.query_one(TabbedContent).active == "query"
            await pilot.press("1")
            await pilot.pause()
            assert app.query_one(TabbedContent).active == "explore"
            await pilot.press("2")
            await pilot.pause()
            assert app.query_one(TabbedContent).active == "browse"

    asyncio.run(scenario())


def test_view_key_flips_between_views(repo_dir: Path) -> None:
    async def scenario() -> None:
        app = LairsApp(repo_path=str(repo_dir))
        async with app.run_test(size=(180, 52)) as pilot:
            await pilot.pause()
            _select(app, _SEGMENTATION)
            await pilot.pause()
            wrap = app.query_one("#rdetail-wrap", VerticalScroll)
            first = str(wrap.border_title)
            await pilot.press("v")
            await pilot.pause()
            second = str(wrap.border_title)
            assert first != second
            assert "Tokens" in first
            assert "Detail" in second

    asyncio.run(scenario())
