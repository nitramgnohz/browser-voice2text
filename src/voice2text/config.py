"""Project-local paths and connection settings."""

from dataclasses import dataclass
from pathlib import Path
import json
import os
import secrets

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / '.local'
MODEL_REPO = 'mlx-community/whisper-small-mlx'


@dataclass
class Config:
    token: str
    model_path: Path = LOCAL / 'models' / 'whisper-small-mlx'
    port: int = 8766
    auth_timeout: float = 5


def configure_environment():
    LOCAL.mkdir(mode=0o700, exist_ok=True)
    LOCAL.chmod(0o700)
    os.environ['HF_HOME'] = str(LOCAL / 'huggingface')
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    os.environ['HF_HUB_DISABLE_XET'] = '1'
    os.environ['XDG_CACHE_HOME'] = str(LOCAL / 'cache')
    os.environ['NUMBA_CACHE_DIR'] = str(LOCAL / 'numba')


def load_config() -> Config:
    configure_environment()
    path = LOCAL / 'config.json'
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump({'token': secrets.token_urlsafe(32)}, handle)
    data = json.loads(path.read_text())
    return Config(token=data['token'])
