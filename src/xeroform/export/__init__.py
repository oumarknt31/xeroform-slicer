"""Pluggable exporters.

The engine talks to the `Exporter` interface only. Adding a new machine format
(binary CLI, OpenVectorFormat, a firmware-specific dialect) means adding one
class here and registering it - nothing else in the engine changes.
"""
from .base import Exporter
from .cli_ascii import AsciiCliExporter

EXPORTERS = {
    "cli": AsciiCliExporter,
}


def get_exporter(name: str, **kwargs) -> Exporter:
    try:
        cls = EXPORTERS[name]
    except KeyError:
        raise ValueError(f"Unknown export format {name!r}. Available: {list(EXPORTERS)}") from None
    return cls(**kwargs)


__all__ = ["Exporter", "AsciiCliExporter", "EXPORTERS", "get_exporter"]
