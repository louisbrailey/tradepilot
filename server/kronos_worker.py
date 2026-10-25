"""Isolated offline inference process; stdin contains public price history only."""
import contextlib
import json
import sys


def main():
    payload = json.load(sys.stdin)
    sys.path.insert(0, sys.argv[1])
    with contextlib.redirect_stdout(sys.stderr):
        import numpy as np
        import pandas as pd
        import torch
        from model import Kronos, KronosTokenizer, KronosPredictor
        torch.set_num_threads(4)
        tokenizer = KronosTokenizer.from_pretrained('NeoQuasar/Kronos-Tokenizer-base', local_files_only=True)
        model = Kronos.from_pretrained('NeoQuasar/Kronos-small', local_files_only=True)
        predictor = KronosPredictor(model, tokenizer, device='cpu', max_context=512)
        frame = pd.DataFrame(payload['history']).rename(columns={'o':'open','h':'high','l':'low','c':'close','v':'volume'})
        x = pd.Series(pd.to_datetime(frame['t'], unit='ms', utc=True).dt.tz_convert('America/New_York').dt.tz_localize(None))
        y = pd.Series(pd.to_datetime(payload['dates'], unit='ms', utc=True).tz_convert('America/New_York').tz_localize(None))
        paths = []
        for sample in range(payload['samples']):
            torch.manual_seed(42+sample)
            np.random.seed(42+sample)
            forecast = predictor.predict(df=frame[['open','high','low','close','volume']], x_timestamp=x,
                y_timestamp=y, pred_len=len(y), T=1.0, top_p=0.9, sample_count=1)
            paths.append([float(v) for v in forecast['close']])
    print(json.dumps({'paths':paths}, allow_nan=False))


if __name__ == '__main__':
    main()
