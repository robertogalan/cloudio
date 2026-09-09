"""Cloudio core - config, upload, and clipboard, with no GUI dependency.

Both the tray app (cloudio.py) and the CLI (bin/cloudio) go through here,
so a file uploaded either way lands in the same place under the same name.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote

from ssh_client import SSHClient

APP_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = APP_DIR / 'config.json'
ICON_FILE = str(APP_DIR / 'assets' / 'cloud.svg')

# scp copies the local mode across, so a file that is private locally lands
# unreadable by the web server and its link 404s. Uploads are public by
# definition, so normalise them.
REMOTE_MODE = '644'


class ConfigError(Exception):
    """config.json is missing, malformed, or incomplete."""


def load_config(path=None):
    path = Path(path) if path else CONFIG_FILE
    if not path.exists():
        raise ConfigError(
            f"No config at {path}\n"
            f"Copy config.example.json to config.json and fill in your server."
        )
    try:
        with open(path) as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path} is not valid JSON: {e}")

    for key in ('server', 'remote_path', 'base_url'):
        if key not in config:
            raise ConfigError(f"{path} is missing the '{key}' setting.")
    return config


def safe_filename(name):
    """Sanitize a filename for safe remote storage and clean URLs.

    Keeps only alphanumerics, hyphens, underscores, and dots.
    Everything else (spaces, slashes, control chars, path traversal)
    becomes an underscore.
    """
    name = os.path.basename(name)          # strip any directory component
    name = re.sub(r'[^\w.\-]', '_', name)  # allow only safe chars
    name = re.sub(r'\.{2,}', '_', name)    # collapse .. sequences
    return name or '_'


def upload_files(config, file_paths, on_progress=None):
    """Upload files and return their public URLs, in the order given.

    on_progress(index, total, filename) is called before each file starts.
    Raises RuntimeError if any upload fails.
    """
    client = SSHClient(config['server'])
    remote_dir = config['remote_path'].rstrip('/')
    base_url = config['base_url'].rstrip('/')

    client.ssh_run(['mkdir', '-p', remote_dir])

    urls = []
    remote_paths = []
    total = len(file_paths)
    for i, local_path in enumerate(file_paths, 1):
        filename = safe_filename(local_path)
        if on_progress:
            on_progress(i, total, filename)
        remote_path = f"{remote_dir}/{filename}"
        client.upload(local_path, remote_path)
        remote_paths.append(remote_path)
        urls.append(f"{base_url}/{quote(filename)}")

    client.ssh_run(['chmod', REMOTE_MODE] + remote_paths)
    return urls


# Ordered by how likely each is to be the right tool for the session:
# Wayland first, then X11, then macOS.
_CLIPBOARD_COMMANDS = (
    ('wl-copy', ['wl-copy']),
    ('xclip', ['xclip', '-selection', 'clipboard']),
    ('xsel', ['xsel', '--clipboard', '--input']),
    ('pbcopy', ['pbcopy']),
)


def copy_to_clipboard(text):
    """Copy text to the system clipboard. Returns the tool used, or None.

    A short-lived CLI cannot own the clipboard itself the way the tray app
    does, so this shells out to a helper that survives the process.
    """
    for name, command in _CLIPBOARD_COMMANDS:
        if not shutil.which(name):
            continue
        try:
            subprocess.run(command, input=text, text=True, check=True,
                           timeout=10)
            return name
        except (subprocess.SubprocessError, OSError):
            continue
    return None
