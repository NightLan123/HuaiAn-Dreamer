"""Regenerate the standalone PMM HTTP contract for both supported numeric models."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from persona.pmm import DIM,LATENT,SHAPES
from persona.learned_pmm import EXTRA_SHAPES,ADAPTER_SHAPES,RANK,MODEL_ID as LEARNED_ID
from persona.pmm_interface import CONTRACT,MODEL_ID
from persona.registry_pmm import DIM as FULL_DIM,SHAPES as FULL_SHAPES,EXTRA_SHAPES as FULL_EXTRA,ADAPTER_SHAPES as FULL_ADAPTER,MODEL_ID as REGISTRY_ID
from persona.registry import CONTRACT as REGISTRY_CONTRACT,N


def arr(n,minimum=-4,maximum=4):return {'type':'array','minItems':n,'maxItems':n,'items':{'type':'number','minimum':minimum,'maximum':maximum}}
def obj(properties,required=None):return {'type':'object','properties':properties,'required':list(properties) if required is None else required}
def params(shapes):
    result={}
    for key,shape in shapes.items():
        schema=arr(shape[-1],-100,100)
        if len(shape)==2:schema={'type':'array','minItems':shape[0],'maxItems':shape[0],'items':schema}
        result[key]=schema
    return {**obj(result),'additionalProperties':False}
def ref(name):return {'$ref':'#/components/schemas/'+name}
hexid={'type':'string','pattern':'^[a-f0-9]{32}$'};sha={'type':'string','pattern':'^[a-f0-9]{64}$'};count={'type':'integer','minimum':0}
common={'steps':count,'learned_samples':count,'samples':{'type':'array','maxItems':512,'items':{'type':'object'}},'metrics':{'type':'object'},'retrieval_weights':arr(4,0,1),'retrieval_labels':count}
legacy=obj({'format':{'const':'pmm/3'},'dimension':{'const':DIM},'latent':{'const':LATENT},'parameters':params(SHAPES),**common})
core=obj({'format':{'const':'pmm-core/2'},'dimension':{'const':DIM},'latent':{'const':LATENT},'parameters':params(SHAPES),'extra':params(EXTRA_SHAPES)})
adapter=obj({'format':{'const':'personal-adapter/2'},'id':hexid,'identity_id':hexid,'core_sha256':sha,'rank':{'const':RANK},'revision':count,'steps':count,'parameters':params(ADAPTER_SHAPES)})
learned=obj({'format':{'const':'learned-pmm/2'},'core':ref('SharedCore'),'core_sha256':sha,'core_steps':count,'core_origin':{'type':'string'},'adapter':ref('PersonalAdapter'),**common})
full_core=obj({'format':{'const':'pmm-core/2.1'},'dimension':{'const':FULL_DIM},'latent':{'const':LATENT},'registry_contract':{'const':REGISTRY_CONTRACT},'parameters':params(FULL_SHAPES),'extra':params(FULL_EXTRA),'feature_steps':{'type':'array','minItems':N,'maxItems':N,'items':count}})
full_adapter=obj({'format':{'const':'personal-adapter/2.1'},'id':hexid,'identity_id':hexid,'core_sha256':sha,'rank':{'const':RANK},'registry_contract':{'const':REGISTRY_CONTRACT},'revision':count,'steps':count,'parameters':params(FULL_ADAPTER),'feature_steps':{'type':'array','minItems':N,'maxItems':N,'items':count}})
full_model=obj({'format':{'const':'learned-pmm/2.1'},'registry_contract':{'const':REGISTRY_CONTRACT},'core':ref('RegistryCore'),'core_sha256':sha,'core_steps':count,'core_origin':{'type':'string'},'adapter':ref('RegistryAdapter'),'migration':{'type':'object'},**common})
base={'contract':{'const':CONTRACT},'request_id':hexid,'identity_id':hexid,'checkpoint_sha256':sha}
args={'encode':obj({'vectors':{'type':'array','minItems':1,'maxItems':512,'items':arr(DIM)}}),'decode':obj({'x':arr(DIM),'memory_vectors':{'type':'array','maxItems':40,'items':arr(DIM)}},['x']),'train':obj({'epochs':{'type':'integer','minimum':1,'maximum':150}},[]),'rank_feedback':obj({'components':arr(4,0,1),'relevant':{'type':'boolean'}}),'inspect':{'type':'object'}}
requests=[]
for model,checkpoint in ((MODEL_ID,'LegacyCheckpoint'),(LEARNED_ID,'LearnedCheckpoint'),(REGISTRY_ID,'RegistryCheckpoint')):
    for name,schema in args.items():
        if model in (LEARNED_ID,REGISTRY_ID) and name=='train':schema=obj({'epochs':{'type':'integer','minimum':1,'maximum':150},'target':{'enum':['adapter','core'],'default':'adapter'}},[])
        if model==REGISTRY_ID and name=='encode':schema=obj({'vectors':{'type':'array','minItems':1,'maxItems':512,'items':arr(FULL_DIM)}})
        if model==REGISTRY_ID and name=='decode':schema=obj({'x':arr(FULL_DIM),'memory_vectors':{'type':'array','maxItems':40,'items':arr(FULL_DIM)}},['x'])
        requests.append(obj({**base,'model':{'const':model},'checkpoint':ref(checkpoint),'operation':{'const':name},'arguments':schema}))
request={'oneOf':requests}
response=obj({**base,'model':{'enum':[MODEL_ID,LEARNED_ID,REGISTRY_ID]},'result':{},'checkpoint':ref('Checkpoint'),'next_checkpoint_sha256':sha},[*base,'model','result'])
json_response=lambda schema:{'description':'成功','content':{'application/json':{'schema':schema}}}
paths={'/health':{'get':{'operationId':'health','responses':{'200':json_response({'type':'object'})}}},'/v1/models':{'get':{'operationId':'models','responses':{'200':json_response({'type':'object'})}}},'/v1/pmm/execute':{'post':{'operationId':'execute','description':'Stateless computation on the supplied checkpoint. Writes return a candidate. Learned adapter updates must preserve the shared core.','requestBody':{'required':True,'content':{'application/json':{'schema':ref('ExecuteRequest')}}},'responses':{'200':json_response(ref('ExecuteResponse')),'400':{'description':'合约 / 参数错误'},'401':{'description':'认证失败'},'413':{'description':'请求超过32MB'},'429':{'description':'并发容量已满'},'500':{'description':'计算失败'}}}}}
spec={'openapi':'3.1.0','info':{'title':'Persona Dialogue PMM HTTP API','version':'2.1.0','description':'PMM HTTP/1 with registry learned-pmm/2.1, learned-pmm/2 and legacy pmm/3 checkpoints. This service computes numeric PMM; API-PMM uses the independently configured LLM provider.'},'servers':[{'url':'http://127.0.0.1:8766'}],'security':[{'PMMKey':[]}],'paths':paths,'components':{'securitySchemes':{'PMMKey':{'type':'http','scheme':'bearer'}},'schemas':{'Checkpoint':{'oneOf':[ref('LegacyCheckpoint'),ref('LearnedCheckpoint'),ref('RegistryCheckpoint')]},'RegistryCore':full_core,'RegistryAdapter':full_adapter,'RegistryCheckpoint':full_model,'LegacyCheckpoint':legacy,'SharedCore':core,'PersonalAdapter':adapter,'LearnedCheckpoint':learned,'ExecuteRequest':request,'ExecuteResponse':response}}}
path=Path(__file__).resolve().parents[1]/'docs/pmm-openapi.json';path.write_text(json.dumps(spec,ensure_ascii=False,indent=2)+'\n');print(path)
