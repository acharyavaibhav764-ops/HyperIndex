"""v5.9.4 offline check. Run from the repo root:  python -m pytest tests/parsing_arch/v5_9/test_v5_9_4.py -q"""
import importlib.util
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))
_spec = importlib.util.spec_from_file_location("chunk_cleanup", _REPO / "core" / "chunk_cleanup.py")
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)

META = {"content_type": "table", "heading_path": "3 Electrical connection > 3.8 Wiring terminals"}


def _run(chunks):
    return cc.postprocess_chunks(chunks, [dict(META) for _ in chunks])[0]


def test_heading_plus_cut_separator_row_is_dropped():
    junk1 = "3 Electrical connection\n3.8 Wiring terminals and their function:\n-------------------|--------|-------|"
    junk2 = "4. Room variants\n4.5 Combinations in the patient room\n----------------------------|\n"
    keep = "3 Electrical connection\n3.8 Wiring terminals\n| DBUS | Yes | Yes | Yes |"
    out = _run([junk1, keep, junk2])
    assert len(out) == 1 and "| DBUS |" in out[0]


def test_real_text_chunk_with_a_rule_is_kept():
    text = "Safety instructions\nIn accordance with DIN VDE 0834-1, connection cables must withstand 4 kV.\n---"
    assert any("DIN VDE" in c for c in _run([text]))


def test_table_chunk_with_normal_separator_is_unchanged():
    t = "2 Installation\n| A | B |\n|---|---|\n| 1 | 2 |"
    out = _run([t])
    assert out and "| 1 | 2 |" in out[0]
