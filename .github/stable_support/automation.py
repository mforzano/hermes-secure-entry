"""Plan from official release metadata; publish only from a trusted scheduled job."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlencode

from policy import proposal, stable_tag, VERSION

REPO = 'mforzano/hermes-secure-entry'
UPSTREAM = 'repos/NousResearch/hermes-agent'
TARGET = f'repos/{REPO}'
PREFIX = 'automation/hermes-stable-'


def api(endpoint, *, payload=None, paginate=False):
    args = ['gh', 'api', '--hostname', 'github.com', endpoint]
    if paginate:
        args += ['--paginate', '--slurp']
    if payload is not None:
        args += ['--method', 'POST', '--input', '-']
    return json.loads(subprocess.check_output(args, input=None if payload is None else json.dumps(payload).encode()))


def oid(value):
    if type(value) is not str or not re.fullmatch(r'[0-9a-f]{40}', value):
        raise ValueError('Expected an exact commit/object SHA')
    return value


def resolve_host(fetch, tag):
    stable_tag(fetch(f'{UPSTREAM}/releases/tags/{tag}'), tag)
    ref = fetch(f'{UPSTREAM}/git/ref/tags/{tag}')['object']
    if ref['type'] == 'tag':
        ref = fetch(f'{UPSTREAM}/git/tags/{oid(ref["sha"])}')['object']
    if ref['type'] != 'commit':
        raise ValueError('Official release tag must resolve directly to a commit')
    return {'tag': tag, 'sha': oid(ref['sha'])}


def plan(fetch, base, source, requested=''):
    oid(base)
    if requested and not re.fullmatch('v' + VERSION, requested):
        raise ValueError('Invalid requested stable tag')
    endpoint = f'tags/{requested}' if requested else 'latest'
    tag = stable_tag(fetch(f'{UPSTREAM}/releases/{endpoint}'), requested or None)
    proposed = proposal(source, tag)
    if proposed is None:
        return None
    data, versions = proposed
    return ({'base': base, 'tag': tag, 'manifest_sha256': hashlib.sha256(data).hexdigest(),
             'spec': f'>={versions[0]},<={versions[-1]}',
             'hosts': [resolve_host(fetch, f'v{v}') for v in versions]}, data)


def publication_blocker(branch, open_heads, prior_heads, occupied):
    if any(head.startswith(PREFIX) for head in open_heads):
        return 'An automation PR is already open; no new PR.'
    if branch in prior_heads:
        return 'This exact candidate already had a PR; no new PR.'
    if branch in occupied:
        raise ValueError('Candidate branch exists without a matching PR; maintainer inspection required')
    return None


def heads(fetch, **query):
    pages = fetch(f'{TARGET}/pulls?{urlencode(query | {"per_page": 100})}', paginate=True)
    return {pr['head']['ref'] for page in pages for pr in page
            if (pr['head']['repo'] or {}).get('full_name') == REPO}


def dedup(fetch, branch):
    open_heads = heads(fetch, state='open', base='main')
    prior = heads(fetch, state='all', base='main', head=f'mforzano:{branch}')
    refs = fetch(f'{TARGET}/git/matching-refs/heads/{branch}')
    occupied = {ref['ref'].removeprefix('refs/heads/') for ref in refs}
    return publication_blocker(branch, open_heads, prior, occupied)


def publish(fetch, base, source, approved, result, run_url):
    if result != 'success':
        raise ValueError('The complete validation matrix must pass before publishing')
    current = plan(fetch, base, source)
    if current is None or current[0] != approved:
        raise ValueError('Release, host commits, base or manifest differs from the tested plan')
    evidence, data = current
    tag = evidence['tag']
    branch = PREFIX + tag
    if blocker := dedup(fetch, branch):
        return blocker
    if not re.fullmatch(rf'https://github\.com/{REPO}/actions/runs/[0-9]+', run_url):
        raise ValueError('Expected the exact verification run URL')
    base_commit = fetch(f'{TARGET}/git/commits/{base}')
    if fetch(f'{TARGET}/git/ref/heads/main')['object']['sha'] != base:
        raise ValueError('Main advanced after validation; retry from the new base')
    blob = oid(fetch(f'{TARGET}/git/blobs', payload={
        'content': base64.b64encode(data).decode('ascii'), 'encoding': 'base64'})['sha'])
    tree = oid(fetch(f'{TARGET}/git/trees', payload={
        'base_tree': oid(base_commit['tree']['sha']),
        'tree': [{'path': 'plugin.yaml', 'type': 'blob', 'mode': '100644', 'sha': blob}]})['sha'])
    title = f'Support Hermes {tag[1:]} in Secure Entry'
    commit = oid(fetch(f'{TARGET}/git/commits', payload={
        'message': f'ci: propose Secure Entry support for Hermes {tag[1:]}',
        'tree': tree, 'parents': [base]})['sha'])
    # Create only, never force/update a ref. GitHub rejects concurrent duplicate creates.
    if fetch(f'{TARGET}/git/ref/heads/main')['object']['sha'] != base:
        raise ValueError('Main advanced before branch creation; retry from the new base')
    fetch(f'{TARGET}/git/refs', payload={'ref': f'refs/heads/{branch}', 'sha': commit})
    hosts = '\n'.join(f'- `{host["tag"]}` at `{host["sha"]}`' for host in evidence['hosts'])
    pr = fetch(f'{TARGET}/pulls', payload={
        'title': title, 'head': branch, 'base': 'main', 'draft': False,
        'body': (f'Updates only `plugin.yaml` to `{evidence["spec"]}`.\n\n'
                 f'Windows regressions, manifest admission, registered tools, doctor and catalog validation '
                 f'passed in [this run]({run_url}) on:\n{hosts}\n\n'
                 'Review before merging. No plugin release, catalog publication or installation. '
                 'GitHub may require approval to start the ordinary PR checks.')})
    # Never infer PR creation from branch creation; verify the PR returned by GitHub.
    actual = fetch(f'{TARGET}/pulls/{int(pr["number"])}')
    if (actual['state'] != 'open' or actual['head']['sha'] != commit
            or actual['head']['ref'] != branch or actual['base']['ref'] != 'main'
            or actual['head']['repo']['full_name'] != REPO or actual['base']['repo']['full_name'] != REPO):
        raise ValueError('Created PR does not match the verified branch')
    return actual['html_url']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['plan', 'stage', 'publish'])
    args = parser.parse_args()
    base = oid(subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip())
    if base != os.environ['GITHUB_SHA']:
        raise ValueError('Unexpected plugin checkout commit')
    source = subprocess.check_output(['git', 'show', f'{base}:plugin.yaml'])
    if args.mode == 'stage':
        approved = json.loads(os.environ['APPROVED_PLAN'])
        proposed = proposal(source, approved['tag'])
        if proposed is None or base != approved['base']:
            raise ValueError('No candidate for this checkout')
        data, _ = proposed
        if hashlib.sha256(data).hexdigest() != approved['manifest_sha256']:
            raise ValueError('Candidate manifest hash differs from the planned bytes')
        Path('plugin.yaml').write_bytes(data)
        return
    if os.environ['GITHUB_REPOSITORY'] != REPO:
        raise ValueError('Stable support automation is scoped to the public Secure Entry repository')
    if args.mode == 'publish':
        if os.environ['GITHUB_EVENT_NAME'] != 'schedule' or os.environ['GITHUB_REF'] != 'refs/heads/main':
            raise ValueError('Only a scheduled default-branch run may publish')
        message = publish(api, base, source, json.loads(os.environ['APPROVED_PLAN']),
                          os.environ['RESULT'], f'https://github.com/{REPO}/actions/runs/{os.environ["GITHUB_RUN_ID"]}')
    else:
        proposed = plan(api, base, source, os.environ.get('REQUESTED_TAG', ''))
        approved = proposed[0] if proposed else None
        message = 'Latest stable is already admitted; nothing to propose.'
        if approved:
            branch = PREFIX + approved['tag']
            blocker = dedup(api, branch) if os.environ['GITHUB_EVENT_NAME'] == 'schedule' else None
            message = blocker or f'Verifying `{approved["spec"]}` from `{base}`: {json.dumps(approved["hosts"])}'
            if blocker:
                approved = None
        with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as output:
            print(f'candidate={str(approved is not None).lower()}', file=output)
            print('plan=' + json.dumps(approved), file=output)
            print('matrix=' + json.dumps({'include': approved['hosts'] if approved else []}), file=output)
    print(message)
    with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as summary:
        print(message, file=summary)


if __name__ == '__main__':
    main()
