#!/usr/bin/env python3
"""Sync only the original appearance controls into the offline workspace.

The required ``<!-- BEGIN ONLINE NAME -->`` / ``<!-- END ONLINE NAME -->``
pairs are APPEARANCE and BACKGROUND VIEWER. Optional APPEARANCE ICON and
MOBILE APPEARANCE ICON pairs copy only the original appearance button SVG. Run normally to update
those fragments, or use --check in CI.

The offline workspace keeps its own navigation, six tools, layout and styles.
This script never copies the online chat shell, tool dialogs or CSS blocks.
Keep the shared appearance-panels.css link in the offline page's existing head;
the separate sync_offline_styles.py maintains its existing shared CSS exports.
"""
import argparse
from html.parser import HTMLParser
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
VOID_TAGS = {
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
    'meta', 'param', 'source', 'track', 'wbr',
}
REQUIRED = ('APPEARANCE', 'BACKGROUND VIEWER')
ELEMENT_IDS = {
    'APPEARANCE': 'appearanceModal',
    'BACKGROUND VIEWER': 'appearanceBackgroundViewer',
}


class Elements(HTMLParser):
    """Record balanced source ranges without reserializing the original DOM."""

    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.lines = [0]
        for match in re.finditer('\n', source):
            self.lines.append(match.end())
        self.stack = []
        self.elements = []
        self.feed(source)

    def source_position(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag not in VOID_TAGS:
            self.stack.append((tag, attributes, self.source_position()))

    def handle_startendtag(self, tag, attrs):
        # SVG paths/rects and self-closing void elements need no closing range.
        pass

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] != tag:
                continue
            opened_tag, attrs, start = self.stack[index]
            del self.stack[index:]
            end = self.source.find('>', self.source_position()) + 1
            self.elements.append((opened_tag, attrs, start, end))
            return

    def extract(self, identifier):
        matches = [item for item in self.elements if item[1].get('id') == identifier]
        if len(matches) != 1:
            raise ValueError('Expected one online element: ' + identifier)
        _, _, start, end = matches[0]
        return self.source[start:end]


def appearance_icon(online):
    """Return the original appearance button SVG without copying its button."""
    button = Elements(online).extract('appearanceBtn')
    icons = [item for item in Elements(button).elements if item[0] == 'svg']
    if len(icons) != 1:
        raise ValueError('Expected one SVG in online appearanceBtn')
    _, _, start, end = icons[0]
    return button[start:end]


def sync(online, offline):
    parsed = Elements(online)
    changed = []
    for name in (*REQUIRED, 'APPEARANCE ICON', 'MOBILE APPEARANCE ICON'):
        begin = '<!-- BEGIN ONLINE ' + name + ' -->'
        end = '<!-- END ONLINE ' + name + ' -->'
        if begin not in offline and end not in offline and name not in REQUIRED:
            continue
        if offline.count(begin) != 1 or offline.count(end) != 1:
            raise ValueError('Expected one matching marker pair: ' + begin + ' / ' + end)
        pattern = re.compile(re.escape(begin) + r'[\s\S]*?' + re.escape(end))
        if not pattern.search(offline):
            raise ValueError('Online marker pair is out of order: ' + name)
        if name in ('APPEARANCE ICON', 'MOBILE APPEARANCE ICON'):
            fragment = appearance_icon(online)
        else:
            fragment = parsed.extract(ELEMENT_IDS[name])
        if '{{' in fragment or '{%' in fragment:
            raise ValueError('Unsupported template-dependent markup in online fragment: ' + name)
        fragment = '\n'.join(line.rstrip() for line in fragment.strip().splitlines())
        replacement = begin + '\n' + fragment + '\n' + end
        previous = pattern.search(offline).group()
        if previous != replacement:
            changed.append(name)
            offline = pattern.sub(lambda _match: replacement, offline, count=1)
    return offline, changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--offline-html', type=Path, default=ROOT / 'static/offline.html',
                        help='Offline HTML to update (default: static/offline.html)')
    args = parser.parse_args()
    original = args.offline_html.read_text(encoding='utf-8')
    try:
        result, changed = sync((ROOT / 'templates/index.html').read_text(encoding='utf-8'), original)
    except ValueError as error:
        parser.error(str(error))
    if args.check and changed:
        parser.exit(1, 'Shared offline appearance differs from online: ' + ', '.join(changed)
                    + '\nRun python scripts/sync_offline_shell.py\n')
    if not args.check:
        args.offline_html.write_text(result, encoding='utf-8')
    print('Shared appearance matches' if args.check else 'Shared appearance exported')


if __name__ == '__main__':
    main()
