# LoxBerry MCP Server

LoxBerry MCP Server makes a local Loxone installation available to compatible
AI clients through the Model Context Protocol (MCP). It runs on LoxBerry, needs
no project cloud service, and starts with read-only access.

## What it provides

- Read rooms, controls and current Loxone states permitted to the signed-in user.
- Optionally read history and masked LoxBerry diagnostics.
- Optionally operate a documented, type-specific and visible Loxone control.
- Connect clients through local HTTPS and OAuth.

## Safety model

Loxone permissions, optional control access and LoxBerry diagnostics are
separate approvals. Controls are disabled by default; arbitrary commands,
shell access and remote administration are not provided.

## Install

Install the ZIP asset from a [project GitHub Release](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/releases)
with the LoxBerry Plugin Manager. GitHub's automatic **Source code** archives
and local `-local-` ZIPs are not plugin packages.

## Documentation

- [User documentation](docs/user/README.md)
- [Client setup](docs/clients/README.md)
- [Support matrix](docs/development/support-matrix.md)
- [Developer documentation](docs/development/README.md)
- [Changes](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)

## License

Apache License 2.0. See [LICENSE](LICENSE).
