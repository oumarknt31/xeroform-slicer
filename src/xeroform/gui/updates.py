"""Is there a newer XeroForm? Asks GitHub at most once a day, and says how to update.

GitHub answers /releases/latest with a redirect to the newest release's tag, so
one small request (no API, no rate limit) tells the latest version. Nothing
else is sent.
"""

from __future__ import annotations
import re
import sys
import time

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .. import __version__
from .constants import REPO_URL

LATEST_URL = f"{REPO_URL}/releases/latest"
CHECK_EVERY = 20 * 3600  # seconds between automatic checks
_INSTALL = "https://raw.githubusercontent.com/oumarknt31/xeroform-slicer/main/install"


def version_in(url: str) -> str | None:
    """The version a release URL points at: ".../releases/tag/v0.4.0" -> "0.4.0"."""
    m = re.search(r"/releases/tag/v?(\d+(?:\.\d+)*)/?$", url or "")
    return m.group(1) if m else None


def is_newer(candidate: str, current: str = __version__) -> bool:
    def parts(v):
        return tuple(int(n) for n in re.findall(r"\d+", v)[:3])

    return parts(candidate) > parts(current)


def install_command(platform: str = sys.platform) -> str:
    """The one-line installer for this computer; running it again updates XeroForm."""
    if platform.startswith("win"):
        return f"irm {_INSTALL}/install-windows.ps1 | iex"
    if platform == "darwin":
        return f"curl -fsSL {_INSTALL}/install-mac.sh | sh"
    return f"curl -fsSL {_INSTALL}/install-linux.sh | sh"


class UpdateChecker(QObject):
    """After `check`: `found(version)` when a newer release exists, else
    `up_to_date`, or `failed(message)` when GitHub couldn't be asked."""

    found = Signal(str)
    up_to_date = Signal()
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.net = QNetworkAccessManager(self)

    def due(self, last_checked: float | None) -> bool:
        return last_checked is None or time.time() - float(last_checked) > CHECK_EVERY

    def check(self) -> QNetworkReply:
        request = QNetworkRequest(QUrl(LATEST_URL))
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.ManualRedirectPolicy)
        request.setHeader(QNetworkRequest.UserAgentHeader, f"XeroForm/{__version__}")
        request.setTransferTimeout(15000)
        reply = self.net.head(request)
        reply.finished.connect(lambda: self._answered(reply))
        return reply

    def _answered(self, reply: QNetworkReply) -> None:
        location = reply.header(QNetworkRequest.LocationHeader)
        url = location.toString() if isinstance(location, QUrl) else str(location or "")
        error = reply.errorString() if reply.error() != QNetworkReply.NoError else ""
        reply.deleteLater()
        self.handle(url, error)

    def handle(self, location: str, error: str = "") -> None:
        latest = version_in(location)
        if latest is None:
            self.failed.emit(error or "GitHub didn't say which version is the latest.")
        elif is_newer(latest):
            self.found.emit(latest)
        else:
            self.up_to_date.emit()
