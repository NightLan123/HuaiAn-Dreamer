"""Regression: shipped app.js must execute only after its referenced dialogs exist."""
from html.parser import HTMLParser
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class Scan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.order=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if 'id' in a:self.order.append(('id',a['id']))
        if tag=='script' and 'app.js' in a.get('src',''):self.order.append(('script',a['src'], 'defer' in a))

class HtmlBootRegression(unittest.TestCase):
    def test_main_script_runs_after_all_required_dialog_nodes(self):
        scan=Scan();scan.feed((ROOT/'web/index.html').read_text('utf-8'))
        scripts=[(n,v) for n,v in enumerate(scan.order) if v[0]=='script']
        self.assertEqual(len(scripts),1)
        script_i,script=scripts[0]
        self.assertTrue(script[2], 'app.js should be deferred')
        for element in ['dynamicBoundaryForm','brmCalibrationForm','editCharacter','retryLocal','psychologyPanel','chatLog']:
            indexes=[i for i,v in enumerate(scan.order) if v[:2]==('id',element)]
            self.assertEqual(len(indexes),1,f'missing/duplicate {element}')
            self.assertLess(indexes[0],script_i, f'{element} has not been parsed when app.js executes')

if __name__=='__main__':unittest.main()
