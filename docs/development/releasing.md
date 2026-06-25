# Releasing

`lairs` follows [Semantic Versioning](https://semver.org/) and publishes to
[PyPI](https://pypi.org/project/lairs/) as `lairs`. While the project is pre-1.0
the rules in [Stability](../project/stability.md) describe what a minor bump may
change.

Releases are automated. Pushing a `vX.Y.Z` tag triggers the
[release workflow](https://github.com/layers-pub/lairs/blob/main/.github/workflows/release.yml),
which verifies the build, publishes to PyPI via Trusted Publishing, and cuts the
GitHub release. The documentation is published
separately by the
[docs workflow](https://github.com/layers-pub/lairs/blob/main/.github/workflows/docs.yml)
on every push to `main`. A maintainer prepares the release commit and pushes the
tag; the workflows do the rest.

The version is declared once, in `pyproject.toml` (`project.version`). At runtime
`lairs.__version__` reads it back through `importlib.metadata.version("lairs")`,
so the installed metadata must match the source. After bumping the version,
reinstall (`uv sync`) before building locally.

## Prepare the release

Work from a clean checkout of `main`.

1. **Update the changelog.** In `CHANGELOG.md`, rename the `## [Unreleased]`
   section to the new version with today's date, add a fresh empty
   `## [Unreleased]` above it, and update the comparison links at the bottom of
   the file. The release workflow extracts this section verbatim for the GitHub
   release notes.

2. **Bump the version** in `pyproject.toml`, then sync so the installed metadata
   matches:

   ```bash
   uv sync
   python -c "import lairs; print(lairs.__version__)"   # must print the new version
   ```

3. **Record any lexicon bump.** If this release adopts a new Layers version,
   confirm `lairs gen --check` is clean and that `layers_version` in
   `lairs/lexicons/MANIFEST.toml` and the [Stability](../project/stability.md)
   page agree.

4. **Verify locally (recommended).** The workflow re-runs all of this, but
   catching a failure now is faster than catching it in CI:

   ```bash
   uv run ruff format --check lairs tests
   uv run ruff check lairs tests
   uv run ty check --error-on-warning
   uv run pytest --run-integration
   uv run --group docs mkdocs build --strict
   uv build && uvx twine check dist/*
   ```

## Tag and push

Commit the version and changelog change to `main`, then tag and push:

```bash
git commit -am "chore(release): vX.Y.Z"
git push origin main          # the docs workflow redeploys the site
git tag vX.Y.Z
git push origin vX.Y.Z        # the release workflow publishes the release
```

The tag push starts `release.yml`: it verifies, builds the sdist and wheel,
asserts the built version matches the tag, publishes to PyPI, and creates the
GitHub release with the changelog section as notes. Watch it from the Actions
tab.

## After the release

Confirm the published package installs cleanly in a fresh environment and reports
the right version:

```bash
uv run --no-project --with "lairs==X.Y.Z" python -c "import lairs; print(lairs.__version__)"
```

Then continue normal development against the new `## [Unreleased]` changelog
section.
