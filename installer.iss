#ifndef MyAppVersion
  #define MyAppVersion "1.0.1"
#endif

[Setup]
AppId={{2E4D782D-29E0-4A72-9946-9A0F0788B2A1}
AppName=Bubble Player
AppVersion={#MyAppVersion}
AppPublisher=Bubble
DefaultDirName={localappdata}\Programs\Bubble
DefaultGroupName=Bubble
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=bubble-{#MyAppVersion}-win-x64-setup
SetupIconFile=assets\logo.ico
UninstallDisplayIcon={app}\bubble.exe
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce

[Files]
Source: "dist\bubble-{#MyAppVersion}-win-x64.exe"; DestDir: "{app}"; DestName: "bubble.exe"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Bubble\Bubble Player"; Filename: "{app}\bubble.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Bubble Player"; Filename: "{app}\bubble.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\bubble.exe"; Description: "Launch Bubble Player"; Flags: postinstall nowait skipifsilent

; Deliberately do not delete {userappdata}\Bubble on uninstall, so the library survives.
