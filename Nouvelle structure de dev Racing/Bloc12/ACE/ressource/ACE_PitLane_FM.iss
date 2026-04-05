; =============================================================================
;  ACE_PitLane_FM.iss - Script Inno Setup
; =============================================================================

#define AppName        "ACE PitLane FM"
#define AppVersion     "1.0.0"
#define AppPublisher   "MetalSlug35"
#define AppExeName     "ACE_PitLane_FM.exe"
#define ConfigExeName  "ACE_Configurateur.exe"
#define AppId          "MetalSlug.ACEPitLaneFM"
#define Bloc11ACE      "..\..\..\Bloc11\ACE"
#define Bloc11Shared   "..\..\..\Bloc11\ressource"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://www.nexusmods.com/profile/MetalSlug35/mods
AppSupportURL=https://www.nexusmods.com/profile/MetalSlug35/mods
AppUpdatesURL=https://www.nexusmods.com/profile/MetalSlug35/mods
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DefaultDirName={autopf64}\PitLane FM\ACE PitLane FM
DefaultGroupName={#AppName}
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
OutputDir=..\output
OutputBaseFilename=ACE_PitLane_FM_Setup
SetupIconFile={#Bloc11ACE}\ACE_PitLane_FM_icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
InternalCompressLevel=ultra64
LZMAUseSeparateProcess=yes
WizardStyle=modern
WizardResizable=no
PrivilegesRequired=admin
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=no
ShowLanguageDialog=no
LanguageDetectionMethod=locale
MinVersion=6.1

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Files]
Source: "..\..\..\dist\ACE\ACE_PitLane_FM\*";          DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\..\dist\ACE\ACE_Configurateur\*";       DestDir: "{app}\Configurator"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Bloc11Shared}\Buy Me a Coffee - MetalSlug35.url"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Bloc11Shared}\Nexus Mods - MetalSlug35.url";      DestDir: "{app}"; Flags: ignoreversion
Source: "{#Bloc11Shared}\*.m3u";  DestDir: "{autopf64}\PitLane FM\Radio"; Flags: ignoreversion uninsneveruninstall
Source: "{#Bloc11Shared}\*.m3u8"; DestDir: "{autopf64}\PitLane FM\Radio"; Flags: ignoreversion skipifsourcedoesntexist uninsneveruninstall
Source: "{#Bloc11Shared}\*.pls";  DestDir: "{autopf64}\PitLane FM\Radio"; Flags: ignoreversion skipifsourcedoesntexist uninsneveruninstall

[Dirs]
Name: "{autopf64}\PitLane FM";        Flags: uninsneveruninstall
Name: "{autopf64}\PitLane FM\Radio";  Flags: uninsneveruninstall

[Icons]
Name: "{userdesktop}\{#AppName}";              Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"
Name: "{group}\{#AppName}";                    Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"
Name: "{group}\Configurer {#AppName}";         Filename: "{app}\Configurator\{#ConfigExeName}"; IconFilename: "{app}\Configurator\{#ConfigExeName}"
Name: "{group}\Desinstaller {#AppName}";       Filename: "{uninstallexe}"

[Run]
Filename: "{app}\Configurator\{#ConfigExeName}"; \
    Parameters: "--configure-only"; \
    Description: "Ouvrir l'assistant de configuration"; \
    Flags: shellexec nowait postinstall skipifsilent

[Code]
function RacingRootDir(): string;
begin
  Result := ExpandConstant('{autopf64}\PitLane FM');
end;

function SharedRadioDir(): string;
begin
  Result := AddBackslash(RacingRootDir()) + 'Radio';
end;

function HasOtherRacingAppsInstalled(): Boolean;
var
  Root: string;
begin
  Root := AddBackslash(RacingRootDir());
  Result :=
    DirExists(Root + 'ACC PitLane FM') or
    DirExists(Root + 'AMS2 PitLane FM') or
    DirExists(Root + 'LMU PitLane FM');
end;

procedure CleanupSharedRadioIfLastRacingApp();
begin
  if HasOtherRacingAppsInstalled() then
    exit;
  DelTree(SharedRadioDir(), True, True, True);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    CleanupSharedRadioIfLastRacingApp();
end;
