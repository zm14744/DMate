#!/usr/bin/env python3
"""Keep the offline shell and dialogs identical to the online template.

The offline HTML contains ``<!-- BEGIN ONLINE NAME -->`` / ``<!-- END ONLINE
NAME -->`` pairs. The required names are STYLES, SHELL, APPEARANCE, BACKGROUND
VIEWER and KNOWLEDGE GRAPH. Optional pairs are WRONG BOOK, DRAWING DIALOG and
LEARNING REVIEW. Run normally to update them, or use --check in CI.

Only offline action bindings differ: inline click handlers are removed,
learning-tool entries receive data-offline-panel, and the offline entry becomes
the return-online entry. The original structure, classes and SVGs are retained.
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
REQUIRED = ('STYLES', 'SHELL', 'APPEARANCE', 'BACKGROUND VIEWER', 'KNOWLEDGE GRAPH')
ASSET_VERSION = '6'
ELEMENT_IDS = {
    'APPEARANCE': 'appearanceModal',
    'BACKGROUND VIEWER': 'appearanceBackgroundViewer',
    'KNOWLEDGE GRAPH': 'knowledgeGraphModal',
    'WRONG BOOK': 'wrongBookModal',
    'DRAWING DIALOG': 'graphEditorDialog',
    'LEARNING REVIEW': 'learningReviewModal',
}
PANEL_ENTRIES = {
    'wrongBookBtn': 'mistakes',
    'conceptNotebookBtn': 'notes',
    'knowledgeGraphBtn': 'graph',
    'graphDrawingBtn': 'drawing',
    'learningReviewBtn': 'review',
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
        self.style_links = []
        self.feed(source)

    def source_position(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'link' and 'stylesheet' in (attributes.get('rel') or '').split():
            self.style_links.append((self.source_position(), self.get_starttag_text()))
        if tag not in VOID_TAGS:
            self.stack.append((tag, attributes, self.source_position()))

    def handle_startendtag(self, tag, attrs):
        # SVG paths/rects and self-closing void elements contain no shell roots.
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

    def extract(self, identifier=None, layout=False):
        matches = [item for item in self.elements if (
            item[1].get('id') == identifier if identifier is not None
            else layout and item[0] == 'div' and 'layout' in (item[1].get('class') or '').split()
        )]
        if len(matches) != 1:
            raise ValueError('Expected one online element: ' + (identifier or '.layout'))
        _, _, start, end = matches[0]
        return self.source[start:end]


def without_click_handlers(source):
    return re.sub(r'\s+onclick\s*=\s*([\"\'])[\s\S]*?\1', '', source, flags=re.IGNORECASE)


def shell_fragment(source):
    shell = without_click_handlers(source)
    # The static shell is browser markup; native-app-only hiding is not needed.
    shell = re.sub(
        r'{%\s*if\s+is_dmate_android_app\s+or\s+is_dmate_desktop_app\s*%}'
        r'\s*hidden\s*{%\s*endif\s*%}', '', shell,
    )
    for identifier, panel in PANEL_ENTRIES.items():
        pattern = r'(<button\b[^>]*\bid="' + re.escape(identifier) + r'"[^>]*)(>)'
        shell, count = re.subn(pattern, lambda match: match[1]
                              + ' data-offline-panel="' + panel + '"' + match[2], shell)
        if count != 1:
            raise ValueError('Expected one online learning-tool entry: ' + identifier)
    online_button = Elements(shell).extract('offlineWorkspaceBtn')
    return_button = online_button.replace('id="offlineWorkspaceBtn"', 'id="returnOnline"')
    return_button = return_button.replace('aria-label="打开离线学习工作区"', 'aria-label="返回在线版"')
    return_button = return_button.replace('title="离线版"', 'title="在线版"')
    return_button = return_button.replace('<span class="dmate-ui-label">离线版</span>',
                                          '<span class="dmate-ui-label">在线版</span>')
    shell = shell.replace(online_button, return_button, 1)
    return shell


def styles_fragment(parsed):
    """Retain every online style and stylesheet link in its cascade order."""
    pieces = list(parsed.style_links)
    pieces.extend((start, parsed.source[start:end])
                  for tag, _attrs, start, end in parsed.elements if tag == 'style')
    content = '\n'.join(value for _position, value in sorted(pieces))
    return re.sub(r'([?&]v=){{\s*dmate_web_revision\s*}}',
                  lambda match: match[1] + ASSET_VERSION, content)


def tool_fragment(name, source):
    """Keep the original dialog chrome and attach its local data adapter."""
    fragment = without_click_handlers(source)
    if name == 'WRONG BOOK':
        fragment = fragment.replace('<div id="wrongBookList"></div>',
            '<section id="mistakesPanel" class="offline-module-content"><div id="wrongBookList"><div id="mistakeList"></div></div></section>')
        fragment = fragment.replace('<button id="wrongPdfBtn"',
            '<button id="addMistake" class="primary" type="button">添加错题</button>\n            <button id="wrongPdfBtn"')
    elif name == 'DRAWING DIALOG':
        fragment = fragment.replace('>图片</h2>', '>绘图</h2>').replace(
            '<div id="graphEditorMount"></div>',
            '<div id="graphEditorMount"><section id="drawingPanel" class="offline-module-content"><div id="offlineDrawingHost"></div></section></div>')
    elif name == 'LEARNING REVIEW':
        fragment = fragment.replace('<div id="learningReviewBody" class="learning-review-body"></div>',
            '<div id="learningReviewBody" class="learning-review-body"></div>\n'
            '        <div class="offline-library-actions learning-review-section">\n'
            '          <button type="button" data-offline-panel="questions">题库</button>\n'
            '          <button type="button" data-offline-panel="concepts">概念库</button>\n'
            '          <button id="exportLocalData" type="button">导出本地数据</button>\n'
            '        </div>')
    return fragment


def sync(online, offline):
    parsed = Elements(online)
    changed = []
    for name in (*REQUIRED, *(name for name in ELEMENT_IDS if name not in REQUIRED)):
        begin = '<!-- BEGIN ONLINE ' + name + ' -->'
        end = '<!-- END ONLINE ' + name + ' -->'
        if begin not in offline and end not in offline and name not in REQUIRED:
            continue
        if offline.count(begin) != 1 or offline.count(end) != 1:
            raise ValueError('Expected one matching marker pair: ' + begin + ' / ' + end)
        pattern = re.compile(re.escape(begin) + r'[\s\S]*?' + re.escape(end))
        if not pattern.search(offline):
            raise ValueError('Online marker pair is out of order: ' + name)
        if name == 'STYLES':
            fragment = styles_fragment(parsed)
        elif name == 'SHELL':
            fragment = shell_fragment(parsed.extract(layout=True))
        else:
            fragment = tool_fragment(name, parsed.extract(ELEMENT_IDS[name]))
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
        parser.exit(1, 'Offline shell differs from online template: ' + ', '.join(changed)
                    + '\nRun python scripts/sync_offline_shell.py\n')
    if not args.check:
        args.offline_html.write_text(result, encoding='utf-8')
    print('Online/offline shell matches' if args.check else 'Online shell and dialogs exported')


if __name__ == '__main__':
    main()
