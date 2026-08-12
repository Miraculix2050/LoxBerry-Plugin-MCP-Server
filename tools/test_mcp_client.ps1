param(
    [string]$ClaudeConfigPath,
    [string]$ServerName = 'loxberry-mcp',
    [string]$VisibilityFixturePath,
    [string]$ControlFixturePath,
    [int]$CallbackPort,
    [int]$TimeoutSeconds = 120,
    [switch]$CheckConfigurationOnly
)

$ErrorActionPreference = 'Stop'

function Resolve-ClaudeConfigPath([string]$RequestedPath) {
    if ($RequestedPath) {
        if (-not (Test-Path -LiteralPath $RequestedPath -PathType Leaf)) {
            throw 'The requested Claude configuration file does not exist.'
        }
        return (Get-Item -LiteralPath $RequestedPath).FullName
    }

    if ($env:LOCALAPPDATA) {
        $packagesPath = Join-Path $env:LOCALAPPDATA 'Packages'
        if (Test-Path -LiteralPath $packagesPath -PathType Container) {
            $storeCandidates = @(
                Get-ChildItem -LiteralPath $packagesPath -Directory -Filter 'Claude_*' -ErrorAction SilentlyContinue |
                    ForEach-Object {
                        Join-Path $_.FullName 'LocalCache\Roaming\Claude\claude_desktop_config.json'
                    } |
                    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
                    Sort-Object { (Get-Item -LiteralPath $_).LastWriteTimeUtc } -Descending
            )
            if ($storeCandidates.Count -gt 0) {
                return $storeCandidates[0]
            }
        }
    }

    if ($env:APPDATA) {
        $classicPath = Join-Path $env:APPDATA 'Claude\claude_desktop_config.json'
        if (Test-Path -LiteralPath $classicPath -PathType Leaf) {
            return $classicPath
        }
    }

    throw 'No active Claude Desktop configuration file was found.'
}

$ClaudeConfigPath = Resolve-ClaudeConfigPath $ClaudeConfigPath
$config = Get-Content -LiteralPath $ClaudeConfigPath -Raw | ConvertFrom-Json
$server = $config.mcpServers.$ServerName
if (-not $server -or -not $server.command) {
    throw "Claude MCP server '$ServerName' is missing from the active configuration."
}
if ($CheckConfigurationOnly) {
    'claude_mcp_configuration=pass'
    return
}

