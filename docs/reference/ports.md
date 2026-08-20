# Integration ports

Integrations bind to a set of stable ``typing.Protocol`` ports. `Codec`,
`Exporter`, and `KnowledgeBase` are generic over their concrete payload and
return types; `StorageBackend` is non-generic and types its methods directly
against ``str``, ``bytes``, and ``bool``. No method returns a widened type.
Adapters bind a port to concrete didactic models and framework objects. For
the design, see [Concepts >
Integrations and ports](../concepts/integrations.md).

::: lairs.integrations.ports.Codec

::: lairs.integrations.ports.Exporter

::: lairs.integrations.ports.KnowledgeBase

::: lairs.integrations.ports.StorageBackend
