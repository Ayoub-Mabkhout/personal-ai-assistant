$ErrorActionPreference='Stop'
$assistantTaskName='PersonalAssistantServices'
Stop-ScheduledTask -TaskName $assistantTaskName
$assistantDeadline=(Get-Date).AddSeconds(15)
while ((Get-ScheduledTask -TaskName $assistantTaskName).State -eq 'Running') {
    if ((Get-Date) -gt $assistantDeadline) { throw 'Assistant service did not stop within 15 seconds.' }
    Start-Sleep -Milliseconds 200
}
Start-ScheduledTask -TaskName $assistantTaskName
$assistantDeadline=(Get-Date).AddSeconds(15)
while ((Get-ScheduledTask -TaskName $assistantTaskName).State -ne 'Running') {
    if ((Get-Date) -gt $assistantDeadline) { throw 'Assistant service did not start within 15 seconds.' }
    Start-Sleep -Milliseconds 200
}
Get-ScheduledTask -TaskName $assistantTaskName | Select-Object TaskName,State
