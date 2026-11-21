"""Conservative, local English/Filipino/Taglish abuse detection for HOA chatbot.

Keep the vocabulary reviewed and avoid substring matching. This is not a
comprehensive language classifier; ambiguous phrases are left to normal FAQs.
"""
import re
import unicodedata

WARNING_EN = ('Please use respectful and appropriate language when communicating through the '
              'NFH-HOA Chatbot. We are here to assist you with your HOA-related questions. '
              'Kindly rephrase your message.')
WARNING_TL = ('Pakigamit po ng magalang at angkop na pananalita sa pakikipag-usap gamit '
              'ang NFH-HOA Chatbot. Nandito po kami upang tumulong sa inyong mga katanungan '
              'tungkol sa HOA. Maaari po bang ayusin at muling ipadala ang inyong mensahe?')
WARNING_MIX = ('Paumanhin po, ngunit mangyaring gumamit ng respectful at appropriate na '
               'pananalita. Handa po kaming tumulong sa inyong HOA concerns. '
               'Pakirephrase na lamang po ang inyong message.')

# Explicit, high-confidence terms only. Avoid ambiguous short tokens like 'ass',
# 'puta', 'pota', 'gago' substrings occurring in names or regular words.
ENGLISH = {'fuck', 'fucker', 'fucking', 'motherfucker', 'shit', 'bullshit',
           'bitch', 'bastard', 'dickhead', 'asshole', 'wtf', 'stfu'}
FILIPINO = {'putangina', 'putangina mo', 'putang ina', 'putang ina mo',
            'putanginamo', 'tangina', 'tangina mo', 'tanginamo',
            'gago', 'gaga', 'gag0', 'ulol', 'tarantado', 'tarantada',
            'pakyu', 'pakyew', 'leche', 'lintik'}
LEET = str.maketrans({'0':'o', '1':'i', '3':'e', '4':'a', '5':'s', '7':'t', '@':'a', '$':'s'})
TOKEN = re.compile(r'[a-z0-9@\$]+', re.I)
# Only bridge symbols between substantial alphabetic chunks, not arbitrary words.
JOINED_EXPLICIT = re.compile(r'(?<![a-z0-9])(?:f[\W_]*u[\W_]*c[\W_]*k|s[\W_]*h[\W_]*i[\W_]*t|p[\W_]*a[\W_]*k[\W_]*y[\W_]*u)(?![a-z0-9])', re.I)
REPORT_CONTEXT = re.compile(r'\b(?:reported?|complain(?:t|ing)?|called me|said to me|sinabi|tinawag|nagmura|harass(?:ment|ed)?|insulted|quoted?)\b', re.I)


def normalize(text):
    text = unicodedata.normalize('NFKC', str(text or '')).casefold()
    text = ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))
    text = text.translate(LEET)
    words = TOKEN.findall(text)
    # Collapse long runs only; doubles can be legitimate spelling.
    words = [re.sub(r'(.)\1{2,}', r'\1', word) for word in words]
    return words


def detect(message):
    """Return warning language or None. Conservative for quoted complaints."""
    words = normalize(message)
    if not words:
        return None
    joined = ' '.join(words)
    english = any(word in ENGLISH for word in words)
    filipino = any(word in FILIPINO for word in words) or any(
        re.search(r'(?<!\w)' + re.escape(phrase) + r'(?!\w)', joined)
        for phrase in FILIPINO if ' ' in phrase
    )
    # Distinguish spaced letter obfuscation from everyday multiword phrases.
    if JOINED_EXPLICIT.search(unicodedata.normalize('NFKC', str(message)).casefold()):
        candidate = JOINED_EXPLICIT.search(unicodedata.normalize('NFKC', str(message)).casefold()).group()
        compact = re.sub(r'[^a-z]', '', candidate)
        english |= compact in {'fuck', 'shit'}
        filipino |= compact == 'pakyu'
    if not (english or filipino):
        return None
    # Quoted misconduct should reach HOA concern/help functionality where possible.
    if REPORT_CONTEXT.search(message):
        return None
    return 'taglish' if english and filipino else ('tagalog' if filipino else 'english')


def warning_for(message):
    language = detect(message)
    if language is None:
        return None
    return {'english': WARNING_EN, 'tagalog': WARNING_TL, 'taglish': WARNING_MIX}[language]
