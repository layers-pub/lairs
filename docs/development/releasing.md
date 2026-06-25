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
on every push to `main`. Your job is to prepare the release commit and push the
tag.

The version is declared once, in `pyproject.toml` (`project.version`). At runtime
`lairs.__version__` reads it back through `importlib.metadata.version("lairs")`,
so the installed metadata must match the source. After bumping the version,
reinstall (`uv sync`) before you build locally.

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

## One-time setup

The workflows assume this is configured on the repository and the package
indexes:

- **PyPI Trusted Publisher.** On PyPI, add a publisher for `layers-pub/lairs`,
  workflow `release.yml`, environment `pypi`. Before the first release the
  project does not exist yet, so add it as a *pending* publisher; the first tag
  push creates the project.
- **GitHub environments.** Create the `pypi` and `github-pages` environments in
  the repository settings. Add protection rules (for example a required reviewer
  on `pypi`) as desired.
- **GitHub Pages source.** Set Pages to deploy from GitHub Actions. The site is
  served at <https://layers.pub/lairs/>: the `layers-pub` organization's Pages
  custom domain (`layers.pub`) serves each project repository at `/<repo>/`, so
  no per-repo domain or CNAME is needed.
