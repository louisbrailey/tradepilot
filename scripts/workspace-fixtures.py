"""Build synthetic server contract fixtures for the native decoding smoke check."""
import json
import sys
import tempfile
import time
from pathlib import Path
from paper_service import PaperService
from strategies import compare_strategies

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as directory:
    service = PaperService(Path(directory)/'paper.sqlite3')
    review = service.create_review(dict(symbol='AAPL',side='buy',quantity='2',client_id='fixture-1234'),
        dict(symbol='AAPL',price='100',as_of=time.time()-3600,source='Synthetic fixture',delayed=True))
    receipt = service.confirm(dict(id=review['id'],token=review['token'],approved=True))
    service.add_note({'text':'Synthetic reflection'})
    for name, value in [('review',review),('receipt',receipt),('state',service.state())]:
        (out/(name+'.json')).write_text(json.dumps(value))
bars=[dict(t=1600000000000+i*86400000,o=100+i/10,h=102+i/10,l=99+i/10,c=101+i/10) for i in range(180)]
(out/'strategies.json').write_text(json.dumps({**compare_strategies(bars),'ticker':'AAPL'}))

from paper_automation import AutomationService
from datetime import datetime
from zoneinfo import ZoneInfo
import uuid
with tempfile.TemporaryDirectory() as directory:
    service = AutomationService(Path(directory)/'automation.sqlite3', clock=lambda: datetime(2026,11,5,21,tzinfo=ZoneInfo('America/New_York')).timestamp())
    state = service.start({'client_id': str(uuid.uuid4()), 'approved': True})
    (out/'automation.json').write_text(json.dumps(state))
