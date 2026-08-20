# Adapter registry

The registry resolves codec, exporter, and knowledge-base adapters by
name from in-process registration and Python entry points. It uses the
entry-point groups ``lairs.codecs``, ``lairs.exporters``, and
``lairs.knowledge_bases``.

::: lairs.integrations.registry
