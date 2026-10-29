"""The standalone drawing and notebook stay beside the existing wrong book."""
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_drawing_and_notebook_are_unique_entries_in_the_wrong_book_panel():
    class Menu(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.entries, self.current = [], {}, None

        def handle_starttag(self, tag, attributes):
            data = dict(attributes)
            if tag == 'button' and data.get('id') in ('wrongBookBtn', 'graphDrawingBtn', 'conceptNotebookBtn'):
                assert data['id'] not in self.entries
                self.entries[data['id']] = {'panels': [node.get('class', '') for _, node in self.stack], 'text': ''}
                self.current = data['id']
            if tag not in ('input', 'meta', 'link', 'img', 'br', 'hr', 'source', 'area', 'wbr'):
                self.stack.append((tag, data))

        def handle_endtag(self, tag):
            if tag == 'button':
                self.current = None
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index][0] == tag:
                    self.stack = self.stack[:index]
                    break

        def handle_data(self, text):
            if self.current:
                self.entries[self.current]['text'] += text

    menu = Menu()
    menu.feed((ROOT / 'templates/index.html').read_text())
    assert list(menu.entries) == ['wrongBookBtn', 'graphDrawingBtn', 'conceptNotebookBtn']
    assert menu.entries['graphDrawingBtn']['text'] == '画图'
    assert menu.entries['conceptNotebookBtn']['text'] == '笔记本'
    for entry in menu.entries.values():
        assert 'learning-panel' in entry['panels']
        assert 'right' in entry['panels']
