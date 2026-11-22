; PDF 阅读器 安装脚本 (Inno Setup 6)
; 编译：ISCC.exe installer\setup.iss

#define MyAppName "PDF 阅读器"
#define MyAppVersion "2.3"
#define MyAppPublisher "深圳市创炫互动网络科技有限公司"
#define MyAppExeName "PDF阅读器.exe"
#define MyAppURL "http://www.mrheedu.com"

[Setup]
RedirectionGuard=no
AppId={{0F63B8B1-8C4E-4E6D-9A8D-3B1D0E6C2A45}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DirExistsWarning=no
OutputDir=installer_output
OutputBaseFilename=PDF阅读器_Setup_{#MyAppVersion}
SetupIconFile=..\icons\app.ico
UninstallDisplayIcon={app}\app.ico
UninstallDisplayName={#MyAppName}
Compression=lzma2/ultra64
SolidCompression=yes
LanguageDetectionMethod=uilanguage
WizardStyle=modern
; per-user 安装：全程不弹 UAC，默认装到 %LOCALAPPDATA%\Programs
PrivilegesRequired=lowest
DisableDirPage=no

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式(&D)"; GroupDescription: "附加图标:"; Flags: unchecked
Name: "fileassoc"; Description: "关联 .pdf 文件（双击用本程序打开）(&A)"; GroupDescription: "文件关联:"; Flags: unchecked

[Files]
; onedir 打包：整体复制 dist\PDF阅读器 目录（exe + _internal 依赖）
Source: "..\dist\PDF阅读器\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\icons\app.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app.ico"; Tasks: desktopicon

[Registry]
; 文件关联 .pdf → 本程序（仅当前用户 HKCU，per-user 安装规范）
Root: HKCU; Subkey: "Software\Classes\.pdf"; ValueType: string; ValueName: ""; ValueData: "PDFReader.Document"; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\PDFReader.Document"; ValueType: string; ValueName: ""; ValueData: "PDF 文档"; Flags: uninsdeletekey; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\PDFReader.Document\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\app.ico"; Flags: uninsdeletekey; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\PDFReader.Document\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletevalue; Tasks: fileassoc

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent
