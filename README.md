# Cloudio

Drop a file, get a link.

Cloudio is a lightweight Linux tray app that uploads files to your own server and gives you a shareable URL. That's it. No accounts, no subscriptions, no 47 features you didn't ask for.

If you used CloudApp back when it was good — before it became a bloated screenshot-annotation-video-recording-workspace-collaboration platform — this is that. The original idea, done right: drag a file, get a link, move on with your life.

**Your server, your files, your links.**

![Drop zone](assets/cloud.svg)

## How it works

1. A small cloud icon sits in your system tray
2. Drag a file onto the drop zone (or pick one from the menu)
3. File gets uploaded to your server via SCP
4. The public URL is copied to your clipboard
5. Done

No electron. No daemon eating your RAM. No cloud service that'll sunset next quarter. Just ~300 lines of Python, GTK for the tray icon, and `scp` to move your file. Uses zero CPU when idle.

## Requirements

- Linux with a GTK3 desktop (tested on Linux Mint Cinnamon)
- Python 3
- A server with SSH access and nginx (or any web server)
- `scp` and optionally `sshpass` (for password auth)

System packages:
```
python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 openssh-client
```

## Setup

### 1. Configure your server

You need a directory on your server that nginx serves publicly. Add something like this to your nginx config:

```nginx
location /cloudio/ {
    alias /home/youruser/cloudio-uploads/;
    autoindex off;
}
```

Then:
```bash
mkdir -p ~/cloudio-uploads
sudo nginx -t && sudo systemctl reload nginx
```

### 2. Configure Cloudio

```bash
cp config.example.json config.json
```

Edit `config.json`:

```json
{
    "server": {
        "name": "my-server",
        "host": "your.server.ip",
        "port": 22,
        "user": "ubuntu",
        "auth_type": "key",
        "key_path": "~/.ssh/id_rsa"
    },
    "remote_path": "/home/youruser/cloudio-uploads",
    "base_url": "https://yourdomain.com/cloudio"
}
```

| Field | What it is |
|-------|-----------|
| `server` | SSH connection details — same stuff you'd put in `~/.ssh/config` |
| `auth_type` | `"key"` for SSH key, `"password"` for password auth (requires `sshpass`) |
| `remote_path` | Where files land on the server |
| `base_url` | The public URL prefix that maps to `remote_path` |

### 3. Install and run

```bash
# Install system dependencies + set up autostart
./install.sh

# Or just run it directly
python3 cloudio.py
```

Cloudio auto-starts on login after running `install.sh`.

## Usage

**Drag and drop:** Drag any file onto the floating drop zone window.

**Menu upload:** Click the tray icon > "Upload File..." to pick a file.

**Toggle drop zone:** Click the tray icon > "Toggle Drop Zone" to show/hide the drop target.

After upload, the link is in your clipboard. Paste it anywhere.

## Password auth

If your server uses password auth instead of SSH keys, set `auth_type` to `"password"` and add a `"password"` field:

```json
{
    "server": {
        "auth_type": "password",
        "password": "yourpassword",
        ...
    }
}
```

This requires `sshpass` (`sudo apt install sshpass`). The password is passed via environment variable, not command line arguments, so it won't show up in `ps`.

SSH keys are recommended.

## Why

CloudApp was perfect in 2012. Drag a file to the menu bar, get a link. Then it got acquired, added teams and workspaces and annotations and screen recording and video messaging and became $16/month for something that used to be simple and free.

Cloudio is the app CloudApp should have stayed. You own the server. You own the files. There's no service to cancel. It does one thing and it does it well.

## License

MIT
