"""Offline packaging regressions for the reviewed Ollama v2 name mapping."""
import json
from pathlib import Path
import tempfile
import unittest

from package_candidate import reviewed_ollama_mapping

CHILD = 'd8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04'
LIST = '492e37dc69072c5a189a0cf21d32d844c983d599e4553a1e4d2ebd3f6b1299e2'
MEDIA = 'application/vnd.ollama.manifest.list.v2+json'
# Exact public 470-byte mapping; contains neither weights nor private cache data.
MAPPING = b'{"schemaVersion":2,"mediaType":"application/vnd.ollama.manifest.list.v2+json","manifests":[{"mediaType":"application/vnd.docker.distribution.manifest.v2+json","digest":"sha256:d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04","runner":"llamacpp","format":"gguf"},{"mediaType":"application/vnd.docker.distribution.manifest.v2+json","digest":"sha256:7f3251fa6878a78a606bcb3c074283306e5ad2ea411a7774a9dd98a4bc7f2d13","runner":"mlx","format":"safetensors"}]}'


class OllamaMappingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.relative = Path('manifests-v2/ollama.com/library/qwen3.5/4b')
        self.path = self.root / self.relative
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(MAPPING)
        self.refs = [{'digest': 'sha256:' + LIST, 'mediaType': MEDIA}]

    def test_exact_mapping_is_included(self):
        self.assertEqual(reviewed_ollama_mapping(self.root, self.refs, CHILD), (self.relative, LIST))

    def test_missing_mapping_fails_before_packaging(self):
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            reviewed_ollama_mapping(self.root, self.refs, CHILD)

    def test_altered_mapping_rejected(self):
        data = json.loads(MAPPING)
        data['manifests'][0]['digest'] = 'sha256:' + '0' * 64
        self.path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'Unexpected 4B v2 mapping'):
            reviewed_ollama_mapping(self.root, self.refs, CHILD)

    def test_unbound_list_rejected(self):
        with self.assertRaisesRegex(ValueError, 'list missing'):
            reviewed_ollama_mapping(self.root, [], CHILD)

    def test_other_selected_child_rejected(self):
        with self.assertRaisesRegex(ValueError, 'selected child differs'):
            reviewed_ollama_mapping(self.root, self.refs, '0' * 64)
