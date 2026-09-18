[CmdletBinding()]
param([Parameter(Mandatory)][string] $ProbePath)
$ErrorActionPreference = 'Stop'
Import-Module C:/Users/Benjamin/.codex/skills/test-loxberry-mcp-plugin/scripts/LoxBerryTarget.psm1 -Force
$modules = [ordered]@{}
$root = Split-Path $PSScriptRoot -Parent
foreach ($name in @('models','source','decoder','parser','graph','mapping','worker','service')) {
    $path = Join-Path $root "src/mcpserver/loxone/project/$name.py"
    if (Test-Path $path) { $modules["mcpserver.loxone.project.$name"] = Get-Content $path -Raw }
}
$modules['mcpserver.loxone.client'] = Get-Content (Join-Path $root 'src/mcpserver/loxone/client.py') -Raw
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($modules | ConvertTo-Json -Compress)))
$bootstrap = @'
import os, shlex, subprocess, sys, types, json, base64, logging, tempfile, pathlib
logging.disable(logging.CRITICAL)
for item in shlex.split(subprocess.check_output(['systemctl','show','loxberry-mcpserver.service','--property=Environment','--value'], text=True)):
    key, _, value = item.partition('=')
    if key.startswith('MCPSERVER_'): os.environ[key] = value
import mcpserver.loxone
package = types.ModuleType('mcpserver.loxone.project')
package.__path__ = []
sys.modules[package.__name__] = package
sources = json.loads(base64.b64decode('ENCODED_MODULES'))
# Only reviewed source code is staged, never downloaded project bytes or tokens.
import mcpserver
staging = tempfile.TemporaryDirectory(prefix='mcp-project-probe-')
root = pathlib.Path(staging.name)
for package_name, original in [('mcpserver',mcpserver),('mcpserver.loxone',mcpserver.loxone)]:
    folder = root.joinpath(*package_name.split('.'))
    folder.mkdir(parents=True, exist_ok=True)
    init = pathlib.Path(original.__file__).read_text()
    init += '\n__path__.append(' + repr(str(pathlib.Path(original.__file__).parent)) + ')\n'
    (folder/'__init__.py').write_text(init)
for name, source in sources.items():
    path = root.joinpath(*name.split('.')).with_suffix('.py')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
(root/'mcpserver/loxone/project/__init__.py').write_text('')
os.environ['PYTHONPATH'] = staging.name
order = [k for k in sources if not k.endswith('.service') and k != 'mcpserver.loxone.client']
order += ['mcpserver.loxone.client']
if 'mcpserver.loxone.project.service' in sources: order += ['mcpserver.loxone.project.service']
for name in order:
    module = types.ModuleType(name)
    module.__package__ = name.rpartition('.')[0]
    sys.modules[name] = module
    exec(compile(sources[name], '<project-probe-module>', 'exec'), module.__dict__)
'@
$source = $bootstrap.Replace('ENCODED_MODULES', $encoded) + "`n" + (Get-Content -LiteralPath $ProbePath -Raw)
Assert-LoxBerryConnection
$result = Invoke-LoxBerryCommand -Command '/opt/loxberry/data/plugins/mcpserver/venv/bin/python -' -InputText $source -AllowedExitCodes @(0,2) -TimeoutSeconds 60
$result.StdOut
