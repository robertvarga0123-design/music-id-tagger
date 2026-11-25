#define MyAppName "Music ID Tagger"
#define MyAppVersion "1.5.1"
#define MyAppPublisher "RCRTZ"
#define MyAppExeName "MusicIDTagger.exe"

[Setup]
AppId={{7E4C1A2B-5D88-4F0E-9C31-A6B8D2E47F10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=Output
OutputBaseFilename=MusicIDTagger-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupLogging=yes

[Languages]
Name: "hungarian"; MessagesFile: "compiler:Languages\Hungarian.isl"

[Tasks]
Name: "desktopicon"; Description: "Parancsikon az asztalon"; GroupDescription: "További ikonok:"; Flags: unchecked

[Files]
Source: "..\dist\MusicIDTagger\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "A Music ID Tagger indítása"; Flags: nowait postinstall skipifsilent
