param(
    [string]$ClaudeConfigPath = (Join-Path $env:APPDATA 'Claude\claude_desktop_config.json'),
    [string]$ServerName = 'loxberry-mcp',
    [string]$VisibilityFixturePath,
    [int]$TimeoutSeconds = 120
)

$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath $ClaudeConfigPath -Raw | ConvertFrom-Json
$server = $config.mcpServers.$ServerName
if (-not $server -or -not $server.command) {
    throw 'Claude MCP configuration is missing.'
}

$startInfo = [System.Diagnostics.ProcessStartInfo]::new()
$startInfo.FileName = [string]$server.command
foreach ($argument in $server.args) {
    [void]$startInfo.ArgumentList.Add([string]$argument)
}
if ($server.env) {
    foreach ($property in $server.env.PSObject.Properties) {
        $startInfo.Environment[$property.Name] = [string]$property.Value
    }
}
$startInfo.UseShellExecute = $false
$startInfo.CreateNoWindow = $true
$startInfo.RedirectStandardInput = $true
$startInfo.RedirectStandardOutput = $true
$startInfo.RedirectStandardError = $true

$process = [System.Diagnostics.Process]::new()
$process.StartInfo = $startInfo
[void]$process.Start()
$script:stderrLines = [System.Collections.Generic.List[string]]::new()
$script:stderrReadTask = $process.StandardError.ReadLineAsync()
$script:authorizationReported = $false
$script:authorizationUrlFile = Join-Path ([IO.Path]::GetTempPath()) 'loxberry-mcp-oauth-url.tmp'
Remove-Item -LiteralPath $script:authorizationUrlFile -Force -ErrorAction SilentlyContinue

function Read-StderrProgress {
    while ($script:stderrReadTask.IsCompleted) {
        $line = $script:stderrReadTask.Result
        if ($null -eq $line) { return }
        $script:stderrLines.Add($line)
        if (-not $script:authorizationReported -and $line -match '(https://\S+/authorize\?\S+)') {
            $authorizationUrl = $Matches[1].TrimEnd('.', ',', ')')
            [IO.File]::WriteAllText($script:authorizationUrlFile, $authorizationUrl)
            $authorizationUrl = ''
            Write-Output "MCP_AUTHORIZATION_REQUIRED=$script:authorizationUrlFile"
            $script:authorizationReported = $true
        }
        $script:stderrReadTask = $process.StandardError.ReadLineAsync()
    }
}

function Send-JsonRpc([hashtable]$Message) {
    $line = $Message | ConvertTo-Json -Depth 20 -Compress
    $process.StandardInput.WriteLine($line)
    $process.StandardInput.Flush()
}

function Read-JsonRpc([int]$Id) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $readTask = $null
    while ([DateTime]::UtcNow -lt $deadline) {
        Read-StderrProgress
        if ($null -eq $readTask) { $readTask = $process.StandardOutput.ReadLineAsync() }
        if (-not $readTask.Wait(500)) {
            if ($process.HasExited) { throw "MCP proxy exited before response $Id." }
            continue
        }
        $line = $readTask.Result
        $readTask = $null
        if ($null -eq $line) { throw "MCP proxy closed stdout before response $Id." }
        try { $message = $line | ConvertFrom-Json } catch { continue }
        if ($message.id -eq $Id) { return $message }
    }
    throw "Timed out waiting for MCP response $Id."
}

function Invoke-ReadTool([int]$Id, [string]$Name, [hashtable]$Arguments) {
    Send-JsonRpc @{
        jsonrpc = '2.0'
        id = $Id
        method = 'tools/call'
        params = @{ name = $Name; arguments = $Arguments }
    }
    $response = Read-JsonRpc $Id
    if ($response.error -or $response.result.isError) { throw "Read-only tool $Name failed." }
    $envelope = $response.result.structuredContent
    if (-not $envelope -and $response.result.content[0].text) {
        $envelope = $response.result.content[0].text | ConvertFrom-Json
    }
    if (-not $envelope -or -not $envelope.ok) {
        throw "Read-only tool $Name returned an invalid envelope."
    }
    return $envelope
}

