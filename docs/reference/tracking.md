# Experiment tracking

Experiment tracking logs a Repository revision and its provenance bundle to
Weights & Biases or MLflow, so a run pins the exact record CIDs and the
lexicon manifest hash it was built against. It requires the
``lairs[tracking]`` extra. For usage, see [Guides > Experiment
tracking](../guide/tracking.md).

::: lairs.integrations.tracking
