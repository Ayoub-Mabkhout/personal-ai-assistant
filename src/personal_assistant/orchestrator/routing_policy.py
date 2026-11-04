"""Deterministic account choice and explicit routing constraints; no model calls.

This is an owner's allowance policy, not a benchmark of model capability. The
classifier still selects a suitable model/effort within the chosen account.
"""
from datetime import datetime,timezone
from functools import lru_cache
import math
import re
import time
import unicodedata


UNKNOWN_HEADROOM=20.0
STALE_MINUTES=60
# Allowance only falls until its window resets, so an old reading is an upper bound; it is capped because
# other work may have used it since. A window that has reset since the reading is mostly fresh again.
STALE_CAP=60.0
RESET_HEADROOM=60.0
_QUOTED=re.compile(r'```[\s\S]*?```|`[^`\n]*`|"[^"\n]*"|(?<!\w)\'[^\'\n]*\'(?!\w)|^\s*>[^\n]*',re.MULTILINE)
_DIRECT=re.compile(r'\b(?:use|choose|select|pick|prefer|avoid|switch\s+to|(?:route|dispatch|delegate)\s+(?:this\s+)?to)\s+(?:(?:the\s+)?(?:model|agent)\s*[:=]?\s*)?')
_RUN=re.compile(r'\b(?:run|do|execute|process|handle|send)\b[^\n.;!?]{0,100}?\b(?:with|via|using|on|to)\s+')
_FIELD=re.compile(r'\b(?:model|agent)\s*[:=]\s*')
_LET=re.compile(r'\blet\s+')
_EFFORT_WORD=r'(?:extra[\s_-]*high|x[\s_-]*high|maximum|max|ultra|medium|high|low)'
_EFFORT_FIELD=re.compile(r'\b(?:effort|reasoning(?:\s+effort)?)\s*(?:[:=]|(?:to|is)\s+)\s*('+_EFFORT_WORD+r')\b')
_EFFORT_USE=re.compile(r'\b(?:use|set|choose|prefer|avoid)\s+('+_EFFORT_WORD+r')\s+(?:reasoning\s+)?effort\b')
_EFFORT_TAIL=re.compile(r'\s*(?:at|with|on)\s+(?:effort\s+)?('+_EFFORT_WORD+r')\b|\s+('+_EFFORT_WORD+r')\s+(?:reasoning\s+)?effort\b')
_NEGATED=re.compile(r"(?:don'?t|do\s+not|never|avoid|without|not(?:\s+to)?|rather\s+than)\s+(?:\w+\s+){0,3}$")
_HYPOTHETICAL=re.compile(r'\b(?:should\s+i|whether(?:\s+to)?|if\s+(?:i|we)|when\s+(?:i|we)|why|compare|comparison|difference)\b')
_MAIL_ACTION=re.compile(r'\b(?:find|search|read|open|reply|respond|send|draft|forward|download|check)\b')
_MAIL_NOUN=re.compile(r'\b(?:e[\s-]?mails?|gmail|outlook|inbox|mailbox)\b')


def clean_text(text):
    if not isinstance(text,str):raise ValueError('Routing needs the original request text.')
    text=unicodedata.normalize('NFKC',text).casefold()
    text=text.translate(str.maketrans({'–':'-','—':'-','−':'-','’':"'",'‘':"'",'“':'"','”':'"'}))
    return _QUOTED.sub(lambda match:' '*len(match[0]),text)


def _prefix(text,start):
    return re.split(r'[.;!?\n,]',text[:start])[-1][-150:]


def _polarity(text,start,verb=''):
    prefix=_prefix(text,start)
    if _HYPOTHETICAL.search(prefix):return None
    return -1 if verb.startswith('avoid') or _NEGATED.search(prefix) else 1


def _pattern(value):
    return r'[\s._-]*'.join(re.escape(part) for part in re.split(r'[\s._-]+',value))


