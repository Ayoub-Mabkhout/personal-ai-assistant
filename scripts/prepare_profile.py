"""Split confirmed legacy profile sections; import memories only as sourced candidates."""
import argparse
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
TOPICS={'Identity and contact':'identity','Household and relationships':'household',
    'Work and study':'work-and-study','Goals and routines':'goals-and-routines',
    'Food, shopping, travel, health, and accessibility':'shopping-and-finances',
    'Devices and information sources':'devices-and-accounts','Open questions':'open-questions',
    'Verified developer benefits':'education-benefits'}


def prepare(directory):
    directory=Path(directory)
    original=directory/'PROFILE.md'
    text=original.read_text(encoding='utf-8')
    sections=re.split(r'^## (.+)\n',text,flags=re.MULTILINE)
    created=[]
    for index in range(1,len(sections),2):
        title,body=sections[index:index+2]
        slug=TOPICS.get(title)
        if not slug:
            continue
        target=directory/(slug+'.md')
        if not target.exists():
            target.write_text('# '+title+'\n\nSource: existing PROFILE.md; user-confirmed facts and explicit unknowns.\n\n'+body.strip()+'\n',encoding='utf-8')
            created.append(slug)
    preferences=directory/'PREFERENCES.md'
    if preferences.exists() and not (directory/'assistant-preferences.md').exists():
        (directory/'assistant-preferences.md').write_text(preferences.read_text(encoding='utf-8'),encoding='utf-8')
        created.append('assistant-preferences')
    manifest={'display_name':None,'themes':[{'id':slug,'title':title,'file':slug+'.md'} for title,slug in TOPICS.items()],
        'memory_import_status':'No ChatGPT web memory imported. Existing project facts are sourced separately.',
        'originals_preserved':True}
    manifest['themes'].append({'id':'assistant-preferences','title':'Assistant preferences','file':'assistant-preferences.md'})
    path=directory/'manifest.json'
    if not path.exists():
        path.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    return {'themes_created':created,'original_profile_preserved':True}


def import_candidates(source,directory):
    source=Path(source).resolve()
    digest=__import__('hashlib').sha256(source.read_bytes()).hexdigest()
    output=Path(directory)/'memory-candidates'
    output.mkdir(parents=True,exist_ok=True)
    path=output/(digest+'.md')
    path.write_text('# Imported memory candidates\n\nStatus: unverified; review before promoting to profile facts.\n'
        f'Source: {source}\nSHA256: {digest}\n\n'+source.read_text(encoding='utf-8'),encoding='utf-8')
    return {'candidate_file':str(path),'promoted_to_confirmed_profile':False}


