#!/usr/bin/env python3
"""Export the online template's inline overrides for the offline workspace.

Both pages already link directly to dmate-main.css. Offline-only layout lives
in offline.css.
"""
import argparse
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    template = (ROOT / 'templates/index.html').read_text(encoding='utf-8')
    offline = (ROOT / 'static/offline.html').read_text(encoding='utf-8')
    main_stylesheet = '<link rel="stylesheet" href="/static/dmate-main.css?'
    if any(main_stylesheet not in page for page in (template, offline)):
        parser.error('Both workspaces must link the shared dmate-main.css stylesheet')
    blocks = re.findall(r'<style(?:\s[^>]*)?>([\s\S]*?)</style>', template)
    if not blocks or any('{{' in block or '{%' in block for block in blocks):
        parser.error('Expected static inline styles; review template-dependent CSS before exporting')
    path = ROOT / 'static/dmate-shared-overrides.css'
    content = ('/* Generated from templates/index.html by scripts/sync_offline_styles.py. */\n'
               + '\n\n'.join(block.strip() for block in blocks) + '\n')
    if args.check:
        if not path.exists() or path.read_text(encoding='utf-8') != content:
            parser.exit(1, 'Shared online/offline CSS is out of date. Run python scripts/sync_offline_styles.py\n')
    else:
        path.write_text(content, encoding='utf-8')
    print('Online/offline shared styles match' if args.check else 'Shared styles exported')


if __name__ == '__main__':
    main()
