"""Private per-athlete narrative and searchable conversation journal."""
import os
from pathlib import Path


def directory(config, user_id=None):
    from .tools import workout_path
    root = Path(config.get('workout_runtime_dir', str(Path.home()/'.personal-assistant/workout')))
    if user_id and user_id != 'owner':
        workout_path(user_id)
        root = root/'members'/user_id
    return root/'memory'


def save(config, identifier, question, answer, narrative):
    root = directory(config)
    root.mkdir(parents=True, exist_ok=True)
    for name, text in {
        'facts.md': narrative,
        identifier+'.md': '# Request\n\n'+question+'\n\n# Answer\n\n'+answer,
    }.items():
        if Path(name).name != name:
            raise ValueError('Invalid memory identifier')
        path = root/name
        temp = path.with_suffix('.tmp')
        temp.write_text(text, encoding='utf-8')
        os.replace(temp, path)


def search(config, user_id, query, offset=0, limit=10):
    if not isinstance(query,str) or not 1 <= len(query) <= 200:
        raise ValueError('Supply a memory query of 1..200 characters')
    if offset < 0 or not 1 <= limit <= 20:
        raise ValueError('Invalid memory page')
    matches = []
    for path in sorted(directory(config, user_id).glob('*.md')):
        for paragraph in path.read_text(encoding='utf-8').split('\n\n'):
            if query.casefold() in paragraph.casefold():
                matches.append({'source':path.name, 'text':paragraph[:4000]})
    return {'matches':matches[offset:offset+limit], 'total':len(matches)}
