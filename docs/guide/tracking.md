# Experiment tracking

This guide covers logging a Repository revision as a tracked artifact with
provenance, for Weights & Biases and MLflow, and the reproducibility that follows
from the revision id.

`log_revision` records the revision itself, not a copy of the data. A logged run
pins the exact commit (or tag) and the vendored lexicon manifest hash the records
were generated against, so the dataset behind a run can always be rebuilt. The
backend libraries are imported lazily, so importing `lairs.integrations.tracking`
never pulls in `wandb` or `mlflow`.

## Logging a revision

```python
from lairs.integrations.tracking import log_revision
from lairs.store.repository import Repository

repo = Repository.open("/path/to/repo")
artifact = log_revision(repo.inner, "v1", backend="wandb")
print(artifact)                          # "lairs-revision:v1"
```

`log_revision` takes the underlying didactic repository handle, which the lairs
`Repository` wrapper exposes as `repo.inner`. `backend` is a keyword-only argument
and is `"wandb"` or `"mlflow"`. The function assembles a `ProvenanceBundle` and
returns the tracked artifact identifier as `"<name>:<revision>"`.

- For **Weights & Biases**, the bundle is attached as the metadata of a
  `wandb.Artifact` of type `dataset`, and it is logged to the active run when one
  is open.
- For **MLflow**, the bundle's fields are logged as run parameters and the
  revision is set as a tag.

An unrecognized backend raises `ValueError`. A backend whose optional dependency
is missing raises `ImportError` directing the caller to install
`lairs[tracking]`. The probe runs before any logging, so the error is raised only
when that backend is used.

## What the provenance pins

The `ProvenanceBundle` carries:

- `revision`: the Repository commit id or tag the run was logged against.
- `lexicon_tree_hash`: the content hash of the vendored lexicon tree the
  records were generated from, read from `lairs/lexicons/MANIFEST.toml`.
- `layers_version`: the upstream Layers release the lexicons were vendored from.
- `working_dir`: the Repository working directory the revision was read from.

The two manifest fields are read from the vendored manifest packaged with lairs,
so a logged run always records the schema version its records were generated
against, independent of the caller.

## Reproducibility from the revision id

The revision id is the reproducibility anchor. A tag pins an exact,
byte-reproducible set of record values in the Repository, so rebuilding the
dataset behind a run is: open the same Repository, resolve the logged revision,
and materialize. Pairing the revision with the lexicon manifest hash also pins
the schema, so the generated models match the records.

```python
from lairs.store.repository import Repository

repo = Repository.open("/path/to/repo")
repo.resolve("v1")                       # the logged revision resolves to a commit
```

## Requirements

`log_revision` needs the `lairs[tracking]` extra (`wandb`, `mlflow`) for the
backend used. Installing only one backend's library is enough to log to that
backend, and the other is probed only when selected.

## See also

- [Authoring](authoring.md) for producing and committing the revisions you log.
- [Exporters](exporters.md) for the dataset a tracked run consumes.
- [CLI](cli.md) for committing a pulled snapshot whose revision you can log.
