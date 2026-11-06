"""Download public pinned weights; set offline default refs for the existing worker."""
from pathlib import Path
from huggingface_hub import snapshot_download

MODELS = {
    'NeoQuasar/Kronos-small': '901c26c1332695a2a8f243eb2f37243a37bea320',
    'NeoQuasar/Kronos-Tokenizer-base': '0e0117387f39004a9016484a186a908917e22426',
}

for model, revision in MODELS.items():
    snapshot = Path(snapshot_download(model, revision=revision, allow_patterns=['*.json', '*.safetensors']))
    refs = snapshot.parent.parent/'refs'
    refs.mkdir(exist_ok=True)
    (refs/'main').write_text(revision)
print('Pinned public Kronos weights cached for offline inference.')