$startInfo = [System.Diagnostics.ProcessStartInfo]::new()
$startInfo.FileName = [string]$server.command
$proxyArguments = [System.Collections.Generic.List[string]]::new()
foreach ($argument in @($server.args)) {
    $proxyArguments.Add([string]$argument)
}
if ($CallbackPort) {
    $serverUrlIndex = -1
    for ($index = 0; $index -lt $proxyArguments.Count; $index += 1) {
        if ($proxyArguments[$index] -match '^https?://') {
            $serverUrlIndex = $index
            break
        }
    }
    if ($serverUrlIndex -lt 0) {
        throw 'CallbackPort requires an HTTP(S) server URL in the proxy arguments.'
    }
    $callbackIndex = $serverUrlIndex + 1
    if ($callbackIndex -lt $proxyArguments.Count -and
        $proxyArguments[$callbackIndex] -match '^\d+$') {
        $proxyArguments[$callbackIndex] = [string]$CallbackPort
    } else {
        $proxyArguments.Insert($callbackIndex, [string]$CallbackPort)
    }
}
foreach ($argument in $proxyArguments) {
    [void]$startInfo.ArgumentList.Add($argument)
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

function Get-NextId {
    $value = $script:nextId
    $script:nextId += 1
    return $value
}

function Invoke-ToolEnvelope([int]$Id, [string]$Name, [hashtable]$Arguments) {
    Send-JsonRpc @{
        jsonrpc = '2.0'
        id = $Id
        method = 'tools/call'
        params = @{ name = $Name; arguments = $Arguments }
    }
    $response = Read-JsonRpc $Id
    if ($response.error -or $response.result.isError) { throw "MCP tool $Name failed." }
    $envelope = $response.result.structuredContent
    if (-not $envelope -and $response.result.content[0].text) {
        $envelope = $response.result.content[0].text | ConvertFrom-Json
    }
    if (-not $envelope) { throw "MCP tool $Name returned no envelope." }
    return $envelope
}

function Invoke-ReadTool([int]$Id, [string]$Name, [hashtable]$Arguments) {
    $envelope = Invoke-ToolEnvelope $Id $Name $Arguments
    if (-not $envelope.ok) { throw "Read-only tool $Name returned an error envelope." }
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
    $initializeResponse = Read-JsonRpc 0
    if ($initializeResponse.error) { throw 'MCP initialize failed.' }
    if ($initializeResponse.result.instructions -notlike '*skill://using-loxberry-mcp/SKILL.md*' -or
        $initializeResponse.result.instructions -notlike '*loxone_get_skill_guide*') {
        throw 'MCP initialize did not advertise the bundled skill.'
    }
    Send-JsonRpc @{ jsonrpc = '2.0'; method = 'notifications/initialized'; params = @{} }
    Send-JsonRpc @{ jsonrpc = '2.0'; id = 1; method = 'tools/list'; params = @{} }
    $toolsResponse = Read-JsonRpc 1
    if ($toolsResponse.error) { throw 'MCP tools/list failed.' }

    $expected = @(
        'loxone_get_system_status', 'loxone_list_rooms', 'loxone_list_categories',
        'loxone_find_controls', 'loxone_describe_control', 'loxone_get_control_notes',
        'loxone_get_states',
        'loxone_get_skill_guide'
    )
    $actual = @($toolsResponse.result.tools | ForEach-Object { $_.name } | Sort-Object)
    $controlAdvertised = $actual -contains 'loxone_operate_control'
    if ($controlAdvertised) { $expected += 'loxone_operate_control' }
    if ($ControlFixturePath -and -not $controlAdvertised) {
        throw 'ControlFixturePath requires the enabled loxone_operate_control tool.'
    }
    if (($actual -join "`n") -ne (($expected | Sort-Object) -join "`n")) {
        throw 'MCP tool inventory differs from the expected enabled contract.'
    }
    foreach ($tool in $toolsResponse.result.tools) {
        if ($tool.name -eq 'loxone_operate_control') {
            if ($tool.annotations.readOnlyHint -ne $false -or
                $tool.annotations.destructiveHint -ne $true -or
                $tool.annotations.idempotentHint -ne $true) {
                throw 'MCP control tool annotations violate the control contract.'
            }
        } elseif ($tool.annotations.readOnlyHint -ne $true -or $tool.annotations.destructiveHint -ne $false) {
            throw 'MCP tool annotations violate the read-only contract.'
        }
        if (-not $tool.outputSchema.properties.data.anyOf) {
            throw 'MCP tool output schema is not concrete.'
        }
    }

    Send-JsonRpc @{ jsonrpc = '2.0'; id = 2; method = 'resources/list'; params = @{} }
    $resourcesResponse = Read-JsonRpc 2
    if ($resourcesResponse.error -or @($resourcesResponse.result.resources).Count -ne 1 -or
        [string]$resourcesResponse.result.resources[0].uri -ne
            'skill://using-loxberry-mcp/SKILL.md' -or
        $resourcesResponse.result.resources[0].mimeType -ne 'text/markdown') {
        throw 'MCP skill resource inventory differs from the expected contract.'
    }
    Send-JsonRpc @{
        jsonrpc = '2.0'; id = 3; method = 'resources/read'
        params = @{ uri = 'skill://using-loxberry-mcp/SKILL.md' }
    }
    $resourceResponse = Read-JsonRpc 3
    $skillMarkdown = [string]$resourceResponse.result.contents[0].text
    if ($resourceResponse.error -or
        $resourceResponse.result.contents[0].mimeType -ne 'text/markdown' -or
        $skillMarkdown -notlike "---`nname: using-loxberry-mcp`n*") {
        throw 'MCP skill resource content differs from the expected contract.'
    }

    $script:nextId = 4
    $skillGuide = Invoke-ReadTool (Get-NextId) 'loxone_get_skill_guide' @{}
    if ($skillGuide.data.name -ne 'using-loxberry-mcp' -or
        $skillGuide.data.revision -ne 12 -or
        $skillGuide.data.media_type -ne 'text/markdown' -or
        $skillGuide.data.content -ne $skillMarkdown) {
        throw 'MCP skill guide tool differs from the canonical resource.'
    }
    [void](Invoke-ReadTool (Get-NextId) 'loxone_get_system_status' @{})
    [void](Invoke-ReadTool (Get-NextId) 'loxone_list_rooms' @{ limit = 100 })
    [void](Invoke-ReadTool (Get-NextId) 'loxone_list_categories' @{ limit = 100 })

    $allControls = [System.Collections.Generic.List[object]]::new()
    $cursor = $null
    $pageCount = 0
    do {
        $arguments = @{ limit = 100 }
        if ($cursor) { $arguments.cursor = $cursor }
        $page = Invoke-ReadTool (Get-NextId) 'loxone_find_controls' $arguments
        foreach ($control in $page.data.items) { $allControls.Add($control) }
        $cursor = $page.data.next_cursor
        $pageCount += 1
        if ($pageCount -gt 50) { throw 'Control pagination exceeded the safe test bound.' }
    } while ($cursor)

    $visibleUuid = @($allControls | ForEach-Object { $_.uuid }) | Select-Object -First 1
    $hiddenUuid = $null
    $description = $null
    if ($VisibilityFixturePath) {
        $fixture = Get-Content -LiteralPath $VisibilityFixturePath -Raw | ConvertFrom-Json
        $visibleUuid = [string]$fixture.visible_control_uuid
        $hiddenUuid = [string]$fixture.hidden_control_uuid
        $controlUuids = @($allControls | ForEach-Object { $_.uuid })
        if (-not $visibleUuid -or $visibleUuid -notin $controlUuids) {
            throw 'Expected visible control is absent.'
        }
        if ($hiddenUuid -and $hiddenUuid -in $controlUuids) {
            throw 'Expected hidden control leaked into the result.'
        }
        if ($hiddenUuid) {
            $hidden = Invoke-ToolEnvelope (Get-NextId) 'loxone_describe_control' @{
                control_uuid = $hiddenUuid
            }
            if ($hidden.ok -or $hidden.data.error -ne 'not_found') {
                throw 'Expected hidden control is directly describable.'
            }
        }
        $description = Invoke-ReadTool (Get-NextId) 'loxone_describe_control' @{
            control_uuid = $visibleUuid
        }
    } else {
        $describeBudget = [Math]::Max(0, 50 - $pageCount)
        foreach ($control in @($allControls | Select-Object -First $describeBudget)) {
            $candidate = Invoke-ReadTool (Get-NextId) 'loxone_describe_control' @{
                control_uuid = $control.uuid
            }
            if (@($candidate.data.states).Count -gt 0) {
                $visibleUuid = $control.uuid
                $description = $candidate
                break
            }
        }
    }
    if (-not $visibleUuid -or -not $description) {
        throw 'No visible control with a readable state is available within the safe call budget.'
    }
    $stateUuid = @($description.data.states | ForEach-Object { $_.uuid }) | Select-Object -First 1
    if (-not $stateUuid) { throw 'The selected visible control has no readable state.' }
    [void](Invoke-ReadTool (Get-NextId) 'loxone_get_states' @{ state_uuids = @($stateUuid) })

    if ($ControlFixturePath) {
        $controlFixture = Get-Content -LiteralPath $ControlFixturePath -Raw | ConvertFrom-Json
        $controlUuid = [string]$controlFixture.control_uuid
        $initialState = [string]$controlFixture.initial_state
        if (-not $controlUuid -or $initialState -notin @('on', 'off')) {
            throw 'Control fixture must contain control_uuid and initial_state on/off.'
        }
        $testState = if ($initialState -eq 'on') { 'off' } else { 'on' }
        $changed = $false
        try {
            $operation = Invoke-ToolEnvelope (Get-NextId) 'loxone_operate_control' @{
                control_uuid = $controlUuid; action = $testState
            }
            if (-not $operation.ok -or -not $operation.data.accepted -or
                -not $operation.data.confirmed -or $operation.data.observed_state -ne $testState) {
                throw 'The test Switch action was not confirmed.'
            }
            $changed = $true
        } finally {
            if ($changed) {
                $restore = Invoke-ToolEnvelope (Get-NextId) 'loxone_operate_control' @{
                    control_uuid = $controlUuid; action = $initialState
                }
                if (-not $restore.ok -or -not $restore.data.accepted -or
                    -not $restore.data.confirmed -or $restore.data.observed_state -ne $initialState) {
                    throw 'The test Switch initial state was not restored and confirmed.'
                }
            }
        }
        $controlUuid = $null
        'mcp_switch_control=pass'
    }

    $visibleUuid = $null
    $hiddenUuid = $null
    $stateUuid = $null
    'mcp_tool_contract=pass'
    'mcp_skill_delivery=pass'
    if ($ControlFixturePath) { 'mcp_six_data_tools_plus_skill_guide_and_control=pass' }
    else { 'mcp_six_data_tools_plus_skill_guide=pass' }
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
