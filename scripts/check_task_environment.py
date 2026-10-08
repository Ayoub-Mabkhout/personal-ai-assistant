"""Compile and execute small programs in a prepared private task environment."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess


def check(workspace):
    workspace=Path(workspace).resolve()
    environment=json.loads((workspace/'environment.json').read_text())
    directory=workspace/'.checks'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory.mkdir(parents=True)
    results={}
    env={**os.environ,'DOTNET_CLI_TELEMETRY_OPTOUT':'1','DOTNET_NOLOGO':'1'}
    def run(args):
        result=subprocess.run([str(x) for x in args],cwd=directory,env=env,capture_output=True,
            encoding='utf-8',errors='replace',timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        if result.returncode:
            raise RuntimeError(f'Toolchain exited with code {result.returncode}')
        return result.stdout.strip()
    def probe(name, action):
        try:
            output=action()
            if 'assistant-check-ok' not in output:
                raise RuntimeError('Expected program output missing')
            results[name]={'ok':True}
        except (OSError,RuntimeError,subprocess.TimeoutExpired) as exc:
            results[name]={'ok':False,'error':str(exc)}
    probe('python',lambda:run([environment['python'],'-c',
        'import sqlite3; assert sqlite3.connect(":memory:").execute("select 1").fetchone()[0]==1; print("assistant-check-ok")']))
    tools=environment['tools']
    if tools.get('node'):
        probe('javascript',lambda:run([tools['node'],'-e','console.log("assistant-check-ok")']))
        compiler=workspace/'node_modules/typescript/bin/tsc'
        if compiler.is_file():
            (directory/'check.ts').write_text('const result: string = "assistant-check-ok"; console.log(result);\n')
            def typescript():
                run([tools['node'],compiler,'check.ts','--outDir','compiled','--ignoreConfig'])
                return run([tools['node'],directory/'compiled/check.js'])
            probe('typescript',typescript)
    if tools.get('javac'):
        (directory/'AssistantCheck.java').write_text('public class AssistantCheck { public static void main(String[] args) { System.out.println("assistant-check-ok"); } }\n')
        def java():
            run([tools['javac'],'AssistantCheck.java'])
            return run([Path(tools['javac']).parent/'java.exe' if os.name=='nt' else 'java','-cp',directory,'AssistantCheck'])
        probe('java',java)
    if tools.get('dotnet'):
        def dotnet():
            major=run([tools['dotnet'],'--version']).split('.')[0]
            (directory/'check.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType>'
                f'<TargetFramework>net{major}.0</TargetFramework></PropertyGroup></Project>')
            (directory/'Program.cs').write_text('System.Console.WriteLine("assistant-check-ok");\n')
            return run([tools['dotnet'],'run','--project','check.csproj','--verbosity','quiet'])
        probe('csharp',dotnet)
    if tools.get('pwsh'):
        probe('powershell',lambda:run([tools['pwsh'],'-NoProfile','-NonInteractive','-Command',"Write-Output 'assistant-check-ok'"]))
    record={'checked_at':datetime.now(timezone.utc).isoformat(),'results':results,
        'missing_tools':[name for name in ('go','rustc','cargo') if not tools.get(name)],'check_workspace':str(directory)}
    (workspace/'checks.json').write_text(json.dumps(record,indent=2)+'\n')
    return record


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,required=True)
    result=check(parser.parse_args().workspace)
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if all(item['ok'] for item in result['results'].values()) else 1)
