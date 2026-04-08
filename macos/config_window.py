"""Cloudio macOS – Server configuration window.

A native NSWindow form for editing config.json settings.
Imported lazily by cloudio_mac.py when the user clicks Configure….
"""

import json
import os
import sys
import threading
from pathlib import Path

import objc
import AppKit
import Foundation

sys.path.insert(0, str(Path(__file__).parent.parent))
from ssh_client import SSHClient  # noqa: E402

CONFIG_DIR = Path.home() / '.config' / 'cloudio'
CONFIG_PATH = CONFIG_DIR / 'config.json'


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

# ---------------------------------------------------------------------------
# Layout constants (all in points, y=0 at bottom – Cocoa coordinate system)
# ---------------------------------------------------------------------------
W = 490          # window width
PAD = 20         # horizontal margin
LABEL_W = 110    # right-aligned label column width
FIELD_X = PAD + LABEL_W + 10   # 140
FIELD_W = W - FIELD_X - PAD    # 330
FIELD_H = 22
ROW_H = 32       # vertical step between rows
BROWSE_W = 44    # "…" browse button width

# Computed window height (see _build for the row list)
H = 450


# ---------------------------------------------------------------------------
# Widget factories
# ---------------------------------------------------------------------------

def _label(text, x, y, w, h=17, bold=False, align=AppKit.NSTextAlignmentRight):
    lbl = AppKit.NSTextField.labelWithString_(text)
    lbl.setFrame_(Foundation.NSMakeRect(x, y, w, h))
    lbl.setAlignment_(align)
    if bold:
        lbl.setFont_(AppKit.NSFont.boldSystemFontOfSize_(13))
    return lbl


def _field(x, y, w=None, secure=False):
    w = w or FIELD_W
    cls = AppKit.NSSecureTextField if secure else AppKit.NSTextField
    fld = cls.alloc().initWithFrame_(Foundation.NSMakeRect(x, y, w, FIELD_H))
    fld.setEditable_(True)
    fld.setBezeled_(True)
    return fld


def _button(title, x, y, w, h, target, action):
    btn = AppKit.NSButton.buttonWithTitle_target_action_(title, target, action)
    btn.setFrame_(Foundation.NSMakeRect(x, y, w, h))
    return btn


def _separator(y, content_view):
    box = AppKit.NSBox.alloc().initWithFrame_(
        Foundation.NSMakeRect(PAD, y, W - 2 * PAD, 1)
    )
    box.setBoxType_(AppKit.NSBoxSeparator)
    content_view.addSubview_(box)


# ---------------------------------------------------------------------------
# ConfigWindow
# ---------------------------------------------------------------------------

