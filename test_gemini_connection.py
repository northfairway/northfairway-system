import unittest
from unittest.mock import patch, MagicMock
import nfh_ai_assistant as ai

class GeminiConnectionTests(unittest.TestCase):
    def test_unsupported_model_rejected(self):
        with self.assertRaises(ValueError):
            ai.gemini_connection_test('invalid-model')
    def test_missing_key_rejected(self):
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises((RuntimeError, ImportError)):
                ai.gemini_connection_test('gemini-2.5-flash-lite')

if __name__=='__main__': unittest.main()
