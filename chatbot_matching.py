"""Deterministic, conservative FAQ matching; no generated HOA facts."""
import re
import unicodedata
from difflib import SequenceMatcher

STOP = {'a','an','the','is','are','i','my','me','can','could','do','does','how','what','where','when','to','for','of','in','on','and','or','please','about','tell','you','your','with'}

def normalize(value):
    value = unicodedata.normalize('NFKC', str(value or '')).casefold()
    return ' '.join(re.findall(r'[a-z0-9]+', value))

def tokens(value):
    return set(normalize(value).split()) - STOP

def alternatives(row):
    return [row['question']] + [p.strip() for p in re.split(r'[,;\n]', row.get('keywords') or '') if p.strip()]

def match(question, rows, previous_id=None):
    q = normalize(question)
    if not q: return {'type':'empty'}
    ranked=[]
    for row in rows:
        scores=[]
        for phrase in alternatives(row):
            p=normalize(phrase)
            if not p: continue
            if q == p: scores.append(1.0);continue
            a,b=tokens(q),tokens(p)
            overlap=len(a & b)/len(a | b) if a and b else 0
            coverage=len(a & b)/max(1,len(a)) if a else 0
            fuzzy=SequenceMatcher(None,q,p).ratio()
            score=max(fuzzy * .90 if fuzzy>=.80 else 0, (.62*overlap+.38*coverage) if len(a&b)>=2 else 0)
            scores.append(score)
        if scores: ranked.append((max(scores),row))
    ranked.sort(key=lambda item:item[0],reverse=True)
    if not ranked or ranked[0][0]<.77:return {'type':'fallback'}
    top,row=ranked[0]
    if len(ranked)>1 and ranked[1][0]>=.77 and top-ranked[1][0]<.08:
        return {'type':'clarify','options':[r['question'] for _,r in ranked[:3]]}
    return {'type':'match','row':row,'score':round(top,3)}