class ConfigWindow(Foundation.NSObject):

    def init(self):
        self = objc.super(ConfigWindow, self).init()
        if self is None:
            return None
        self._app = None
        self._win = None
        self._fields = {}       # key → NSTextField / NSPopUpButton
        self._key_views = []    # shown only when auth=key
        self._pwd_views = []    # shown only when auth=password
        return self

    def setApp_(self, app):
        self._app = app

    def show(self):
        if self._win is None:
            self._build()
        self._load_into_fields()
        self._win.makeKeyAndOrderFront_(None)
        AppKit.NSApp.activateIgnoringOtherApps_(True)

    # --- Window construction (built once, reused) ---

    def _build(self):
        screen = AppKit.NSScreen.mainScreen().frame()
        wx = (screen.size.width - W) / 2
        wy = (screen.size.height - H) / 2

        mask = (AppKit.NSWindowStyleMaskTitled |
                AppKit.NSWindowStyleMaskClosable)
        self._win = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            Foundation.NSMakeRect(wx, wy, W, H),
            mask,
            AppKit.NSBackingStoreBuffered,
            False
        )
        self._win.setTitle_('Cloudio — Configure Server')
        self._win.setDelegate_(self)
        cv = self._win.contentView()

        # Build rows from bottom up (Cocoa y=0 at bottom)
        y = 14

        # ── Bottom buttons ────────────────────────────────────────────────
        cancel = _button('Cancel', PAD, y, 90, 28, self, 'cancelConfig:')
        cv.addSubview_(cancel)

        test = _button('Test Connection', PAD + 100, y, 150, 28, self, 'testConnection:')
        cv.addSubview_(test)

        save = _button('Save', W - PAD - 90, y, 90, 28, self, 'saveConfig:')
        save.setKeyEquivalent_('\r')
        save.setBezelStyle_(AppKit.NSBezelStyleRounded)
        cv.addSubview_(save)

        y += 28 + 14

        # ── Separator ─────────────────────────────────────────────────────
        _separator(y, cv)
        y += 1 + 14

        # ── Publishing section ────────────────────────────────────────────
        y = self._add_text_row(cv, y, 'base_url', 'Base URL')
        y = self._add_text_row(cv, y, 'remote_path', 'Remote Path')

        y += 8
        _separator(y, cv)
        y += 1 + 14

        # ── Auth section (conditional rows) ──────────────────────────────
        # Password row (hidden when auth=key)
        pwd_lbl = _label('Password', PAD, y + 3, LABEL_W)
        pwd_fld = _field(FIELD_X, y, secure=True)
        cv.addSubview_(pwd_lbl)
        cv.addSubview_(pwd_fld)
        self._fields['password'] = pwd_fld
        self._pwd_views = [pwd_lbl, pwd_fld]
        y += ROW_H

        # Key Path row (hidden when auth=password)
        key_lbl = _label('Key Path', PAD, y + 3, LABEL_W)
        key_fld = _field(FIELD_X, y, w=FIELD_W - BROWSE_W - 8)
        browse = _button('…', FIELD_X + (FIELD_W - BROWSE_W - 8) + 8,
                         y - 1, BROWSE_W, FIELD_H + 2, self, 'browseKeyPath:')
        cv.addSubview_(key_lbl)
        cv.addSubview_(key_fld)
        cv.addSubview_(browse)
        self._fields['key_path'] = key_fld
        self._key_views = [key_lbl, key_fld, browse]
        y += ROW_H

        # Auth Type popup
        cv.addSubview_(_label('Auth Type', PAD, y + 3, LABEL_W))
        popup = AppKit.NSPopUpButton.alloc().initWithFrame_(
            Foundation.NSMakeRect(FIELD_X, y, 160, FIELD_H + 2)
        )
        popup.addItemsWithTitles_(['SSH Key', 'Password'])
        popup.setTarget_(self)
        popup.setAction_('authTypeChanged:')
        cv.addSubview_(popup)
        self._fields['auth_type'] = popup
        y += ROW_H

        y += 4
        _separator(y, cv)
        y += 1 + 14

        # ── Server section ────────────────────────────────────────────────
        y = self._add_text_row(cv, y, 'user', 'Username')
        y = self._add_text_row(cv, y, 'port', 'Port', field_w=70)
        y = self._add_text_row(cv, y, 'host', 'Host')
        y = self._add_text_row(cv, y, 'server_name', 'Server Name')

        y += 8

        # ── Title ─────────────────────────────────────────────────────────
        title = _label('Server Configuration', PAD, y, W - 2 * PAD, 20,
                       bold=True, align=AppKit.NSTextAlignmentLeft)
        cv.addSubview_(title)

    @objc.python_method
    def _add_text_row(self, cv, y, key, text, field_w=None):
        cv.addSubview_(_label(text, PAD, y + 3, LABEL_W))
        fld = _field(FIELD_X, y, w=field_w)
        cv.addSubview_(fld)
        self._fields[key] = fld
        return y + ROW_H

    # --- Load / save config -----------------------------------------------

    def _load_into_fields(self):
        cfg = load_config() or {}
        srv = cfg.get('server', {})

        def set_f(key, val):
            f = self._fields.get(key)
            if f is None or val is None:
                return
            if isinstance(f, AppKit.NSPopUpButton):
                f.selectItemWithTitle_('Password' if val == 'password' else 'SSH Key')
            else:
                f.setStringValue_(str(val))

        set_f('server_name', srv.get('name', ''))
        set_f('host', srv.get('host', ''))
        set_f('port', srv.get('port', 22))
        set_f('user', srv.get('user', ''))
        set_f('auth_type', srv.get('auth_type', 'key'))
        set_f('key_path', srv.get('key_path', ''))
        set_f('password', srv.get('password', ''))
        set_f('remote_path', cfg.get('remote_path', ''))
        set_f('base_url', cfg.get('base_url', ''))

        self._update_auth_rows()

    @objc.python_method
    def _fv(self, key):
        """Get string value from a field."""
        f = self._fields.get(key)
        if f is None:
            return ''
        if isinstance(f, AppKit.NSPopUpButton):
            return f.titleOfSelectedItem() or ''
        return f.stringValue() or ''

    def _current_server_config(self):
        """Build a server dict from current field values (for test / save)."""
        auth = 'password' if self._fv('auth_type') == 'Password' else 'key'
        srv = {
            'name': self._fv('server_name'),
            'host': self._fv('host'),
            'port': int(self._fv('port') or 22),
            'user': self._fv('user'),
            'auth_type': auth,
        }
        if auth == 'key':
            srv['key_path'] = self._fv('key_path')
        else:
            srv['password'] = self._fv('password')
        return srv

    # --- UI callbacks -------------------------------------------------------

    def authTypeChanged_(self, sender):
        self._update_auth_rows()

    def _update_auth_rows(self):
        is_key = self._fv('auth_type') != 'Password'
        for v in self._key_views:
            v.setHidden_(not is_key)
        for v in self._pwd_views:
            v.setHidden_(is_key)

    def browseKeyPath_(self, sender):
        panel = AppKit.NSOpenPanel.openPanel()
        panel.setTitle_('Select SSH Private Key')
        panel.setCanChooseFiles_(True)
        panel.setCanChooseDirectories_(False)
        panel.setAllowsMultipleSelection_(False)
        if panel.runModal() == getattr(AppKit, 'NSModalResponseOK', 1):
            f = self._fields.get('key_path')
            if f:
                f.setStringValue_(str(panel.URL().path()))

    def saveConfig_(self, sender):
        srv = self._current_server_config()
        cfg = {
            'server': srv,
            'remote_path': self._fv('remote_path'),
            'base_url': self._fv('base_url'),
        }
        save_config(cfg)
        if self._app:
            self._app.reload_config()
        self._win.orderOut_(None)
        self._show_alert('Saved', 'Configuration saved successfully.', success=True)

    def cancelConfig_(self, sender):
        self._win.orderOut_(None)

    def testConnection_(self, sender):
        srv = self._current_server_config()

        def do_test():
            try:
                client = SSHClient(srv)
                client.ssh_run(['echo', 'cloudio_ok'])
                AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
                    lambda: self._show_alert(
                        'Connection Successful',
                        f'Connected to {srv["host"]} as {srv["user"]}.',
                        success=True
                    )
                )
            except Exception as exc:
                AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
                    lambda e=str(exc): self._show_alert('Connection Failed', e, success=False)
                )

        threading.Thread(target=do_test, daemon=True).start()

    @objc.python_method
    def _show_alert(self, title, msg, success=True):
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(msg)
        alert.addButtonWithTitle_('OK')
        style = (AppKit.NSAlertStyleInformational if success
                 else AppKit.NSAlertStyleCritical)
        alert.setAlertStyle_(style)
        alert.runModal()

    # --- NSWindowDelegate ---------------------------------------------------

    def windowWillClose_(self, notification):
        # Hide rather than destroy so state is preserved
        pass
