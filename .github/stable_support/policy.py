"""Pure policy for bounded, one-patch Hermes support proposals."""
import re

VERSION = r'(?:0|[1-9][0-9]{0,5})\.(?:0|[1-9][0-9]{0,5})\.(?:0|[1-9][0-9]{0,5})'
GATE = re.compile(rb'^requires_hermes: "([^"\r\n]+)"(?=\r?$)', re.MULTILINE)
MAX_HOSTS = 8


def stable_tag(release, expected=None):
    tag = release.get('tag_name')
    if (type(tag) is not str or not re.fullmatch('v' + VERSION, tag)
            or release.get('draft') is not False or release.get('prerelease') is not False
            or (expected is not None and tag != expected)):
        raise ValueError('Expected an exact, published official stable vMAJOR.MINOR.PATCH release')
    return tag


def proposal(data, tag):
    stable_tag({'tag_name': tag, 'draft': False, 'prerelease': False})
    gate = GATE.search(data)
    if gate is None or data.count(b'requires_hermes') != 1:
        raise ValueError('Expected one canonical requires_hermes declaration')
    spec = gate[1].decode('ascii')
    equal = re.fullmatch(f'==({VERSION})', spec)
    bounded = re.fullmatch(f'>=({VERSION}),<=({VERSION})', spec)
    if not (equal or bounded):
        raise ValueError('Existing requires_hermes is outside the automation policy')
    lo, hi = (equal[1], equal[1]) if equal else bounded.groups()
    lower, upper, candidate = [tuple(map(int, v.split('.'))) for v in (lo, hi, tag[1:])]
    if lower[:2] != upper[:2] or lower > upper or upper[2] - lower[2] >= MAX_HOSTS:
        raise ValueError('Existing support must be a bounded contiguous same-minor patch series')
    if lower <= candidate <= upper:
        return None
    if candidate[:2] != upper[:2] or candidate[2] != upper[2] + 1:
        raise ValueError('Only the next same-minor patch is eligible; gaps and downgrades require review')
    if candidate[2] - lower[2] >= MAX_HOSTS:
        raise ValueError('Candidate exceeds the hosted verification budget; review manually')
    prefix = '.'.join(lo.split('.')[:2])
    versions = [f'{prefix}.{n}' for n in range(lower[2], candidate[2] + 1)]
    spec = f'>={lo},<={tag[1:]}'.encode('ascii')
    return data[:gate.start(1)] + spec + data[gate.end(1):], versions
