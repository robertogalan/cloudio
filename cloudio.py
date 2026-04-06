#!/usr/bin/env python3
"""Cloudio - Drop a file, get a link.

Lightweight tray app that uploads files to a remote nginx server
via SCP and copies the public URL to clipboard.
"""

import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')

try:
    gi.require_version('AyatanaAppIndicator3', '0.1')
    from gi.repository import AyatanaAppIndicator3 as AppIndicator3
except (ValueError, ImportError):
    gi.require_version('AppIndicator3', '0.1')
    from gi.repository import AppIndicator3

from gi.repository import Gtk, Gdk, GLib, GdkPixbuf
import json
import os
import threading
from pathlib import Path
from urllib.parse import quote, urlparse, unquote

from ssh_client import SSHClient

APP_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = APP_DIR / 'config.json'
ICON_FILE = str(APP_DIR / 'assets' / 'cloud.svg')


def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def safe_filename(name):
    """Replace spaces and problematic chars for clean URLs."""
    return name.replace(' ', '_')


# ---------------------------------------------------------------------------
# Drop Zone Window
# ---------------------------------------------------------------------------

class DropZoneWindow(Gtk.Window):

    def __init__(self, app):
        super().__init__(title='Cloudio')
        self.app = app
        self.set_default_size(140, 140)
        self.set_keep_above(True)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_position(Gtk.WindowPosition.CENTER)

        self.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        self.drag_dest_add_uri_targets()
        self.connect('drag-data-received', self._on_drop)
        self.connect('drag-motion', self._on_drag_motion)
        self.connect('drag-leave', self._on_drag_leave)
        self.connect('delete-event', lambda w, e: w.hide() or True)

        self._hovering = False

        css = Gtk.CssProvider()
        css.load_from_data(b"""
            .dropzone {
                background-color: #2d2d2d;
                border-radius: 16px;
                border: 2px dashed #4A90D9;
            }
            .dropzone-hover {
                background-color: #3d3d4d;
                border-radius: 16px;
                border: 3px dashed #6AB0F9;
            }
            .drop-label { color: #aaaaaa; font-size: 11px; }
        """)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)

        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(ICON_FILE, 48, 48, True)
            icon = Gtk.Image.new_from_pixbuf(pixbuf)
        except Exception:
            icon = Gtk.Image.new_from_icon_name('weather-clouds', Gtk.IconSize.DIALOG)
        box.pack_start(icon, False, False, 0)

        label = Gtk.Label(label='Drop files here')
        label.get_style_context().add_class('drop-label')
        box.pack_start(label, False, False, 0)

        self.frame = Gtk.EventBox()
        self.frame.get_style_context().add_class('dropzone')
        self.frame.add(box)
        self.add(self.frame)

    def _on_drag_motion(self, widget, context, x, y, time):
        if not self._hovering:
            self._hovering = True
            sc = self.frame.get_style_context()
            sc.remove_class('dropzone')
            sc.add_class('dropzone-hover')
        return True

    def _on_drag_leave(self, widget, context, time):
        self._hovering = False
        sc = self.frame.get_style_context()
        sc.remove_class('dropzone-hover')
        sc.add_class('dropzone')

    def _on_drop(self, widget, context, x, y, data, info, time):
        files = []
        for uri in (data.get_uris() or []):
            path = unquote(urlparse(uri).path)
            if os.path.isfile(path):
                files.append(path)
        if files:
            GLib.idle_add(self.app.upload_files, files)


# ---------------------------------------------------------------------------
# Main Application
# ---------------------------------------------------------------------------

