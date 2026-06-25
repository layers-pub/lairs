"""WebDataset data-plane exporter.

Emits tar shards for heavy media from an Arrow view, binding to the
:class:`~lairs.integrations.ports.Exporter` port. Each sample is a keyed group
of files: a ``__key__``, a ``.json`` member holding the row's scalar fields, and,
when a media column is present, a media member carrying the resolved bytes.

The tar-writing path uses the standard-library :mod:`tarfile`, so basic sharding
is exercised without the optional ``webdataset`` library. The ``webdataset``
library (the ``lairs[webdataset]`` extra) is imported lazily inside the read-back
loader only, with a clear error when it is missing, so importing this module never
pulls the dependency in.
"""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING

import didactic.api as dx

if TYPE_CHECKING:
    from collections.abc import Iterator

    import pyarrow as pa

    from lairs._types import JsonValue

__all__ = ["WebDatasetExporter", "WebDatasetSpec"]

# the member extension used for each sample's json metadata.
_JSON_EXT = ".json"

# the default mime-to-extension fallback for an unrecognised media type.
_DEFAULT_MEDIA_EXT = ".bin"

# the mime types whose extension the exporter maps directly.
_MIME_EXT: dict[str, str] = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/flac": ".flac",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
    "text/plain": ".txt",
}


class WebDatasetSpec(dx.Model):
    """An export specification for the WebDataset exporter.

    Attributes
    ----------
    output_dir : str, optional
        The directory the tar shards are written into. Created if absent.
    shard_size : int, optional
        The maximum number of samples per shard. The final shard may be smaller.
    shard_prefix : str, optional
        The filename stem each shard is named after (``<prefix>-000000.tar``).
    key_column : str or None, optional
        The Arrow column whose value names each sample (its ``__key__``). When
        ``None`` the row index is used, zero-padded to a stable width.
    media_column : str or None, optional
        The Arrow column carrying media bytes or a resolvable media record. When
        present, each sample gains a media member alongside its json metadata.
    """

    output_dir: str = dx.field(
        default=".",
        description="directory the tar shards are written into",
    )
    shard_size: int = dx.field(
        default=1000,
        description="maximum number of samples per shard",
    )
    shard_prefix: str = dx.field(
        default="shard",
        description="filename stem each shard is named after",
    )
    key_column: str | None = dx.field(
        default=None,
        description="column whose value names each sample",
    )
    media_column: str | None = dx.field(
        default=None,
        description="column carrying media bytes or a resolvable media record",
    )


