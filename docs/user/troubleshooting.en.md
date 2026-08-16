# Troubleshooting

[Deutsch](troubleshooting.de.md)

| Symptom | Safe check |
| --- | --- |
| Client cannot reach the server | Check service status, local HTTPS address and certificate diagnostics. |
| OAuth login does not start | Open the HTTPS address; HTTP is not used for login. |
| A tool returns `permission_denied` | Check Loxone rights, requested scope and, when applicable, local admin approval. |
| A tool returns `emergency_stop_active` | Check the selected emergency-stop signal: `1` permits tool calls and `0` blocks them. With `unknown`, the service cannot confirm a safe value. Set the signal to `1` outside MCP or remove the selection; do not retry automatically. The response includes the current state and UTC times for observation and the start of the block. |
| No current values | Check the Miniserver connection and whether the Loxone user may see the controls. |
| An update failed | Wait for terminal Plugin Manager status and retain the earlier package. |

Do not export or share credentials, tokens, private addresses or complete state data. Use only masked plugin diagnostics.
