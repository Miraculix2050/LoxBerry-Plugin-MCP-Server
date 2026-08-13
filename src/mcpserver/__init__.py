"""LoxBerry MCP Server package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("loxberry-mcpserver")
except PackageNotFoundError:  # pragma: no cover - source tree without installation
    __version__ = "0.4.0-alpha.5"

__all__ = ["__version__"]
