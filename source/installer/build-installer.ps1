param([string]$Compiler, [string]$AppVersion='1.0.0')
$ErrorActionPreference='Stop'
if ($AppVersion -notmatch '^\d+\.\d+\.\d+([.-][A-Za-z0-9.-]+)?$') { throw 'Choose a valid application version.' }
$bootstrap=Join-Path $PSScriptRoot 'dependencies/MicrosoftEdgeWebview2Setup.exe'
if (-not (Test-Path -LiteralPath $bootstrap)) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $bootstrap) | Out-Null
    Invoke-WebRequest -Uri 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $bootstrap
}
$signature=Get-AuthenticodeSignature -LiteralPath $bootstrap
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft Corporation') { throw 'WebView2 installer signature verification failed.' }
if (-not $Compiler) {
    $found=Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($found) { $Compiler=$found.Source }
    else { $Compiler=Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6/ISCC.exe' }
}
if (-not (Test-Path -LiteralPath $Compiler)) { throw 'Install the official Inno Setup compiler or pass -Compiler with its ISCC.exe path.' }
& $Compiler "/DAppVersion=$AppVersion" (Join-Path $PSScriptRoot 'TarnishedCompanion.iss')
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
