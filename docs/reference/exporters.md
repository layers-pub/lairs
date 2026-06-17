# Exporters

The data-plane exporters, which bind to the [``Exporter``](ports.md)
port and emit framework-native datasets from an Arrow view. Each backend
library is an optional dependency imported lazily. For usage see [Guides
> Exporters](../guide/exporters.md).

## HuggingFace datasets

::: lairs.integrations.hf.datasets

## HuggingFace Hub

::: lairs.integrations.hf.hub

## PyTorch

::: lairs.integrations.torch

## TensorFlow tf.data

::: lairs.integrations.tfdata

## WebDataset

::: lairs.integrations.webdataset
