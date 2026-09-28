; Inno Setup script for the Windows app: installs the PyInstaller folder for the current
; user (no administrator rights), with a Start-menu entry and an uninstaller.
; Built by scripts/build_windows.py, which passes /DAppVersion and /DSourceDir.
; Settings, logs and the downloaded language tools live in %APPDATA% and %LOCALAPPDATA%
; \typst-writer and are kept when uninstalling.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\build\pyinstaller\dist\typst-writer"
#endif

[Setup]
AppId={{3E07A208-CD74-42B2-8FEC-80C3673022CA}
AppName=typst-writer
AppVersion={#AppVersion}
AppVerName=typst-writer {#AppVersion}
DefaultDirName={autopf}\typst-writer
DefaultGroupName=typst-writer
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=typst-writer-setup
SetupIconFile=typst-writer.ico
UninstallDisplayIcon={app}\typst-writer.exe
UninstallDisplayName=typst-writer
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
ShowLanguageDialog=auto

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Files of the previous version (an update replaces the whole program folder).
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\typst-writer"; Filename: "{app}\typst-writer.exe"
Name: "{autodesktop}\typst-writer"; Filename: "{app}\typst-writer.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\typst-writer.exe"; Description: "{cm:LaunchProgram,typst-writer}"; Flags: nowait postinstall skipifsilent
