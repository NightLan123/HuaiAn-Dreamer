"""Manual offline entry. Reads an explicit model and labelled dataset only."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from persona.expression_drive_training import train_candidate

def main():
    parser=argparse.ArgumentParser(description='Fit an offline expression-drive candidate; never activate it')
    parser.add_argument('--model',type=Path,required=True);parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--epochs',type=int,default=50)
    args=parser.parse_args()
    result=train_candidate(json.loads(args.model.read_text(encoding='utf-8-sig')),json.loads(args.dataset.read_text(encoding='utf-8-sig')),args.epochs)
    # Exclusive create protects any existing trained artifact.
    with args.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False)
    print('Candidate saved. Runtime activation: false. Release eligibility: false.')

if __name__=='__main__':main()
