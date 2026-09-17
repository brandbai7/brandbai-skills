param(
    [Parameter(Mandatory = $true)]
    [string]$SourcePath,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"
$source = [System.IO.Path]::GetFullPath($SourcePath)
$output = [System.IO.Path]::GetFullPath($OutputPath)

if (-not [System.IO.File]::Exists($source)) {
    throw "Launcher source is missing."
}

$outputDirectory = [System.IO.Path]::GetDirectoryName($output)
[System.IO.Directory]::CreateDirectory($outputDirectory) | Out-Null

if ([System.IO.File]::Exists($output)) {
    [System.IO.File]::Delete($output)
}

$brandIcon = Join-Path ([System.IO.Path]::GetDirectoryName($source)) 'brandbai.ico'
if (-not [System.IO.File]::Exists($brandIcon)) { throw 'BrandBAI launcher icon is missing.' }
$compiler = New-Object Microsoft.CSharp.CSharpCodeProvider
$parameters = New-Object System.CodeDom.Compiler.CompilerParameters
$parameters.GenerateExecutable = $true
$parameters.OutputAssembly = $output
$parameters.CompilerOptions = "/target:winexe /win32icon:`"$brandIcon`""
$parameters.ReferencedAssemblies.Add('System.dll') | Out-Null
try {
    $result = $compiler.CompileAssemblyFromFile($parameters, $source)
    if ($result.Errors.HasErrors) { throw ($result.Errors | Out-String) }
} finally { $compiler.Dispose() }

if (-not [System.IO.File]::Exists($output)) {
    throw "Launcher compilation did not produce an executable."
}
