; Inno Setup 6 简体中文语言文件
; 占位符格式：[name] [name/ver] [mb] [gb]，缺失键自动回退 Default.isl 英文

[LangOptions]
LanguageName=简体中文
LanguageID=$0804
LanguageCodePage=936
DialogFontName=微软雅黑
DialogFontSize=9

[Messages]
; ── 向导页标题 ──
WizardWelcome=欢迎
WizardLicense=许可协议
WizardSelectDir=选择目标位置
WizardSelectComponents=选择组件
WizardSelectProgramGroup=选择「开始」菜单文件夹
WizardSelectTasks=选择附加任务
WizardReady=准备安装
WizardPreparing=正在准备安装
WizardInstalling=正在安装
WizardFinished=完成安装

; ── 标题栏 ──
SetupAppTitle=安装
SetupWindowTitle=%1 安装
UninstallAppFullTitle=%1 卸载

; ── 欢迎页 ──
WelcomeLabel1=欢迎使用 [name] 安装向导
WelcomeLabel2=本程序将在您的电脑上安装 [name/ver]。%n%n建议安装前关闭所有其他应用程序。%n%n单击「下一步」继续，或单击「取消」退出。

; ── 选择安装位置 ──
SelectDirDesc=[name] 应安装在何处？
SelectDirLabel3=安装程序将把 [name] 安装到以下文件夹。
SelectDirBrowseLabel=要继续请单击「下一步」。若要安装到其他文件夹，请单击「浏览」。
NoIconsCheck=不创建任何图标(&D)

; ── 磁盘空间 ──
DiskSpaceGBLabel=至少需要 [gb] GB 的可用磁盘空间。
DiskSpaceMBLabel=至少需要 [mb] MB 的可用磁盘空间。
ComponentsDiskSpaceGBLabel=当前所选组件至少需要 [gb] GB 的磁盘空间。
ComponentsDiskSpaceMBLabel=当前所选组件至少需要 [mb] MB 的磁盘空间。

; ── 附加任务 ──
SelectTasksLabel2=选择安装 [name] 时要执行的附加任务，然后单击「下一步」。

; ── 准备安装 ──
ReadyLabel1=安装程序已准备好在您的电脑上安装 [name]。

; ── 安装中 ──
PreparingDesc=安装程序正在准备在您的电脑上安装 [name]。
InstallingLabel=请稍候，正在安装 [name]...

; ── 安装完成 ──
FinishedHeadingLabel=完成 [name] 安装向导
FinishedLabelNoIcons=安装程序已完成 [name] 的安装。
FinishedLabel=安装程序已完成 [name] 的安装。可通过已创建的快捷方式运行本程序。
FinishedRestartLabel=要完成 [name] 的安装，安装程序必须重新启动电脑。是否立即重新启动？
FinishedRestartMessage=要完成 [name] 的安装，安装程序必须重新启动电脑。%n%n是否立即重新启动？

; ── 按钮 ──
BtnBack=< 上一步(&B)
BtnNext=下一步(&N) >
BtnInstall=安装(&I)
BtnOK=确定
BtnCancel=取消
BtnYes=是(&Y)
BtnNo=否(&N)
BtnFinish=完成(&F)
BtnBrowse=浏览(&R)...
BtnNewFolder=新建文件夹(&M)

; ── 通用提示 ──
ConfirmTitle=确认
ErrorTitle=错误
InformationTitle=信息

; ── 错误 ──
SetupFileCorrupt=安装文件已损坏。请重新获取安装程序的完整副本。
SetupFileMissing=安装目录中缺少文件 %1。请修复该问题或重新获取安装程序的完整副本。
WinVersionTooLowError=此程序需要 %1 版本 %2 或更高版本。
AdminPrivilegesRequired=安装此程序时您必须以管理员身份登录。
DirDoesntExist=目录 %1 不存在。是否要创建该目录？
DirExists=目录 %1 已存在。是否仍安装到该目录？
InsufficientDiskSpaceLo=所选驱动器上的可用磁盘空间不足，无法安装所选文件。请释放一些磁盘空间，然后单击「重试」继续，或单击「取消」退出。

; ── 卸载 ──
UninstallStatusLabel=正在卸载 [name]，请稍候...
UninstallShouldUninstallLabel=是否卸载 [name]？
UninstallAppNotFound=无法找到 [name] 的安装。它可能已被卸载。%n%n单击「确定」关闭此对话框。
RunEntryExec=运行 [name]
RunEntryUninst=卸载 [name]

; ── 重启 ──
YesRadio=是，立即重新启动电脑(&Y)
NoRadio=否，稍后手动重新启动(&N)
