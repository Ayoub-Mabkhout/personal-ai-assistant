param([Parameter(Mandatory=$true)][string]$Config)
$ErrorActionPreference='Stop'
$assistantConfigPath=(Resolve-Path -LiteralPath $Config).Path
$assistantSettings=Get-Content -LiteralPath $assistantConfigPath -Raw | ConvertFrom-Json
$assistantLauncher=Join-Path $assistantSettings.repository 'scripts/run_assistant_services.py'
$assistantPython=Join-Path (Split-Path -Parent $assistantSettings.python) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $assistantPython)) { throw 'The hidden Python launcher is unavailable.' }
$assistantSid=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$assistantEscape={param($Value) [System.Security.SecurityElement]::Escape($Value)}
$assistantArguments='"'+$assistantLauncher+'" --config "'+$assistantConfigPath+'"'
$assistantTaskXml=@"
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
 <RegistrationInfo><Description>Personal assistant: outbound worker and private local dashboard.</Description></RegistrationInfo>
 <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>$assistantSid</UserId></LogonTrigger></Triggers>
 <Principals><Principal id="Author"><UserId>$assistantSid</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
 <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>true</StartWhenAvailable><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure></Settings>
 <Actions Context="Author"><Exec><Command>$(& $assistantEscape $assistantPython)</Command><Arguments>$(& $assistantEscape $assistantArguments)</Arguments><WorkingDirectory>$(& $assistantEscape $assistantSettings.repository)</WorkingDirectory></Exec></Actions>
</Task>
"@
Register-ScheduledTask -TaskName 'PersonalAssistantServices' -Xml $assistantTaskXml -Force | Select-Object TaskName,State
Start-ScheduledTask -TaskName 'PersonalAssistantServices'