@lru_cache(maxsize=16)
def _targets(models):
    aliases=[];families={}
    for model in models:
        aliases.append((_pattern(model),'model',model))
        match=re.fullmatch(r'gpt-(\d+(?:\.\d+)?)-(\w+)',model)
        if match:
            version,family=match.groups();families.setdefault(family,[]).append((tuple(map(int,version.split('.'))),model))
            aliases.append((_pattern(family+' '+version),'model',model))
        match=re.fullmatch(r'claude-(\w+)-(\d+)-(\d+)',model)
        if match:
            family,major,minor=match.groups();families.setdefault(family,[]).append(((int(major),int(minor)),model))
            aliases.append((_pattern(family+' '+major+'.'+minor),'model',model))
    for family,versions in families.items():
        model=max(versions)[1]
        aliases.append((r'(?:(?:gpt|claude)[\s_-]+)?'+re.escape(family),'model',model))
    aliases.extend(((r'codex|open[\s_-]*ai|gpt','agent','codex'),(r'claude(?:\s+code)?|anthropic','agent','claude')))
    return tuple((re.compile('(?:'+pattern+r')(?![\w.])'),kind,value) for pattern,kind,value in aliases)


def _target(text,start,patterns):
    matches=[(match.end(),kind,value) for pattern,kind,value in patterns if (match:=pattern.match(text,start))]
    if not matches:return None
    end,kind,value=max(matches,key=lambda item:(item[0],item[1]=='model'))
    # Do not silently drop an explicitly written unsupported version after a bare alias.
    if re.match(r'[\s._-]*\d',text[end:]):raise ValueError('The requested model version is not in the configured catalog.')
    return end,kind,value


def _effort(value):
    value=re.sub(r'[\s_-]','',value)
    return {'extrahigh':'xhigh','xhigh':'xhigh','maximum':'max'}.get(value,value)


def explicit_preferences(text,profiles):
    text=clean_text(text);patterns=_targets(tuple(sorted({p['model'] for p in profiles.values()})))
    positives={'agent':set(),'model':set(),'effort':set()};negatives={key:set() for key in positives}
    def add(kind,value,polarity):
        if polarity is not None:(positives if polarity>0 else negatives)[kind].add(value)
    for matcher in (_DIRECT,_RUN,_FIELD,_LET):
        for directive in matcher.finditer(text):
            polarity=_polarity(text,directive.start(),directive[0]);target=_target(text,directive.end(),patterns)
            if not target or polarity is None:continue
            end,kind,value=target
            if matcher is _LET and not re.match(r'\s+(?:handle|do|take|process|run|work|answer)\b',text[end:]):continue
            add(kind,value,polarity)
            tail=_EFFORT_TAIL.match(text,end)
            if tail:add('effort',_effort(tail[1] or tail[2]),polarity)
            # A choice between two models is not one unambiguous worker preference.
            alternative=re.match(r'\s*(?:or|and|/)\s*',text[end:])
            if alternative:
                another=_target(text,end+alternative.end(),patterns)
                if another:add(another[1],another[2],polarity)
    for matcher in (_EFFORT_FIELD,_EFFORT_USE):
        for match in matcher.finditer(text):add('effort',_effort(match[1]),_polarity(text,match.start(),match[0]))
    if any(len(values)>1 for values in positives.values()):raise ValueError('Conflicting explicit routing preferences; choose one model, agent and effort.')
    result={kind:next(iter(values)) for kind,values in positives.items() if values}
    result.update({'excluded_'+kind+'s':sorted(values) for kind,values in negatives.items() if values})
    if result.get('model'):
        agents={p['agent'] for p in profiles.values() if p['model']==result['model']}
        if len(agents)!=1:raise ValueError('Requested model has no unique configured agent.')
        agent=next(iter(agents))
        if result.get('agent',agent)!=agent:raise ValueError('Explicit model and agent conflict.')
        result['agent']=agent
    return result,text


def _number(value):
    return float(value) if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) else None


