# Integration ports

The stable protocols integrations bind to. Each port is a
``typing.Protocol`` generic over its concrete payload and return types,
so no method returns a widened type. Adapters bind a port to concrete
didactic models and framework objects. For the design see [Concepts >
Integrations and ports](../concepts/integrations.md).

::: lairs.integrations.ports.Codec

::: lairs.integrations.ports.Exporter

::: lairs.integrations.ports.KnowledgeBase

::: lairs.integrations.ports.StorageBackend
