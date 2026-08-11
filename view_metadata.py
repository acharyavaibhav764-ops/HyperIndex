import pickle
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
METADATA_PATH = BASE_DIR / "knowledge_base" / "metadata.pkl"

def main():

    # Missing metadata file
    if not METADATA_PATH.exists():
        raise FileNotFoundError(f"Could not find metadata file at '{METADATA_PATH}'")

    # Unpickle and view metadata.pkl
    with open(METADATA_PATH, "rb") as f:
        metadata = pickle.load(f)

    print(f"[view_metadata] Loaded {len(metadata)} chunk record(s) from {METADATA_PATH}\n")

    for entry in metadata:
        print(f"chunk_id : {entry.get('chunk_id')}")
        print(f"source   : {entry.get('source')}")
        print(f"page     : {entry.get('page')}")
        print(f"preview  : {entry.get('content_preview')}")
        print("-" * 60)


if __name__ == "__main__":
    main()