#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define ProjectRoot AddBackslash(SourcePath) + "..\.."

[Setup]
AppId={{56388B8E-0C7F-4AEF-AFB6-8C7E75F9A32A}
AppName=Tarnished Companion
AppVersion={#AppVersion}
AppPublisher=Koné Labie
DefaultDirName={autopf}\Tarnished Companion
DefaultGroupName=Tarnished Companion
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#ProjectRoot}
OutputBaseFilename=TarnishedCompanion-Setup
SetupIconFile={#ProjectRoot}\source\assets\app-icon.ico
UninstallDisplayIcon={app}\TarnishedCompanion.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=110
CloseApplications=no
RestartApplications=no
DisableWelcomePage=no
DisableReadyPage=yes
LicenseFile={#ProjectRoot}\LICENSE.txt
SetupLogging=yes

[Files]
Source: "{#ProjectRoot}\TarnishedCompanion.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjectRoot}\LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjectRoot}\README.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjectRoot}\THIRD-PARTY.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "dependencies\MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy

[Icons]
Name: "{group}\Tarnished Companion"; Filename: "{app}\TarnishedCompanion.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Tarnished Companion"; Filename: "{app}\TarnishedCompanion.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\TarnishedCompanion.exe"; Parameters: "--prepare-offline-setup"; Flags: runhidden waituntilterminated; Check: PrepareGameEnabled
Filename: "{app}\TarnishedCompanion.exe"; Description: "Open Tarnished Companion and start Elden Ring offline"; Flags: nowait postinstall skipifsilent

[Messages]
WelcomeLabel2=Setup installs Tarnished Companion and its automatic offline launch support. Opening the companion finds Elden Ring, opens Steam if needed, and starts your game and overlay. No separate mod download or Vortex setup is required.%n%nIf Microsoft WebView2 is missing, setup installs it automatically. An internet connection is needed only for that prerequisite. Elden Ring and Steam must already be installed.
FinishedLabel=Your companion is ready. Open Tarnished Companion to start Elden Ring offline and display the overlay. Load your character in the game as usual.

[Code]
function PrepareGameEnabled: Boolean;
begin
  Result := ExpandConstant('{param:SKIPGAMESETUP|0}') <> '1';
end;

function RuntimePresent: Boolean;
var
  Version: String;
  Key: String;
begin
  Key := 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Result := (RegQueryStringValue(HKCU, Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
            (RegQueryStringValue(HKLM32, Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Result := '';
  if RuntimePresent then Exit;
  WizardForm.StatusLabel.Caption := 'Installing Microsoft WebView2 automatically...';
  ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
  if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, Code) then
  begin
    Result := 'Microsoft WebView2 could not start. Reconnect to the internet and run this installer again.';
    Exit;
  end;
  if not RuntimePresent then
    Result := 'Microsoft WebView2 did not finish installing. Check your internet connection and run this installer again. No manual runtime download is needed.';
end;
