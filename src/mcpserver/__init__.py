"""LoxBerry MCP Server package."""

__all__ = ["__version__"]


def __getattr__(name: str) -> str:
    if name != "__version__":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib.metadata import PackageNotFoundError, version

    try:
        __version__ = version("loxberry-mcpserver")
    except PackageNotFoundError:  # pragma: no cover - source tree without installation
        __version__ = "0.4.0-beta.4"
    globals()[name] = __version__
    return __version__
