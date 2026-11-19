import json
from pathlib import Path

CONTENT_FILE = Path(__file__).resolve().parent.parent / "content" / "blocks.json"

def load_content():
    return json.loads(CONTENT_FILE.read_text(encoding="utf-8"))

CONTENT = load_content()
