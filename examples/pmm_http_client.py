"""Manual example; run after starting run_pmm_service.py. No real user data."""
import os,sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from persona.pmm import vector
from persona.registry_pmm import RegistryPMM
from persona.registry import extend_vector
from persona.pmm_interface import RemotePMM
key=os.environ.get('PERSONA_PMM_API_KEY','')
if not key:
    key_file=Path.home()/'.persona_dialogue'/'pmm_service.key'
    if key_file.exists():key=key_file.read_text('utf8').strip()
if not key:raise SystemExit('请先启动服务，再设置 PERSONA_PMM_API_KEY 或使用默认密钥文件。')
identity=uuid.uuid4().hex
model=RemotePMM(RegistryPMM(identity=identity).export(),identity,{'base_url':os.environ.get('PERSONA_PMM_URL','http://127.0.0.1:8766'),'api_key':key,'model':'learned-pmm-v21','timeout':120})
print(model.test()['message'])
for i in range(5):model.add('synthetic-example-'+str(i),extend_vector(vector('测试问候'+str(i))),style=[.02,1,0,0,0,0,0,.2],source='synthetic_example')
model.fit(5)
print('仅用于接口演示的合成样本，训练步数：',model.info()['steps'])
print('解码结构字段：',list(model.decode(extend_vector(vector('你好')))))
