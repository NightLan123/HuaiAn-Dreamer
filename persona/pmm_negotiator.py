"""PMM B task adapter: separate call, budget and result from event model A."""
from __future__ import annotations
import copy,time
from .common import dumps
from .api_pmm import BudgetedProvider
from . import deliberation as dl
from .expression_plan import ASSESS_INSTRUCTION

PROMPT='''[PMM_B_DELIBERATION_V281]
你是 PMM 内部讨论与认知协商模型 B。读取已经计算的情绪、慢心境、人格候选、记忆及关系，复核冲突并评估行动；不重新写入事件冲击，不改长期人格，不生成最终回复。只返回简短依据和结构化结果，不输出隐藏推理链。
可以额外返回 review 对象：weights 覆盖所有现有视角 id/weight，reject_ids，retrieval_queries，unresolved_conflict，summary。它只是本轮认知协商结果，不是新的事实证据。
'''

class Negotiator:
    def __init__(self,config,factory):
        from .pmm_connections import connection
        self.connection=connection(config,'B')
        self.provider=BudgetedProvider(factory(self.connection),self.connection['timeout'])
    def assess(self,context,views,records):
        from .validation import validated_call
        start=time.monotonic()
        def check(raw):
            assessment=dl.validate_assessment(raw,views)
            review=raw.get('review')
            dl.review(views,assessment,context['memories'],review)
            return {'assessment':assessment,'review':review}
        result=validated_call(self.provider,[{'role':'system','content':PROMPT+dl.ASSESS+ASSESS_INSTRUCTION},{'role':'user','content':dumps(context)}],check,records)
        assessment,review=result['assessment'],result['review']
        return assessment,review,{'status':'ok','executed':True,'role':'B','provider':self.connection['provider'],'model':self.connection['model'],
            'elapsed_ms':round((time.monotonic()-start)*1000,3),'input_summary':{'perspectives':len(views),'memory_count':len(context['memories']),
                'emotion_revision':context['emotion'].get('emotion_state',{}).get('state_revision'),'neural_received':bool(context.get('pmm_neural'))},
            'output_summary':{'view_ids':[x['id'] for x in assessment['views']],'review_present':review is not None},'applied_to':['policy','expression']}
