; GhostMind — Inno Setup script
; Build with: iscc installer/ghostmind.iss
; Output: dist/GhostMind-Setup-<version>.exe

#define MyAppName "GhostMind"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Dasun Jayasanka"
#define MyAppURL "https://github.com/dasunjlk/GhostMind"
#define MyAppExeName "ghostmind.exe"

[Setup]
; Application information
AppId={{8E9A7D5C-3F2B-4E1A-9C8D-7F6E5A4B3C2D}
AppName={*#MyAppName}
AppVersion={*#MyAppVersion}
AppPublisher={*#MyAppPublisher}
AppPublisherURL={*#MyAppURL}
AppSupportURL={*#MyAppURL}
AppUpdatesURL={*#MyAppURL}
DefaultDirName={localappdata}\GhostMind
DefaultGroupName=GhostMind
AllowNoIcons=yes
; Per-user install (no admin required)
PrivilegesRequired=lowest
; Disable Windows version detection (app is Windows 10+ only, but installer works on older versions)
MinVersion=10.0
; Disable forcing to a specific architecture (allow both 32-bit and 64-bit installs)
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
; Output settings
OutputDir=dist
OutputBaseFilename=GhostMind-Setup-{*#MyAppVersion}
SetupIconFile=assets\icon.ico
; Compression
Compression=lzma2/ultra64
; Disable running the app after install (user starts it manually)
CloseApplications=no
; Keep install directory editable
DisableProgramGroupPage=yes
; Uninstaller settings
UninstallDisplayIcon={app}\ghostmind.exe
UninstallDisplaySize=50

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupicon"; Description: "Start with Windows"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
; Main application files — the entire PyInstaller onedir build
Source: "dist\ghostmind\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Exclude test files and development artifacts from the install
Source: "dist\ghostmind\*.pyc"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs; Exclude
Source: "dist\ghostmind\__pycache__"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs; Exclude
Source: "dist\ghostmind\tests"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs; Exclude
Source: "dist\ghostmind\.gitkeep"; DestDir: "{app}"; Flags: ignoreversion; Exclude
; Icon file (for uninstaller display)
Source: "assets\icon.ico"; DestDir: "{app}"; Flags: ignoreversion
; LICENSE file (included in installer per release plan R-01)
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion
; .env.example (template for users)
Source: ".env.example"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\GhostMind"; Filename: "{app}\ghostmind.exe"
Name: "{group}\{cm:UninstallProgram,GhostMind}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\GhostMind"; Filename: "{app}\ghostmind.exe"; Tasks: desktopicon

[Registry]
; Start with Windows — add registry entry when startupicon task is selected
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "GhostMind"; ValueData: """{app}\ghostmind.exe"""; Flags: uninsdeletevalue; Tasks: startupicon

[Run]
; Run the application after installation (optional — user can start manually)
Filename: "{app}\ghostmind.exe"; Description: "Launch GhostMind now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove app directory on uninstall, but keep config/ and logs
Type: filesandordirs; Name: "{app}"

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
end;