class WebDatasetExporter:
    """An exporter that emits WebDataset tar shards from an Arrow view.

    The exporter binds to the generic :class:`~lairs.integrations.ports.Exporter`
    port with a :class:`pyarrow.Table` view, a :class:`WebDatasetSpec`
    specification, and a list of written shard paths as its return type.
    """

    name = "webdataset"

    def export(
        self,
        view: pa.Table,
        *,
        spec: WebDatasetSpec | None = None,
    ) -> list[Path]:
        """Export an Arrow view to WebDataset tar shards.

        Each row becomes one sample. A sample carries a ``.json`` member with the
        row's scalar (non-media) fields and, when ``spec.media_column`` is set, a
        media member with the resolved bytes. Samples are grouped into shards of
        at most ``spec.shard_size`` rows, each written as a tar archive.

        Parameters
        ----------
        view : pyarrow.Table
            The flattened Arrow view to export.
        spec : WebDatasetSpec or None, optional
            The export specification. A default spec is used when omitted.

        Returns
        -------
        list of pathlib.Path
            The written tar shard files, in shard order.

        Raises
        ------
        ValueError
            When ``spec.shard_size`` is not positive, or a named column is absent
            from the view.
        """
        spec = spec or WebDatasetSpec()
        if spec.shard_size < 1:
            msg = "shard_size must be a positive integer"
            raise ValueError(msg)

        columns = set(view.column_names)
        if spec.key_column is not None and spec.key_column not in columns:
            msg = f"key_column {spec.key_column!r} is not a column of the view"
            raise ValueError(msg)
        if spec.media_column is not None and spec.media_column not in columns:
            msg = f"media_column {spec.media_column!r} is not a column of the view"
            raise ValueError(msg)

        out_dir = Path(spec.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        rows = view.to_pylist()
        width = max(len(str(len(rows) - 1)), 1)
        shards: list[Path] = []
        for shard_index, start in enumerate(range(0, len(rows), spec.shard_size)):
            batch = rows[start : start + spec.shard_size]
            path = out_dir / f"{spec.shard_prefix}-{shard_index:06d}.tar"
            self._write_shard(path, batch, start, width, spec)
            shards.append(path)
        return shards

    def _write_shard(
        self,
        path: Path,
        batch: list[dict[str, JsonValue]],
        offset: int,
        width: int,
        spec: WebDatasetSpec,
    ) -> None:
        """Write one batch of rows to a tar shard.

        Parameters
        ----------
        path : pathlib.Path
            The shard file to write.
        batch : list of dict
            The rows belonging to this shard.
        offset : int
            The global index of the first row in the batch, used for default keys.
        width : int
            The zero-pad width for default integer keys.
        spec : WebDatasetSpec
            The export specification.
        """
        with tarfile.open(path, "w") as tar:
            for local_index, row in enumerate(batch):
                key = self._sample_key(row, offset + local_index, width, spec)
                self._add_member(tar, f"{key}{_JSON_EXT}", self._json_bytes(row, spec))
                media = self._media_member(row, spec)
                if media is not None:
                    ext, payload = media
                    self._add_member(tar, f"{key}{ext}", payload)

    @staticmethod
    def _add_member(tar: tarfile.TarFile, name: str, payload: bytes) -> None:
        """Add a single named byte payload to an open tar archive.

        Parameters
        ----------
        tar : tarfile.TarFile
            The open archive to append to.
        name : str
            The member name (the sample key plus its extension).
        payload : bytes
            The member bytes.
        """
        info = tarfile.TarInfo(name=name)
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))

    def _sample_key(
        self,
        row: dict[str, JsonValue],
        index: int,
        width: int,
        spec: WebDatasetSpec,
    ) -> str:
        """Return the WebDataset ``__key__`` for a row.

        Parameters
        ----------
        row : dict
            The row's fields.
        index : int
            The row's global index, used when no key column is set.
        width : int
            The zero-pad width for the default integer key.
        spec : WebDatasetSpec
            The export specification.

        Returns
        -------
        str
            The sample key, sanitised so it never contains a path separator.
        """
        if spec.key_column is not None:
            value = row.get(spec.key_column)
            if value is not None:
                return self._sanitise_key(str(value))
        return f"{index:0{width}d}"

    @staticmethod
    def _sanitise_key(raw: str) -> str:
        """Return a key with path separators replaced so it is a flat name.

        Parameters
        ----------
        raw : str
            The raw key value.

        Returns
        -------
        str
            The sanitised key.
        """
        return raw.replace("/", "_").replace("\\", "_")

    def _json_bytes(self, row: dict[str, JsonValue], spec: WebDatasetSpec) -> bytes:
        """Serialise a row's scalar fields (minus the media column) to json bytes.

        Parameters
        ----------
        row : dict
            The row's fields.
        spec : WebDatasetSpec
            The export specification.

        Returns
        -------
        bytes
            The utf-8 json encoding of the row's metadata.
        """
        metadata = {
            name: value for name, value in row.items() if name != spec.media_column
        }
        return json.dumps(metadata, default=self._json_default).encode("utf-8")

    @staticmethod
    def _json_default(value: bytes) -> str:
        """Render a non-json value (raw bytes) into a json-safe placeholder.

        Parameters
        ----------
        value : bytes
            The non-serialisable value encountered by the json encoder.

        Returns
        -------
        str
            A short descriptor standing in for opaque bytes.

        Raises
        ------
        TypeError
            When the value is not bytes, so the encoder reports a real error.
        """
        if isinstance(value, (bytes, bytearray)):
            return f"<{len(value)} bytes>"
        msg = f"object of type {type(value).__name__} is not JSON serialisable"
        raise TypeError(msg)

    def _media_member(
        self,
        row: dict[str, JsonValue],
        spec: WebDatasetSpec,
    ) -> tuple[str, bytes] | None:
        """Return the media extension and bytes for a row, when present.

        The media cell may already be raw bytes, or a JSON-shaped media record
        carrying a ``cid``/``mimeType`` and inline ``data``; the latter is
        resolved into a :class:`~lairs.media.MediaHandle` so its bytes and mime
        type drive the member extension.

        Parameters
        ----------
        row : dict
            The row's fields.
        spec : WebDatasetSpec
            The export specification.

        Returns
        -------
        tuple of (str, bytes) or None
            The ``(extension, bytes)`` of the media member, or ``None`` when the
            row has no media or the cell is empty.
        """
        if spec.media_column is None:
            return None
        cell = row.get(spec.media_column)
        if cell is None:
            return None
        if isinstance(cell, (bytes, bytearray)):
            data = bytes(cell)
            return (_DEFAULT_MEDIA_EXT, data) if data else None
        if isinstance(cell, dict):
            return self._resolve_media_cell(cell)
        return None

    def _resolve_media_cell(
        self,
        cell: dict[str, JsonValue],
    ) -> tuple[str, bytes] | None:
        """Resolve a JSON-shaped media record cell to a media member.

        Parameters
        ----------
        cell : dict
            The media record's fields, as carried in the Arrow row.

        Returns
        -------
        tuple of (str, bytes) or None
            The ``(extension, bytes)`` of the media member, or ``None`` when the
            record carries no bytes to embed.
        """
        from lairs.media import MediaHandle, resolve_media  # noqa: PLC0415

        record = _MediaCell.from_json(cell)
        try:
            handle = resolve_media(record)
        except ValueError:
            handle = MediaHandle(
                cid=record.cid,
                mime_type=record.mime_type,
                modality="document",
                data=record.data,
            )
        if not handle.data:
            return None
        return (self._extension_for(handle.mime_type), handle.data)

    @staticmethod
    def _extension_for(mime_type: str) -> str:
        """Return the file extension for a mime type, with a binary fallback.

        Parameters
        ----------
        mime_type : str
            The media mime type.

        Returns
        -------
        str
            The mapped extension, or ``.bin`` when the type is unrecognised.
        """
        return _MIME_EXT.get(mime_type.lower(), _DEFAULT_MEDIA_EXT)

    def load(self, shards: list[Path]) -> Iterator[dict[str, JsonValue]]:
        """Read shards back through the ``webdataset`` loader.

        This is the read-back path used by training loops; it requires the
        optional ``webdataset`` library and is imported lazily so importing this
        module never pulls the dependency in.

        Parameters
        ----------
        shards : list of pathlib.Path
            The shard files to read, in order.

        Returns
        -------
        collections.abc.Iterator of dict
            The decoded samples, one mapping per sample.

        Raises
        ------
        ImportError
            When the optional ``webdataset`` library is not installed.
        """
        try:
            import webdataset as wds  # noqa: PLC0415
        except ImportError as exc:
            msg = "the webdataset loader requires the optional 'webdataset' extra"
            raise ImportError(msg) from exc
        urls = [str(path) for path in shards]
        # webdataset ships no type information, so its top-level WebDataset
        # factory is invisible to the checker.
        return iter(wds.WebDataset(urls))  # ty: ignore[unresolved-attribute]