def _window(reading,name,now):
    value=reading.get(name);value=value if isinstance(value,dict) else {}
    remaining=_number(value.get('remaining_percent',reading.get(name+'_remaining_percent')))
    if remaining is not None and not 0<=remaining<=100:remaining=None
    reset=_number(value.get('resets_in_minutes',reading.get(name+'_resets_in_minutes')))
    if reset is None and value.get('resets_at'):
        try:
            stamp=datetime.fromisoformat(value['resets_at'].replace('Z','+00:00'))
            if stamp.tzinfo:reset=(stamp.timestamp()-now)/60
        except (TypeError,ValueError):pass
    reset_observed=value.get('reset_since_observed') is True or reading.get(name+'_reset_since_observed') is True
    return remaining,reset,reset_observed


def account_score(reading,availability,*,now):
    reading=reading if isinstance(reading,dict) else {}
    if availability is False or (isinstance(availability,dict) and availability.get('usable') is False):return None
    windows=[_window(reading,name,now) for name in ('five_hour','weekly')]
    if any(remaining==0 and not reset for remaining,_,reset in windows):return None
    if reading.get('limit_reached') and not any(reset for _,_,reset in windows):return None
    age=_number(reading.get('observed_minutes_ago'))
    stale=age is not None and age>STALE_MINUTES
    headroom=[];unknown=0
    for remaining,reset,observed in windows:
        if remaining is None or reading.get('available') is False:
            headroom.append(UNKNOWN_HEADROOM);unknown+=1
        elif observed:
            headroom.append(RESET_HEADROOM);unknown+=1
        elif stale:
            headroom.append(min(remaining,STALE_CAP));unknown+=1
        else:headroom.append(remaining)
    five,weekly=headroom
    score=.70*min(five,weekly)+.15*(five+weekly)-5*unknown
    if not stale and reading.get('available') is not False:
        for index,(maximum,horizon) in enumerate(((12,60),(8,1440))):
            remaining,reset,_=windows[index]
            other=headroom[1-index]
            if remaining is not None and reset is not None and 0<=reset<horizon:
                score+=maximum*(1-reset/horizon)*min(1,other/25)
    return round(score,4)


def _mail_required(text):
    for clause in re.split(r'[.;!?\n]',text):
        nouns=list(_MAIL_NOUN.finditer(clause));actions=list(_MAIL_ACTION.finditer(clause))
        if any(abs(noun.start()-action.start())<=120 and _polarity(clause,action.start())==1
               for noun in nouns for action in actions):return True
    return False


def select(body,profiles,*,now=None):
    """Select one usable account and return only its allowed model/effort choices."""
    if not profiles:raise ValueError('The routing model catalog is empty.')
    explicit,text=explicit_preferences(body.get('user_request'),profiles)
    mail=_mail_required(text)
    if mail and explicit.get('agent') not in (None,'codex'):raise ValueError('Email tasks need the Codex mailbox tools; the explicit agent cannot provide them.')
    eligible={name:p for name,p in profiles.items() if
        all(p[k]==explicit[k] for k in ('agent','model','effort') if k in explicit)
        and all(p[k] not in explicit.get('excluded_'+k+'s',[]) for k in ('agent','model','effort'))
        and (not mail or p['agent']=='codex')}
    if not eligible:raise ValueError('No configured worker satisfies the explicit routing constraints.')
    capacity=body.get('agent_capacity') or {};availability=body.get('agent_availability') or {}
    now=time.time() if now is None else now
    scores={agent:account_score(capacity.get(agent),availability.get(agent),now=now) for agent in ('codex','claude')}
    agents={p['agent'] for p in eligible.values() if scores.get(p['agent']) is not None}
    if not agents:raise ValueError('No allowed agent is currently available; nothing was dispatched.')
    agent=max(sorted(agents,reverse=True),key=lambda name:scores[name])
    selected={name:p for name,p in eligible.items() if p['agent']==agent}
    return {'agent':agent,'profiles':selected,'explicit':explicit,'scores':scores,
            'reason':'mail_tools' if mail else 'explicit_preference' if explicit else 'capacity_and_reset'}
