import os,pathlib,subprocess,sys
root=pathlib.Path.cwd();scratch=root/'.superpowers/sdd/2026-10-13-native-host-ask'
sdk=pathlib.Path('C:/Users/redab/.cache/self-learning-native/dotnet-10.0.401');env=os.environ.copy()
env['DOTNET_ROOT']=str(sdk);env['PATH']=str(sdk)+os.pathsep+env['PATH'];env['DOTNET_CLI_TELEMETRY_OPTOUT']='1';env['PYTHONUTF8']='1';env['PYTHONIOENCODING']='utf-8'
env['AGENT_TUTOR_NATIVE_FIXTURE']=str(root/'tests/native/ScreenTutor.ContractTests/bin/Release/net10.0-windows10.0.26100.0/win-x64/ScreenTutor.ContractTests.exe')
env['AGENT_TUTOR_NATIVE_APP']=str(root/'companion/windows/ScreenTutor/bin/Release/net10.0-windows10.0.26100.0/win-x64/ScreenTutor.exe')
env['AGENT_TUTOR_CONNECTION_RECEIPT']=str(scratch/'task3-final-processes.json')
def check(command,name):
 path=scratch/(name+'.log')
 with path.open('w',encoding='utf-8') as out:r=subprocess.run(command,stdout=out,stderr=subprocess.STDOUT,env=env)
 if r.returncode:
  print(path.read_text(encoding='utf-8',errors='replace')[-4000:]);raise SystemExit(r.returncode)
 print('PASS '+name,flush=True)
project='tests/native/ScreenTutor.ContractTests/ScreenTutor.ContractTests.csproj'
check([str(sdk/'dotnet.exe'),'build',project,'--no-restore','--configuration','Release'],'task3-final-native-build')
check([str(sdk/'dotnet.exe'),'run','--project',project,'--no-build','--no-restore','--configuration','Release'],'task3-final-native')
for name in ['test_tutor_connection.py','test_tutor_host.py','test_tutor_transport.py','test_tutor_native_session.py','test_tutor_feature_off.py']:
 check([sys.executable,'tests/'+name],'task3-final-'+name)
print('PASS Task3 local startup completion; memory frames/visible Ask/full acceptance remain',flush=True)
