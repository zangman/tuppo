import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import util.config as config


def get_profile() -> str:
    """
    Retrieve the current owner profile status.
    """
    try:
        cfg = config.load_config()
        owner = cfg.get('owner', {})

        output = ["=== Owner Profile Status ==="]
        output.append(f"- Name: {owner.get('name', 'Unknown')}")
        status = owner.get('status', {})
        for key in ('current_location', 'current_focus', 'availability'):
            output.append(f"- {key.replace('_', ' ').title()}: {status.get(key, 'Unknown')}")

        return "\n".join(output)
    except Exception as e:
        return f"Error retrieving profile: {e}"


def update_owner_status(key: str, value: str) -> str:
    """
    Update a specific field in the owner's profile status.
    Example keys: 'current_location', 'availability', 'current_focus'.
    """
    try:
        cfg = config.load_config()
        if 'status' not in cfg.get('owner', {}):
            cfg.setdefault('owner', {})['status'] = {}
        cfg['owner']['status'][key] = value
        config.save_config(cfg)
        return f"Successfully updated {key} to: {value}"
    except Exception as e:
        return f"Error updating profile: {e}"
