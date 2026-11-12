#!/usr/bin/env python3
"""Export the online template's CSS for the offline workspace.

Run with --check in CI; run without it after changing inline online styles.
Offline-only layout belongs in offline.css, not these shared exports.
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
    blocks = re.findall(r'<style(?:\s[^>]*)?>([\s\S]*?)</style>', template)
    if not blocks or any('{{' in block or '{%' in block for block in blocks):
        parser.error('Expected static inline styles; review template-dependent CSS before exporting')
    exports = {
        'static/dmate-main.css': blocks[0].strip() + '\n',
        'static/dmate-shared-overrides.css':
            '/* Generated from templates/index.html by scripts/sync_offline_styles.py. */\n'
            + '\n\n'.join(block.strip() for block in blocks[1:]) + '\n',
    }
    stale = []
    for filename, content in exports.items():
        path = ROOT / filename
        if args.check:
            if not path.exists() or path.read_text(encoding='utf-8') != content:
                stale.append(filename)
        else:
            path.write_text(content, encoding='utf-8')
    if stale:
        parser.exit(1, 'Shared online/offline CSS is out of date: ' + ', '.join(stale)
                    + '\nRun python scripts/sync_offline_styles.py\n')
    print('Online/offline shared styles match' if args.check else 'Shared styles exported')


if __name__ == '__main__':
    main()
