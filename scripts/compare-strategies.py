#!/usr/bin/env python3
"""Offline fixed-rule comparison; only reads exact private cached snapshots."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
from strategies import compare_strategies, VERSION
spec=importlib.util.spec_from_file_location('frozen_evaluator',ROOT/'scripts/evaluate-strategies.py')
evaluator=importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-dir',required=True)
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--start',default='2022-01-01')
    parser.add_argument('--end',default='2026-09-11')
    args=parser.parse_args()
    cache=Path(args.cache_dir).expanduser()
    # Do not create or mutate the existing cache or its observation ledger.
    if not cache.is_dir() or cache.is_symlink(): raise ValueError('Existing private cache required')
    info=cache.stat()
    import os
    if info.st_uid != os.getuid() or info.st_mode & 0o077: raise ValueError('Cache must be owner-only')
    report={'version':VERSION,'generated_at':datetime.now(timezone.utc).isoformat(),
            'evidence':'exploratory_previously_observed','symbols':{},'errors':{},
            'implementation_sha256':{str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
                                     for path in (ROOT/'server/strategies.py',ROOT/'server/research.py',Path(__file__))}}
    for ticker in evaluator.SYMBOLS:
        try:
            payload=evaluator.acquire(None,ticker,args.start,args.end,cache,True)
            rows=evaluator.validated_bars(payload['rows'],args.start,args.end)
            report['symbols'][ticker]={'source':{key:payload.get(key) for key in
                ('ticker','start','end','retrieved_at','raw_rows_sha256','adjusted')},'comparison':compare_strategies(rows)}
        except (ValueError,KeyError,OSError) as error:
            report['errors'][ticker]=str(error)
    output=Path(args.output_dir)
    output.mkdir(parents=True,exist_ok=True)
    (output/'SUMMARY.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    lines=['# Exploratory daily strategy comparison','',
           'Already-observed history; this is not a fresh holdout, a recommendation, or evidence of deployability. No parameters were optimized. The first 60% supplies warm-up only, followed by 20% validation and 20% final descriptive periods. Each starts in cash independently. Costs are 0, 10, 25 and 50 bps per side. The table uses 10 bps.','',
           '| Symbol | Fixed strategy | Validation return % | Final return % | Final benchmark % | Final drawdown % | Final fills |',
           '|---|---|---:|---:|---:|---:|---:|']
    for ticker,item in report['symbols'].items():
        for rule in item['comparison']['strategies']:
            v,f=rule['validation']['baseline'],rule['final']['baseline']
            lines.append(f"| {ticker} | {rule['strategy']} | {v['return_pct']:.2f} | {f['return_pct']:.2f} | {f['benchmark_price_return_pct']:.2f} | {f['max_drawdown_pct']:.2f} | {f['fills']} |")
    lines += ['','Input hashes, source retrieval times, implementation hashes, dates, rules and all cost scenarios are in SUMMARY.json. Original reports and cache are unchanged. Legacy adjustment flags are unknown; no envelope metadata has been invented. Raw licensed bars are excluded.', '',
              'Daily price returns omit dividends and therefore cannot evaluate dividend optimization. No short/borrow, options, FX, crypto, intraday, taxes, cash interest, volume/market-impact model or news strategy is tested. Surviving securities and correlated assets limit inference. Prospective paper observation remains necessary.']
    if report['errors']: lines += ['', 'Unavailable: '+json.dumps(report['errors'])]
    (output/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'symbols':len(report['symbols']),'errors':report['errors'],'output':str(output)}))
    return bool(report['errors'])

if __name__=='__main__':sys.exit(main())
