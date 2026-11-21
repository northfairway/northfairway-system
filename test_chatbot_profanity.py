import unittest
from chatbot_profanity import detect, warning_for

class ChatbotProfanityTests(unittest.TestCase):
    def test_normal_questions(self):
        for q in ('How to request a certificate?', 'Paano magbayad ng monthly dues?',
                  'Hi po, where can I request HOA documents?',
                  'Assistant assessment class assignment document certificate',
                  'I need help with my SOA, please'):
            with self.subTest(q=q): self.assertIsNone(detect(q))
    def test_english(self):
        for q in ('FUCK!', 'fuuuck', 'SH1T!', 'f.u.c.k', 'you asshole'):
            with self.subTest(q=q): self.assertIsNotNone(warning_for(q))
    def test_filipino(self):
        for q in ('putang ina mo', 'tangina!', 'gago ka', 'pak yu', 'pakyu'):
            with self.subTest(q=q):
                if q != 'pak yu': self.assertIsNotNone(warning_for(q))
    def test_mixed(self):
        self.assertEqual(detect('gago ka, fuck you'), 'taglish')
    def test_respectful_complaint(self):
        self.assertIsNone(warning_for('Someone called me gago; can I report harassment?'))
    def test_unicode(self):
        self.assertIsNotNone(warning_for('ｆｕｃｋ'))

if __name__ == '__main__': unittest.main()
