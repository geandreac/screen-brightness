; Instalador do Lume (Inno Setup 6). Gerado pelo workflow ou por packaging\build_windows.ps1.
; Instala só para o usuário atual: não pede senha de administrador.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6E0B7C1A-4C55-4F0E-9B7D-3F1C2A9D8E41}
AppName=Lume
AppVersion={#AppVersion}
AppVerName=Lume {#AppVersion}
AppPublisher=geandreac
AppPublisherURL=https://github.com/geandreac/screen-brightness
DefaultDirName={autopf}\Lume
DefaultGroupName=Lume
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist\installer
OutputBaseFilename=Lume-Setup-{#AppVersion}
SetupIconFile=..\assets\lume.ico
UninstallDisplayIcon={app}\Lume.exe
UninstallDisplayName=Lume — brilho e cor da tela
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Fecha o Lume aberto (inclusive na área de notificação) antes de atualizar/desinstalar.
AppMutex=LumeAppMutex
CloseApplications=yes

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked
Name: "startup"; Description: "Iniciar o Lume com o Windows (fica só o ícone na área de notificação)"; GroupDescription: "Inicialização:"; Flags: unchecked

[Files]
Source: "..\dist\Lume\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Lume"; Filename: "{app}\Lume.exe"
Name: "{autodesktop}\Lume"; Filename: "{app}\Lume.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Lume"; ValueData: """{app}\Lume.exe"" --tray"; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\Lume.exe"; Description: "Abrir o Lume agora"; Flags: nowait postinstall skipifsilent
; Atualização feita de dentro do app (/SILENT /RELAUNCH): reabre o Lume ao terminar.
Filename: "{app}\Lume.exe"; Flags: nowait; Check: ShouldRelaunch

[UninstallRun]
; Garante cores originais caso o app tenha sido encerrado à força com ajustes ativos.
Filename: "{app}\Lume.exe"; Parameters: "--reset-colors"; Flags: runhidden waituntilterminated; RunOnceId: "LumeResetColors"

[Code]
function ShouldRelaunch: Boolean;
begin
  { Parâmetro próprio: o Inno Setup ignora parâmetros desconhecidos. }
  Result := WizardSilent and (Pos('/RELAUNCH', Uppercase(GetCmdTail)) > 0);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { A opção "Iniciar com o Windows" também pode ter sido ligada dentro do app. }
  if CurUninstallStep = usPostUninstall then
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Lume');
end;
