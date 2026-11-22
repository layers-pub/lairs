# Authoring

The authoring API provides builders over the generated models and the write
path to a PDS. Its builders construct anchors, layers, and cross-references
with model type and structure checks plus selected builder argument checks.
These checks do not enforce every lexicon constraint; see
[validation scope](../concepts/generated-models.md#validation-scope).
The publish module diffs a local Repository revision against a PDS and applies
the minimal write
set. For the workflow, see [Guides > Authoring and
publishing](../guide/authoring.md).

## Builders

::: lairs.author.builders

## Publish

::: lairs.author.publish
