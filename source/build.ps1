$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $compiler /nologo /target:library /optimize+ /platform:anycpu /reference:System.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll "/out:$PSScriptRoot\native\LayeredOverlay.dll" "$PSScriptRoot\native\LayeredOverlay.cs"
if ($LASTEXITCODE -ne 0) { throw 'Native overlay build failed.' }
py -3 -m PyInstaller --noconfirm --onefile --windowed --name TarnishedCompanion --icon "$PSScriptRoot\assets\app-icon.ico" --distpath $projectRoot --workpath "$projectRoot\build" --specpath "$projectRoot\build" --collect-all webview --collect-all clr_loader --collect-all pythonnet --add-data "$PSScriptRoot\data;data" --add-data "$PSScriptRoot\fonts;fonts" --add-data "$PSScriptRoot\native;native" --add-data "$PSScriptRoot\assets;assets" --add-data "$PSScriptRoot\ui.html;." --add-data "$PSScriptRoot\overlay.html;." --add-data "$PSScriptRoot\preview.html;." "$PSScriptRoot\app.py"
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
