[CmdletBinding()]
param(
    [string]$PythonPath,
    [string]$VenvPath = ".venv",
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not [System.IO.Path]::IsPathRooted($VenvPath)) {
    $VenvPath = Join-Path $repositoryRoot $VenvPath
}

function Get-Python313Path {
    param([string]$RequestedPath)

    $candidates = [System.Collections.Generic.List[string]]::new()
    if ($RequestedPath) {
        $candidates.Add($RequestedPath)
    }
    else {
        $candidates.Add((Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"))
        $candidates.Add("C:\Python313\python.exe")
        $candidates.Add("C:\Program Files\Python313\python.exe")
    }

    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }

        $version = & $candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
        if ($LASTEXITCODE -eq 0 -and $version -eq "3.13") {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw "Python 3.13 was not found. Install it or pass -PythonPath <path-to-python.exe>."
}

$python = Get-Python313Path -RequestedPath $PythonPath
$venvPython = Join-Path $VenvPath "Scripts\python.exe"

if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
    $venvVersion = & $venvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($LASTEXITCODE -ne 0 -or $venvVersion -ne "3.13") {
        throw "The existing virtual environment at '$VenvPath' does not use Python 3.13. Remove it manually, then run this script again."
    }
}
elseif (-not $DryRun) {
    & $python -m venv $VenvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Creating the virtual environment failed."
    }
}

if ($DryRun) {
    Write-Output "Python 3.13: $python"
    Write-Output "Virtual environment: $VenvPath"
    Write-Output "Would install locked runtime and development dependencies, then install the project in editable mode."
    return
}

& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $repositoryRoot "requirements\runtime-arm64.lock") -r (Join-Path $repositoryRoot "requirements\dev.lock")
if ($LASTEXITCODE -ne 0) {
    throw "Installing locked dependencies failed."
}

& $venvPython -m pip install --disable-pip-version-check --no-deps -e $repositoryRoot
if ($LASTEXITCODE -ne 0) {
    throw "Installing the project in editable mode failed."
}

Write-Output "Development environment is ready: $VenvPath"
Write-Output "Run '$venvPython tools/test.py --profile changed --plan' to inspect the selected checks."
