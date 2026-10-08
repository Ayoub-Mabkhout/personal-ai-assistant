"""Portable repository skills, discoverable outside the repository working folder."""
from pathlib import Path
import re
import yaml


class SkillRepository:
    def __init__(self,repository):
        self.repository=Path(repository).resolve()
        self.root=self.repository/'skills'

    def catalog(self):
        result=[]
        for path in sorted(self.root.glob('*/SKILL.md')):
            if path.is_symlink() or not path.resolve().is_relative_to(self.root.resolve()):
                continue
            text=path.read_text(encoding='utf-8')
            sections=text.split('---',2)
            if len(sections)!=3 or sections[0].strip():
                raise ValueError('Invalid skill frontmatter: '+str(path))
            metadata=yaml.safe_load(sections[1])
            if not isinstance(metadata,dict) or metadata.get('name')!=path.parent.name:
                raise ValueError('Skill name must match its folder: '+str(path))
            if not re.fullmatch(r'[a-z0-9-]{1,64}',metadata['name']) or not isinstance(metadata.get('description'),str):
                raise ValueError('Invalid skill metadata: '+str(path))
            result.append({'name':metadata['name'],'description':metadata['description'],
                           'path':str(path.resolve())})
        return result

    def instructions(self,names):
        entries={entry['name']:entry for entry in self.catalog()}
        chunks=[]
        for name in dict.fromkeys(names):
            if name not in entries: raise ValueError('Unknown repository skill: '+name)
            path=Path(entries[name]['path'])
            chunks.append('REQUIRED SKILL '+name+'\nSource: '+str(path)+'\nRelative references resolve against '+str(path.parent)+'\n'+path.read_text(encoding='utf-8'))
        return '\n\n'.join(chunks)
