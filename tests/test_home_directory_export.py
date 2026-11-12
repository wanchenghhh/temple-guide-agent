"""Homepage data must stay aligned with the single curated fact source."""
from pathlib import Path
import json
import runpy


def test_home_directory_matches_curated_dataset():
    root = Path(__file__).resolve().parents[1]
    export = runpy.run_path(str(root / 'scripts/export_temple_index.py'))['directory_payload']()
    published = json.loads((root / 'static/data/temple-index.json').read_text())
    assert published == export, 'Run python scripts/export_temple_index.py after changing temple data'
    assert len({row['name'] for row in published['items']}) == len(published['items'])
    assert all(row['name'] and row['district'] and row['status'] for row in published['items'])
