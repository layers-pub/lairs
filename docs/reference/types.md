# Shared types

The cross-cutting typing primitives reused across lairs: the recursive
`JsonValue` alias for JSON-shaped data, and the type variables for
generic helpers. Polymorphism elsewhere is expressed through these
aliases, concrete unions, generics, and protocols rather than `Any` or
`object`.

::: lairs._types
