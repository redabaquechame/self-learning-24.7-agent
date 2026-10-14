import json,os,pathlib,subprocess,sys
root=pathlib.Path.cwd();scratch=root/'.superpowers/sdd/2026-10-13-native-host-ask'
env=os.environ.copy();sdk=pathlib.Path('C:/Users/redab/.cache/self-learning-native/dotnet-10.0.401')
env['DOTNET_ROOT']=str(sdk);env['PATH']=str(sdk)+os.pathsep+env['PATH'];env['DOTNET_CLI_TELEMETRY_OPTOUT']='1'
env['PYTHONUTF8']='1';env['PYTHONIOENCODING']='utf-8'
env['AGENT_BRIDGE_NESTED_TEST_OUTPUT']=str(scratch/'task2-native-nested-output.json')
def check(command,name):
 path=scratch/(name+'.log')
 with path.open('w',encoding='utf-8') as out:r=subprocess.run(command,stdout=out,stderr=subprocess.STDOUT,env=env)
 if r.returncode:
  print(path.read_text(encoding='utf-8',errors='replace')[-4000:]);raise SystemExit(r.returncode)
 print('PASS '+name,flush=True)
project='tests/native/ScreenTutor.ContractTests/ScreenTutor.ContractTests.csproj'
check([str(sdk/'dotnet.exe'),'build',project,'--no-restore','--configuration','Release'],'task2-final-native-build')
check([str(sdk/'dotnet.exe'),'run','--project',project,'--no-build','--no-restore','--configuration','Release'],'task2-final-native')
sys.path.insert(0,str(root));import tutor_transport as wire
for raw in json.loads((scratch/'task2-native-nested-output.json').read_text(encoding='utf-8')):
 wire.decode_message(bytes(range(32)),raw.encode('utf-8'),{'session_id':'session-1','bridge_epoch':2,'sequence':1,'cancellation_generation':0},1000)
print('PASS task2-final-native-to-Python-nested',flush=True)
for name in ['test_tutor_transport.py','test_tutor_host.py','test_tutor_native_session.py','test_tutor_contracts.py','test_tutor_gateway.py','test_tutor_feature_off.py']:
 check([sys.executable,'tests/'+name],'task2-final-'+name)
print('PASS Task2 local transport completion; real bootstrap/frame/Ask and full package acceptance remain',flush=True)