class CloudioApp:

    def __init__(self):
        self.config = load_config()
        self.client = SSHClient(self.config['server'])
        self.drop_zone = None
        self._setup_tray()

    def _setup_tray(self):
        self.indicator = AppIndicator3.Indicator.new(
            'cloudio', ICON_FILE,
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_title('Cloudio')

        menu = Gtk.Menu()

        item = Gtk.MenuItem(label='Upload File...')
        item.connect('activate', lambda w: self._pick_file())
        menu.append(item)

        item = Gtk.MenuItem(label='Toggle Drop Zone')
        item.connect('activate', lambda w: self._toggle_drop_zone())
        menu.append(item)

        menu.append(Gtk.SeparatorMenuItem())

        item = Gtk.MenuItem(label='Quit')
        item.connect('activate', lambda w: Gtk.main_quit())
        menu.append(item)

        menu.show_all()
        self.indicator.set_menu(menu)

    def _toggle_drop_zone(self):
        if self.drop_zone and self.drop_zone.get_visible():
            self.drop_zone.hide()
        else:
            if not self.drop_zone:
                self.drop_zone = DropZoneWindow(self)
            self.drop_zone.show_all()
            self.drop_zone.present()

    def _pick_file(self):
        dialog = Gtk.FileChooserDialog(
            title='Select file to upload', parent=None,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_button('Cancel', Gtk.ResponseType.CANCEL)
        dialog.add_button('Open', Gtk.ResponseType.OK)
        dialog.set_select_multiple(True)
        response = dialog.run()
        files = list(dialog.get_filenames()) if response == Gtk.ResponseType.OK else []
        dialog.destroy()
        if files:
            self.upload_files(files)

    # ------------------------------------------------------------------
    # Upload flow
    # ------------------------------------------------------------------

    def upload_files(self, file_paths):
        if isinstance(file_paths, str):
            file_paths = [file_paths]

        remote_dir = self.config['remote_path']
        base_url = self.config['base_url'].rstrip('/')
        server_name = self.config['server']['name']

        # Progress dialog
        dlg = Gtk.Dialog(title='Uploading...', modal=True)
        dlg.set_default_size(360, -1)
        dlg.set_deletable(False)
        content = dlg.get_content_area()
        content.set_spacing(8)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

        info_label = Gtk.Label()
        info_label.set_line_wrap(True)
        content.pack_start(info_label, False, False, 0)

        progress = Gtk.ProgressBar()
        content.pack_start(progress, False, False, 0)

        status_label = Gtk.Label(label='Connecting...')
        content.pack_start(status_label, False, False, 0)

        content.show_all()
        dlg.show_all()

        pulse_id = GLib.timeout_add(100, lambda: progress.pulse() or True)

        def do_upload():
            urls = []
            total = len(file_paths)
            try:
                # Ensure remote dir exists
                self.client.ssh_run(['mkdir', '-p', remote_dir])

                for i, local_path in enumerate(file_paths, 1):
                    filename = safe_filename(os.path.basename(local_path))
                    remote_path = f"{remote_dir}/{filename}"
                    url = f"{base_url}/{quote(filename)}"

                    GLib.idle_add(info_label.set_markup,
                                  f'<b>{filename}</b>' if total == 1
                                  else f'<b>({i}/{total}) {filename}</b>')
                    GLib.idle_add(status_label.set_text, f'Uploading to {server_name}...')

                    self.client.upload(local_path, remote_path)
                    urls.append(url)

                GLib.idle_add(_on_done, urls, None)
            except Exception as e:
                GLib.idle_add(_on_done, [], str(e))

        def _on_done(urls, error):
            GLib.source_remove(pulse_id)
            dlg.destroy()

            if error:
                self._show_msg(Gtk.MessageType.ERROR, 'Upload failed', error)
                return

            # Copy URL(s) to clipboard
            url_text = '\n'.join(urls)
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(url_text, -1)
            clipboard.store()

            if len(urls) == 1:
                msg = f'{urls[0]}\n\nLink copied to clipboard!'
            else:
                msg = '\n'.join(urls) + f'\n\n{len(urls)} links copied to clipboard!'
            self._show_msg(Gtk.MessageType.INFO, 'Upload complete!', msg)

        threading.Thread(target=do_upload, daemon=True).start()

    def _show_msg(self, msg_type, title, body):
        dlg = Gtk.MessageDialog(
            transient_for=None, modal=True,
            message_type=msg_type,
            buttons=Gtk.ButtonsType.OK,
            text=title, secondary_text=body,
        )
        dlg.run()
        dlg.destroy()


def main():
    app = CloudioApp()
    app._toggle_drop_zone()
    try:
        Gtk.main()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
