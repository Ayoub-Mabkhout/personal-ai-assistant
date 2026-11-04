"""Evaluate routing: code's account choice for every case, then live Jev model choice within that account.

Usage: python scripts/jev_eval.py [--split heldout|dev|all] [--repeat N] [--code-only] [--key-file PATH]
Labels in jev_eval_cases.json are the owner's acceptable ranges, not ground truth. Reports go to state/jev-eval/.
"""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from personal_assistant.orchestrator import routing_policy  # noqa: E402
from personal_assistant.orchestrator.jev import PROFILES, JevError, Router  # noqa: E402
from personal_assistant.skill_repository import SkillRepository  # noqa: E402

TIERS = {'gpt-6-luna': 0, 'claude-haiku-5-5': 0, 'claude-sonnet-5-5': 1, 'gpt-6.1-terra': 1,
         'gpt-6-sol': 2, 'gpt-6.1-sol': 2, 'claude-opus-5-5': 2, 'gpt-6-astra': 3, 'claude-fable-5-1': 4}
NAMES = {'light': 0, 'practical': 1, 'top': 2, 'exceptional': 3}


def body(case, scenarios, skills):
    return {'user_request': case['request'], 'agent_capacity': scenarios[case['scenario']],
            'agent_availability': {'codex': {'usable': True}, 'claude': {'usable': True}},
            'attachments': case.get('attachments', []), 'skill_catalog': skills, 'dev_forwarding': {'available': False}}


def check(case, routed, choice):
    """Each failed expectation as a short label; an empty list is a pass."""
    problems = []
    if 'account' in case and routed['agent'] != case['account']: problems.append('account:' + routed['agent'])
    if choice is None: return problems
    if choice['agent'] != routed['agent']: problems.append('left-account')
    tier = TIERS[choice['model']]
    if 'model' in case and choice['model'] != case['model']: problems.append('ignored-model:' + choice['model'])
    if 'effort' in case and choice['effort'] != case['effort']: problems.append('ignored-effort:' + choice['effort'])
    if 'min' in case and tier < NAMES[case['min']]: problems.append('under:' + choice['model'])
    if 'max' in case and tier > NAMES[case['max']]: problems.append('over:' + choice['model'])
    if tier == 4 and case.get('model') != 'claude-fable-5-1': problems.append('unrequested-fable')
    if 'task_type' in case and choice['task_type'] not in case['task_type']: problems.append('task_type:' + choice['task_type'])
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split', default='heldout', choices=('heldout', 'heldout2', 'dev', 'all'))
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--code-only', action='store_true', help='Check account selection only; no Jev calls.')
    parser.add_argument('--key-file', help='Absolute path to the protected Jev key file.')
    args = parser.parse_args()
    spec = json.loads((ROOT / 'scripts' / 'jev_eval_cases.json').read_text(encoding='utf-8'))
    cases = [c for c in spec['cases'] if args.split == 'all' or c['split'] == args.split]
    skills = [{k: s[k] for k in ('name', 'description')} for s in SkillRepository(ROOT).catalog()]
    router = None if args.code_only else Router({'jev_api_key_file': args.key_file} if args.key_file else {})
    rows = []
    for case in cases:
        for attempt in range(1 if args.code_only else args.repeat):
            request = body(case, spec['scenarios'], skills)
            row = {'id': case['id'], 'group': case['group'], 'attempt': attempt}
            try:
                routed = routing_policy.select(request, PROFILES)
            except ValueError as error:
                row.update(problems=['code-refused:' + str(error)]); rows.append(row); continue
            choice = None
            if router:
                started = time.monotonic()
                try:
                    choice = router.decide(request)
                except JevError as error:
                    row.update(problems=['jev-error:' + str(error)], latency=round(time.monotonic() - started, 2)); rows.append(row); continue
                row['latency'] = round(time.monotonic() - started, 2)
                row['choice'] = {k: choice[k] for k in ('agent', 'model', 'effort', 'task_type', 'confidence')}
            row.update(account=routed['agent'], reason=routed['reason'], problems=check(case, routed, choice))
            rows.append(row)
            mark = 'ok ' if not row['problems'] else 'BAD'
            picked = '' if not choice else f" {choice['model']}/{choice['effort']} {choice['task_type']} {row['latency']}s"
            print(f"{mark} {case['id']:<22} {routed['agent']:<6}{picked} {' '.join(row['problems'])}", flush=True)
    passed = sum(not r['problems'] for r in rows)
    kinds = {}
    for r in rows:
        for p in r['problems']: kinds[p.split(':')[0]] = kinds.get(p.split(':')[0], 0) + 1
    latencies = sorted(r['latency'] for r in rows if 'latency' in r)
    summary = {'split': args.split, 'cases': len(cases), 'runs': len(rows), 'passed': passed, 'failures_by_kind': kinds,
               'latency_median': statistics.median(latencies) if latencies else None,
               'latency_p90': latencies[int(.9 * (len(latencies) - 1))] if latencies else None}
    # Which counterfactual groups split their verdicts: the interesting failures.
    groups = {}
    for r in rows: groups.setdefault(r['group'], set()).add(not r['problems'])
    summary['inconsistent_groups'] = sorted(g for g, v in groups.items() if len(v) > 1)
    out = ROOT / 'state' / 'jev-eval'; out.mkdir(parents=True, exist_ok=True)
    (out / time.strftime('%Y%m%d-%H%M%S.json')).write_text(json.dumps({'summary': summary, 'rows': rows}, indent=1), encoding='utf-8')
    print(json.dumps(summary, indent=1))
    return 0 if passed == len(rows) else 1


if __name__ == '__main__':
    sys.exit(main())