try {
    Send-JsonRpc @{
        jsonrpc = '2.0'; id = 0; method = 'initialize'
        params = @{
            protocolVersion = '2025-11-25'; capabilities = @{}
            clientInfo = @{ name = 'phase1-readonly-probe'; version = '0.1.0' }
        }
    }
    if ((Read-JsonRpc 0).error) { throw 'MCP initialize failed.' }
    Send-JsonRpc @{ jsonrpc = '2.0'; method = 'notifications/initialized'; params = @{} }
    Send-JsonRpc @{ jsonrpc = '2.0'; id = 1; method = 'tools/list'; params = @{} }
    $toolsResponse = Read-JsonRpc 1
    if ($toolsResponse.error) { throw 'MCP tools/list failed.' }

    $expected = @(
        'loxone_get_system_status', 'loxone_list_rooms', 'loxone_list_categories',
        'loxone_find_controls', 'loxone_describe_control', 'loxone_get_states'
    )
    $actual = @($toolsResponse.result.tools | ForEach-Object { $_.name } | Sort-Object)
    if (($actual -join "`n") -ne (($expected | Sort-Object) -join "`n")) {
        throw 'MCP tool inventory differs from the six-tool read-only contract.'
    }
    foreach ($tool in $toolsResponse.result.tools) {
        if ($tool.annotations.readOnlyHint -ne $true -or $tool.annotations.destructiveHint -ne $false) {
            throw 'MCP tool annotations violate the read-only contract.'
        }
        if (-not $tool.outputSchema.properties.data.anyOf) {
            throw 'MCP tool output schema is not concrete.'
        }
    }

    [void](Invoke-ReadTool 2 'loxone_get_system_status' @{})
    [void](Invoke-ReadTool 3 'loxone_list_rooms' @{ limit = 100 })
    [void](Invoke-ReadTool 4 'loxone_list_categories' @{ limit = 100 })
    $controls = Invoke-ReadTool 5 'loxone_find_controls' @{ limit = 100 }
    $visibleUuid = @($controls.data.items | ForEach-Object { $_.uuid }) | Select-Object -First 1
    $hiddenUuid = $null
    if ($VisibilityFixturePath) {
        $fixture = Get-Content -LiteralPath $VisibilityFixturePath -Raw | ConvertFrom-Json
        $visibleUuid = [string]$fixture.visible_control_uuid
        $hiddenUuid = [string]$fixture.hidden_control_uuid
        $controlUuids = @($controls.data.items | ForEach-Object { $_.uuid })
        if (-not $visibleUuid -or $visibleUuid -notin $controlUuids) {
            throw 'Expected visible control is absent.'
        }
        if ($hiddenUuid -and $hiddenUuid -in $controlUuids) {
            throw 'Expected hidden control leaked into the result.'
        }
    }
    if (-not $visibleUuid) { throw 'No visible control is available for the read-only probe.' }
    $description = Invoke-ReadTool 6 'loxone_describe_control' @{ control_uuid = $visibleUuid }
    $stateUuid = @($description.data.states | ForEach-Object { $_.uuid }) | Select-Object -First 1
    if (-not $stateUuid) { throw 'The selected visible control has no readable state.' }
    [void](Invoke-ReadTool 7 'loxone_get_states' @{ state_uuids = @($stateUuid) })

    $visibleUuid = $null
    $hiddenUuid = $null
    $stateUuid = $null
    'mcp_tool_contract=pass'
    'mcp_six_read_tools=pass'
    if ($VisibilityFixturePath) { 'mcp_visibility_filter=pass' }
} finally {
    try { $process.StandardInput.Close() } catch {}
    if (-not $process.WaitForExit(3000)) {
        $process.Kill($true)
        [void]$process.WaitForExit(3000)
    }
    Remove-Item -LiteralPath $script:authorizationUrlFile -Force -ErrorAction SilentlyContinue
    $process.Dispose()
}
