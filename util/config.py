import os

import yaml

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yaml')
_config = None


def load_config() -> dict:
    """Load config.yaml, caching the result after first load."""
    global _config
    if _config is None:
        with open(_CONFIG_PATH) as f:
            _config = yaml.safe_load(f)
    return _config


def reload_config():
    """Force reload config.yaml from disk."""
    global _config
    with open(_CONFIG_PATH) as f:
        _config = yaml.safe_load(f)


def save_config(cfg: dict):
    """Write config back to disk."""
    global _config
    _config = cfg
    with open(_CONFIG_PATH, 'w') as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
