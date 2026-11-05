import json
from pathlib import Path


def load_keys(base_dir):
    path = Path(base_dir) / ".web-settings.json"
    if not path.exists():
        return {}
    try:
        import keyring

        metadata = json.loads(path.read_text())
        return {
            name: keyring.get_password("LahodnyCRM.Web", credential) or ""
            for name, credential in metadata.items()
        }
    except Exception:
        # Fail closed: a missing vault never enables an unsigned source.
        return {}
