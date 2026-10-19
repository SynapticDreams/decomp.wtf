"""Actual symbol control markup and component reject stale actions and preserve exact source bytes."""
from pathlib import Path

from .browser_check import run


def test_symbol_controls_preview_page_apply_and_keep_source_states_distinct(tmp_path):
    page = (Path(__file__).resolve().parents[1] / 'src/decompnet/app/static/index.html').read_text()
    markup = page[page.index('<div id="smsSymbols"'):page.index('<h3 class="sub" id="covHead"')]
    run(tmp_path, ['src/decompnet/app/static/sms-symbols.js', 'tests/browser/sms_symbols.js'], markup=markup, asynchronous=True)
