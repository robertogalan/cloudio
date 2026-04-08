#!/usr/bin/env python3
"""Cloudio for macOS – menu bar file uploader with native drag-and-drop.

The cloud icon lives in the menu bar and doubles as a drop zone:
drag any files onto it to upload instantly.

Requirements:
    pip install pyobjc-core pyobjc-framework-Cocoa
"""

import json
import os
import sys
import threading
from pathlib import Path
from urllib.parse import quote

import objc
import AppKit
import Foundation

# ---------------------------------------------------------------------------
# Shared modules (parent directory)
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent))
from ssh_client import SSHClient  # noqa: E402

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CONFIG_DIR = Path.home() / '.config' / 'cloudio'
CONFIG_PATH = CONFIG_DIR / 'config.json'
ASSETS_DIR = Path(__file__).parent.parent / 'assets'

# Pasteboard type – prefer modern name, fall back to legacy
_PASTE_STRING = getattr(AppKit, 'NSPasteboardTypeString',
                        getattr(AppKit, 'NSStringPboardType', 'public.utf8-plain-text'))
_MODAL_OK = getattr(AppKit, 'NSModalResponseOK', 1)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return None


def save_config(cfg):
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(CONFIG_PATH, 'w') as f:
        json.dump(cfg, f, indent=2)
    os.chmod(CONFIG_PATH, 0o600)  # owner read/write only — config contains credentials


def safe_filename(name):
    """Sanitize a filename for safe remote storage and clean URLs.

    Keeps only alphanumerics, hyphens, underscores, and dots.
    Everything else (spaces, slashes, control chars, path traversal)
    becomes an underscore.
    """
    import re
    name = os.path.basename(name)          # strip any directory component
    name = re.sub(r'[^\w.\-]', '_', name)  # allow only safe chars
    name = re.sub(r'\.{2,}', '_', name)    # collapse .. sequences
    return name or '_'


# ---------------------------------------------------------------------------
# Icon loader
# ---------------------------------------------------------------------------

def make_menu_bar_icon():
    """Return an NSImage for the menu bar.

    Priority:
      1. SF Symbol 'icloud.and.arrow.up'  (macOS 11+, native look)
      2. Bundled cloud.png                (fallback)
    """
    if hasattr(AppKit.NSImage, 'imageWithSystemSymbolName_accessibilityDescription_'):
        img = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            'icloud.and.arrow.up', None
        )
        if img:
            img.setTemplate_(True)
            return img

    png = str(ASSETS_DIR / 'cloud.png')
    if os.path.exists(png):
        img = AppKit.NSImage.alloc().initWithContentsOfFile_(png)
        if img:
            img.setSize_(Foundation.NSMakeSize(18, 18))
            img.setTemplate_(True)
            return img

    return None


# ---------------------------------------------------------------------------
# DropView – custom NSView that accepts file drops
#
# We attach this as the status item's view (via the deprecated-but-working
# setView_ API) so that the cloud icon itself becomes a drop target.
# This is the most reliable cross-version approach; if Apple ever removes
# setView_ we can swap in the overlay-window technique.
# ---------------------------------------------------------------------------

