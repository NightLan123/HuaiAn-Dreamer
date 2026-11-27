"""Export the source registry and initial ED directions, without loading a persona."""
import ast
import csv
import json
from pathlib import Path

def build(root):
    registry=json.loads((root/'persona/construct_registry.json').read_text(encoding='utf-8'))
    disposition=json.loads((root/'persona/trait_disposition_registry.json').read_text(encoding='utf-8'))
    c=registry['constructs']
    groups=[('H',[f for d in c['hexaco_pi_r']['domains'] for f in d['facets']]+c['hexaco_pi_r']['interstitial_facets']),
        ('V',[v for g in c['schwartz_refined_values']['higher_order'] for v in g['values']]),
        ('I',c['interpersonal']['circumplex']),('L',c['linguistic_identity']['style_features']),('D',disposition['fields'])]
    tree=ast.parse((root/'persona/expression_drive.py').read_text(encoding='utf-8'));priors={}
    for node in ast.walk(tree):
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='trait_priors' for t in node.targets):priors=ast.literal_eval(node.value)
    rows=[]
    for block, fields in groups:
        for field in fields:
            identifier=field['id'];weights=priors.get(identifier,(0,0,0))
            rows.append({'id':identifier,'group':block,'label':field.get('name_zh',field.get('label',identifier)),
                'registry':'persona/trait_disposition_registry.json' if block=='D' else 'persona/construct_registry.json',
                'theory_reference':'docs/ARCHITECTURE.md',
                'source':'owner setting or scoped evidence; inspect actual profile source_type',
                'unknown':'null + mask 0; zero numerical contribution, not average personality',
                'a_b_path':'operative_personality + scoped persona views; context, not independent votes',
                'ed_path':'expression_drive.personality_baseline; initial W_theta column',
                'activation_prior':weights[0],'urgency_prior':weights[1],'persistence_prior':weights[2],
                'double_counting':'B utilities use shared context; local ED/action links separate, require ablation',
                'measurement_status':'engineering construct; not proof of independent psychometric validity'})
    return rows

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1];rows=build(root)
    with (root/'docs/CONSTRUCT_68_SOURCE_MAP.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print('Exported',len(rows),'source registry rows. No runtime persona loaded.')