class _MediaCell(dx.Model):
    """A minimal view of a media-record cell read off an Arrow row.

    The Arrow row carries a media record as a JSON-shaped dict; this model picks
    out the fields :func:`~lairs.media.resolve_media` reads, so the exporter never
    inspects the raw mapping with widened types.

    Attributes
    ----------
    cid : str, optional
        The media content identifier.
    mime_type : str, optional
        The media mime type.
    external_uri : str or None, optional
        The external URI, when the media is externally hosted.
    data : bytes, optional
        Inline media bytes carried as an opaque payload.
    """

    cid: str = dx.field(default="", description="media content identifier")
    mime_type: str = dx.field(
        default="application/octet-stream",
        description="media mime type",
    )
    external_uri: str | None = dx.field(
        default=None,
        description="external URI when externally hosted",
    )
    data: bytes = dx.field(
        default=b"",
        opaque=True,
        description="inline media bytes",
    )

    @classmethod
    def from_json(cls, cell: dict[str, JsonValue]) -> _MediaCell:
        """Build a media cell from a JSON-shaped Arrow row value.

        Parameters
        ----------
        cell : dict
            The media record's fields as carried in the Arrow row.

        Returns
        -------
        _MediaCell
            The picked media metadata, with inline bytes when present.
        """
        return cls(
            cid=_str_field(cell, "cid", "id") or "",
            mime_type=(
                _str_field(cell, "mimeType", "mime_type") or "application/octet-stream"
            ),
            external_uri=_str_field(cell, "externalUri", "external_uri"),
            data=_bytes_field(cell, "data", "bytes"),
        )


def _str_field(cell: dict[str, JsonValue], *names: str) -> str | None:
    """Return the first present str value among ``names`` in a cell.

    Parameters
    ----------
    cell : dict
        The media record's fields.
    *names : str
        The candidate field names, in priority order.

    Returns
    -------
    str or None
        The first matching string value, or ``None`` when none is present.
    """
    for name in names:
        value = cell.get(name)
        if isinstance(value, str):
            return value
    return None


def _bytes_field(cell: dict[str, JsonValue], *names: str) -> bytes:
    """Return the first present bytes-like value among ``names`` in a cell.

    A ``bytes``/``bytearray`` value is used directly; a ``str`` value is encoded
    as utf-8 so inline text payloads still survive. Anything else yields empty.

    Parameters
    ----------
    cell : dict
        The media record's fields.
    *names : str
        The candidate field names, in priority order.

    Returns
    -------
    bytes
        The first matching payload, or empty when none is present.
    """
    for name in names:
        value = cell.get(name)
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
        if isinstance(value, str):
            return value.encode("utf-8")
    return b""
