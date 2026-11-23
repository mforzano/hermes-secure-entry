"""Mandatory host-side acceptance; unlike forward CI, exclusion is a failure."""
import hashlib
import json
import os
from pathlib import Path
from subprocess import run
import sys

import hermes_yaml
from hermes_cli import plugins_manifest
from hermes_cli.plugin_dev import doctor_plugin
from packaging.specifiers import SpecifierSet


def main():
    approved = json.loads(os.environ['APPROVED_PLAN'])
    current = os.environ['HOST_TAG'][1:]
    host_root = (Path(os.environ['GITHUB_WORKSPACE']) / 'hermes').resolve()
    if not Path(plugins_manifest.__file__).resolve().is_relative_to(host_root):
        raise SystemExit('Validation imported the wrong Hermes source')
    version = plugins_manifest.running_hermes_version()
    if version != current:
        raise SystemExit(f'Expected runtime version {current}; got {version}')
    data = Path('plugin.yaml').read_bytes()
    if hashlib.sha256(data).hexdigest() != approved['manifest_sha256']:
        raise SystemExit('Candidate manifest bytes changed')
    manifest = hermes_yaml.safe_load(data.decode('utf-8'))
    spec = manifest['requires_hermes']
    if spec != approved['spec'] or version not in SpecifierSet(spec):
        raise SystemExit('Candidate manifest does not contain the planned admission range')
    if error := plugins_manifest.requires_hermes_error(manifest):
        raise SystemExit(error)
    # Enforce both edges through the actual runtime grammar, not only packaging.
    first = approved['hosts'][0]['tag'][1:]
    last = approved['hosts'][-1]['tag'][1:]
    major, minor, low = map(int, first.split('.'))
    high = int(last.rsplit('.', 1)[-1])
    before = f'{major}.{minor}.{low - 1}' if low else f'{major}.{minor - 1}.999999' if minor else f'{major - 1}.999999.999999' if major else None
    after = f'{major}.{minor}.{high + 1}'
    for outside in (before, after):
        if outside and plugins_manifest.version_satisfies(spec, outside):
            raise SystemExit(f'Runtime incorrectly admits outside version {outside}')
    doctor = doctor_plugin('.')
    print(doctor.format_text(), flush=True)
    tools = manifest['provides_tools']
    if not doctor.ok or not tools or sorted(doctor.registered_tools) != sorted(tools):
        raise SystemExit('Runtime discovery/registration or declared tool check failed')
    run([sys.executable, '-c', 'from hermes_cli.plugins_cmd_catalog import cmd_validate; '
         'cmd_validate(".", as_json=True, install_deps=False)'], check=True)
    with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as summary:
        print(f'Hermes `{version}` admitted under `{spec}`. Doctor, {len(tools)} tool registrations and catalog validation passed.', file=summary)


if __name__ == '__main__':
    main()