def import_chatgpt_profile(source,directory):
    import hashlib
    import shutil
    from datetime import datetime, timezone
    directory=Path(directory)
    imported_at=datetime.now(timezone.utc).date().isoformat()
    text=Path(source).read_text(encoding='utf-8')
    parts=re.split(r'^## (.+)\n',text,flags=re.MULTILINE)
    sections={int(re.match(r'(\d+)\.',parts[i])[1]):(parts[i],parts[i+1].strip().removesuffix('---').strip())
        for i in range(1,len(parts),2) if re.match(r'(\d+)\.',parts[i])}
    mappings=[('identity','Identity & background',[1]),('education','Education',[2]),
        ('thesis','Master\'s thesis',[3]),('work-and-career','Work & career',[4,19]),
        ('accounting-automation','Accounting automation',[5]),('engineering','Engineering & projects',[6,20]),
        ('devices','Devices & setup',[7]),('minecraft','Minecraft',[8]),('gaming','Gaming',[9,10]),
        ('films','Films & television',[11]),('music','Music',[12]),('languages','Languages & learning',[13,14]),
        ('outdoors','Alps & outdoor life',[15]),('fitness','Fitness',[16]),('health','Health & routines',[17]),
        ('housing-and-admin','Housing & administration',[18]),('intellectual-interests','Intellectual interests',[21]),
        ('communication','Communication preferences',[22]),('design','Design preferences',[23]),
        ('personal-details','Other personal details',[24]),('current-context','Recent context snapshots',[25])]
    sources=directory/'sources'
    sources.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(Path(source).read_bytes()).hexdigest()
    snapshot=sources/(digest+'-chatgpt-profile.md')
    if not snapshot.exists():
        shutil.copyfile(source,snapshot)
    def save(name, content):
        target=directory/name
        if target.exists() and target.read_text(encoding='utf-8') != content:
            history=sources/'theme-history'
            history.mkdir(exist_ok=True)
            previous=hashlib.sha256(target.read_bytes()).hexdigest()
            backup=history/(target.stem+'-'+previous+target.suffix)
            if not backup.exists():
                shutil.copy2(target,backup)
        target.write_text(content,encoding='utf-8')
    legacy=directory/'PROFILE.md'
    if legacy.exists() and not (sources/'project-profile-before-memory-import.md').exists():
        shutil.copy2(legacy,sources/'project-profile-before-memory-import.md')
    themes=[]
    for slug,title,numbers in mappings:
        header=f'# {title}\n\nSource: supplied ChatGPT profile, imported {imported_at}.\n'
        header+='Status: user-provided remembered context; dated snapshots may need reconfirmation.\n'
        if slug in ('health','fitness','housing-and-admin','current-context','thesis'):
            header+='Historical symptoms, deadlines and plans are not current assessments or active calendar commitments.\n'
        body='\n\n'.join('## '+sections[n][0]+'\n\n'+sections[n][1] for n in numbers if n in sections)
        save(slug+'.md',header+'\n'+body+'\n')
        themes.append({'id':slug,'title':title,'file':slug+'.md','sensitive':slug in ('health','housing-and-admin','identity')})
    for slug,title in [('shopping-and-finances','Shopping & finances'),('goals-and-routines','Assistant goals'),
        ('assistant-preferences','Assistant operating preferences')]:
        if (directory/(slug+'.md')).exists():
            themes.append({'id':slug,'title':title,'file':slug+'.md','sensitive':False})
    contact=sources/'project-profile-before-memory-import.md'
    if contact.exists():
        previous=contact.read_text(encoding='utf-8')
        match=re.search(r'## Identity and contact\n(.*?)(?=\n## |\Z)',previous,re.S)
        if match:
            body=match[1].replace('Languages and preferred name remain unconfirmed.',
                'Preferred name and language context are documented in identity.md from the newer supplied profile.')
            save('contact.md','# Contact details\n\nSource: prior direct user replies; original dated record preserved in sources/.\n'+body)
            themes.append({'id':'contact','title':'Contact details','file':'contact.md','sensitive':True})
    index=f'# Personal profile\n\nUser-supplied ChatGPT profile imported {imported_at}.\n'
    index+='Read the relevant theme instead of loading the whole profile. Original export and prior profile are preserved in sources/.\n'
    index+='Facts about other people explicitly excluded by the export are not added to these themes.\n'
    index+='Past deadlines, health notes and mutable work/study status remain snapshots until reconfirmed.\n\n'
    index+='## Overview\n\n'+sections.get(27,('', ''))[1]+'\n\n## Themes\n\n'
    index+='\n'.join('- ['+theme['title']+']('+theme['file']+')' for theme in themes)+'\n'
    save('PROFILE.md',index)
    identity=sections.get(1,('',''))[1]
    preferred=re.search(r'Preferred name:\s*\*\*(.+?)\*\*',identity)
    full=re.search(r'Full name encountered in prior conversations:\s*\*\*(.+?)\*\*',identity)
    manifest={'display_name':preferred[1] if preferred else None,'full_name':full[1] if full else None,'themes':themes,
        'highlights':['Work & learning','Life & routines','Interests & ideas'],
        'memory_import_status':f'Imported from your supplied ChatGPT profile on {imported_at}. Historical snapshots are labelled; excluded third-party memories are omitted.',
        'source':str(snapshot.relative_to(directory)),'source_sha256':digest,'originals_preserved':True}
    save('manifest.json',json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
    return {'themes':len(themes),'original_export_preserved':True,'excluded_context_not_imported':True}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=ROOT/'private/profile')
    parser.add_argument('--import-memory',type=Path)
    parser.add_argument('--chatgpt-profile',type=Path)
    args=parser.parse_args()
    result=import_chatgpt_profile(args.chatgpt_profile,args.directory) if args.chatgpt_profile else (
        import_candidates(args.import_memory,args.directory) if args.import_memory else prepare(args.directory))
    print(json.dumps(result,indent=2))
