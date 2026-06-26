<!--
Thanks for contributing to lairs. Please fill in the sections below and check
every box before requesting review. See CONTRIBUTING.md for the full guide.
-->

## Summary

<!-- What does this PR do, and why? One or two sentences. -->

## Changes

<!-- A short bullet list of the notable changes. -->

-

## Type of change

<!-- Mark all that apply with an x. -->

- [ ] Bug fix (a non-breaking change that fixes an issue)
- [ ] New feature (a non-breaking change that adds functionality)
- [ ] Breaking change (a fix or feature that changes existing behaviour)
- [ ] Documentation
- [ ] Refactor, test, or chore (no user-visible change)

## Checklist

<!-- All boxes should be checked before review. See CONTRIBUTING.md. -->

- [ ] `uv run ruff format --check lairs tests` passes
- [ ] `uv run ruff check lairs tests` passes (including `ANN401`; no `Any` in annotations)
- [ ] `uv run ty check --error-on-warning` passes
- [ ] `uv run pytest` passes (the unit and functional suite)
- [ ] `uv run pytest --run-integration -m integration` passes against the Docker test PDS
- [ ] `uv run --group docs mkdocs build --strict` passes (when docs or a public API changed)
- [ ] Tests added or updated for new behaviour, mirrored 1:1 under `tests/`
- [ ] `CHANGELOG.md` updated under `## [Unreleased]` for user-visible changes
- [ ] No `@dataclass`, `pydantic`, `Any`, or `object` annotation introduced; no em-dashes
- [ ] Commits follow Conventional Commits, imperative mood, with no AI-assistant mentions

## Related issues

<!-- Link the issues this PR addresses, for example "Closes #1". -->

Closes #
