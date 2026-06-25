# Releasing

`lairs` follows [Semantic Versioning](https://semver.org/) and publishes to
[PyPI](https://pypi.org/project/lairs/) as `lairs`. While the project is pre-1.0
the rules in [Stability](../project/stability.md) describe what a minor bump may
change.

The version is declared once, in `pyproject.toml` (`project.version`). At
runtime `lairs.__version__` reads it back through
`importlib.metadata.version("lairs")`, so the installed metadata must match the
source. After bumping the version, reinstall (`uv sync`) before you build.

## Checklist

Run the release from a clean checkout of `main` with everything green.

1. **Confirm the gates pass.**

   ```bash
   uv run ruff format --check lairs tests
   uv run ruff check lairs tests
   uvx ty check --python .venv --error-on-warning
   uv run pytest --run-integration
   uv run --group docs mkdocs build --strict
   ```

2. **Update the changelog.** In `CHANGELOG.md`, rename the `## [Unreleased]`
   section to the new version with today's date, add a fresh empty
   `## [Unreleased]` above it, and update the comparison links at the bottom of
   the file.

3. **Bump the version** in `pyproject.toml`, then sync so the installed metadata
   matches:

   ```bash
   uv sync
   python -c "import lairs; print(lairs.__version__)"   # must print the new version
   ```

4. **Record any lexicon bump.** If this release adopts a new Layers version,
   confirm `lairs gen --check` is clean and that `layers_version` in
   `lairs/lexicons/MANIFEST.toml` and the [Stability](../project/stability.md)
   page agree.

5. **Build the artifacts.**

   ```bash
   rm -rf dist
   uv build           # writes dist/lairs-X.Y.Z.tar.gz and the wheel
   uvx twine check dist/*
   ```

   `twine check` must report `PASSED` for both the sdist and the wheel.

6. **Commit and tag.** Commit the version and changelog change, then tag:

   ```bash
   git commit -am "chore(release): vX.Y.Z"
   git tag vX.Y.Z
   git push origin main --tags
   ```

7. **Publish to PyPI.**

   ```bash
   uvx twine upload dist/*
   ```

   Use an API token (or PyPI Trusted Publishing from CI). Never commit a token.

8. **Cut the GitHub release.** Create a release from the `vX.Y.Z` tag on
   `layers-pub/lairs` and paste the changelog entry as the notes.

9. **Deploy the docs.**

   ```bash
   uv run --group docs mkdocs gh-deploy
   ```

   This publishes the built site to GitHub Pages at
   <https://layers-pub.github.io/lairs/>.

## After the release

Confirm the published package installs cleanly in a fresh environment and
reports the right version:

```bash
uv run --no-project --with "lairs==X.Y.Z" python -c "import lairs; print(lairs.__version__)"
```

Then continue normal development against the new `## [Unreleased]` changelog
section.
