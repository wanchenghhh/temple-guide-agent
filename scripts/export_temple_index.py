"""Export the public homepage directory from the curated domain dataset."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def directory_payload():
    dataset = json.loads((ROOT / 'app/agent/domain/temples.json').read_text(encoding='utf-8'))
    return {
        'updated_at': dataset['meta'].get('updated_at', ''),
        'items': [{key: row.get(key, '') for key in ('name', 'district', 'sect', 'status', 'open_status', 'atmosphere')}
                  for row in dataset['temples']],
    }


if __name__ == '__main__':
    target = ROOT / 'static/data/temple-index.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(directory_payload(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Exported {len(directory_payload()["items"])} directory entries')