class DropView(AppKit.NSView):

    def initWithFrame_(self, frame):
        self = objc.super(DropView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._status_item = None
        self._app = None
        self._dragging = False

        # NSImageView handles template image dark/light mode automatically.
        # Drawing template images manually in drawRect_ always renders black
        # regardless of appearance; NSImageView does the right thing.
        icon = make_menu_bar_icon()
        if icon:
            thickness = AppKit.NSStatusBar.systemStatusBar().thickness()
            sz = 18.0
            iv = AppKit.NSImageView.alloc().initWithFrame_(
                Foundation.NSMakeRect(
                    (frame.size.width - sz) / 2,
                    (thickness - sz) / 2,
                    sz, sz
                )
            )
            iv.setImage_(icon)
            iv.setAutoresizingMask_(
                AppKit.NSViewMinXMargin | AppKit.NSViewMaxXMargin |
                AppKit.NSViewMinYMargin | AppKit.NSViewMaxYMargin
            )
            self.addSubview_(iv)
            self._image_view = iv

        return self

    @objc.python_method
    def _setup(self, status_item, app):
        """Call after alloc/initWithFrame_ to wire up references."""
        self._status_item = status_item
        self._app = app
        self.registerForDraggedTypes_([AppKit.NSFilenamesPboardType])

    # --- Drawing ---

    def drawRect_(self, rect):
        # Only need to draw the drag-highlight background;
        # the icon is handled by the NSImageView subview.
        if self._dragging:
            AppKit.NSColor.selectedMenuItemColor().set()
            AppKit.NSBezierPath.fillRect_(rect)

    # --- Mouse click → open menu ---

    def mouseDown_(self, event):
        if self._status_item and self._app:
            self._status_item.popUpStatusItemMenu_(self._app.menu)
        self.setNeedsDisplay_(True)

    # --- Drag-and-drop protocol ---

    def draggingEntered_(self, sender):
        if AppKit.NSFilenamesPboardType in (sender.draggingPasteboard().types() or []):
            self._dragging = True
            self.setNeedsDisplay_(True)
            return AppKit.NSDragOperationCopy
        return AppKit.NSDragOperationNone

    def draggingUpdated_(self, sender):
        if AppKit.NSFilenamesPboardType in (sender.draggingPasteboard().types() or []):
            return AppKit.NSDragOperationCopy
        return AppKit.NSDragOperationNone

    def draggingExited_(self, sender):
        self._dragging = False
        self.setNeedsDisplay_(True)

    def prepareForDragOperation_(self, sender):
        return True

    def performDragOperation_(self, sender):
        self._dragging = False
        self.setNeedsDisplay_(True)
        files = sender.draggingPasteboard().propertyListForType_(
            AppKit.NSFilenamesPboardType
        )
        if files and self._app:
            self._app.upload_files(list(files))
        return True

    def concludeDragOperation_(self, sender):
        self.setNeedsDisplay_(True)


# ---------------------------------------------------------------------------
# Main application controller
# ---------------------------------------------------------------------------

class CloudioApp(Foundation.NSObject):

    def init(self):
        self = objc.super(CloudioApp, self).init()
        if self is None:
            return None
        self._config = load_config()
        self._config_win = None
        self._setup_status_item()
        self._build_menu()
        return self

    # --- Status item setup ---

    def _setup_status_item(self):
        bar = AppKit.NSStatusBar.systemStatusBar()
        self._item = bar.statusItemWithLength_(AppKit.NSVariableStatusItemLength)

        thickness = bar.thickness()
        frame = Foundation.NSMakeRect(0, 0, 28, thickness)
        self._drop_view = DropView.alloc().initWithFrame_(frame)
        self._drop_view._setup(self._item, self)

        # setView_ is deprecated (10.10) but reliable on all shipping macOS.
        # It gives us a fully custom NSView that can accept drag operations.
        if hasattr(self._item, 'setView_'):
            self._item.setView_(self._drop_view)
        else:
            # Fallback: modern button without drag-on-icon (still works)
            btn = self._item.button()
            icon = make_menu_bar_icon()
            if icon:
                btn.setImage_(icon)
            btn.setToolTip_('Cloudio – drag files here to upload')

    # --- Menu ---

    def _build_menu(self):
        self.menu = AppKit.NSMenu.alloc().init()

        upload = self._menu_item('Upload File…', 'uploadFile:', '')
        self.menu.addItem_(upload)

        self.menu.addItem_(AppKit.NSMenuItem.separatorItem())

        configure = self._menu_item('Configure…', 'openConfig:', ',')
        self.menu.addItem_(configure)

        self.menu.addItem_(AppKit.NSMenuItem.separatorItem())

        quit_item = self._menu_item('Quit Cloudio', 'quitApp:', 'q')
        self.menu.addItem_(quit_item)

    @objc.python_method
    def _menu_item(self, title, action, key):
        item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            title, action, key
        )
        item.setTarget_(self)
        return item

    # --- Actions ---

    def uploadFile_(self, sender):
        panel = AppKit.NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(True)
        panel.setCanChooseDirectories_(False)
        panel.setAllowsMultipleSelection_(True)
        panel.setTitle_('Select Files to Upload')
        if panel.runModal() == _MODAL_OK:
            paths = [str(u.path()) for u in panel.URLs()]
            if paths:
                self.upload_files(paths)

    def quitApp_(self, sender):
        AppKit.NSApp.terminate_(sender)

    def openConfig_(self, sender):
        # Lazy import to avoid circular deps
        from config_window import ConfigWindow  # noqa: PLC0415
        if not self._config_win:
            self._config_win = ConfigWindow.alloc().init()
            self._config_win.setApp_(self)
        self._config_win.show()

    # --- Upload logic ---

    @objc.python_method
    def upload_files(self, paths):
        """Entry point called from drop or menu. Runs upload on a bg thread."""
        if not self._config:
            self._alert(
                'Cloudio – Not Configured',
                'Click the cloud icon → Configure… to set up your server first.'
            )
            return
        threading.Thread(target=self._do_upload, args=(paths,), daemon=True).start()

    @objc.python_method
    def _do_upload(self, paths):
        cfg = self._config
        server_cfg = cfg['server']
        remote_dir = cfg['remote_path'].rstrip('/')
        base_url = cfg['base_url'].rstrip('/')
        urls = []

        def on_main(fn):
            AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(fn)

        try:
            client = SSHClient(server_cfg)
            client.ssh_run(['mkdir', '-p', remote_dir])

            for path in paths:
                fname = safe_filename(os.path.basename(path))
                on_main(lambda f=fname: self._item.setTitle_(f'  ↑ {f}'))
                client.upload(path, f'{remote_dir}/{fname}')
                urls.append(f'{base_url}/{quote(fname)}')

            on_main(lambda: self._upload_done(urls))

        except Exception as exc:
            on_main(lambda e=str(exc): self._alert('Upload Failed', e))
        finally:
            on_main(lambda: self._item.setTitle_(''))

    @objc.python_method
    def _upload_done(self, urls):
        pb = AppKit.NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_('\n'.join(urls), _PASTE_STRING)
        n = len(urls)
        self._alert(
            'Upload Complete',
            f'{n} file{"s" if n > 1 else ""} uploaded. '
            f'URL{"s" if n > 1 else ""} copied to clipboard.'
        )

    def reload_config(self):
        """Called by ConfigWindow after saving."""
        self._config = load_config()

    # --- Helpers ---

    @objc.python_method
    def _alert(self, title, msg):
        """Show a native alert. Must be called on the main thread."""
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(msg)
        alert.addButtonWithTitle_('OK')
        alert.runModal()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    AppKit.NSApplication.sharedApplication()
    # Accessory policy = no Dock icon, no app switcher entry
    AppKit.NSApp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

    delegate = CloudioApp.alloc().init()
    # Keep a strong reference via the app delegate to prevent GC
    AppKit.NSApp.setDelegate_(delegate)

    AppKit.NSApp.run()


if __name__ == '__main__':
    main()
