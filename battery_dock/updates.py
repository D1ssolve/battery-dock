"""Manual metadata-only update checks. No downloads, execution or installation."""
from __future__ import annotations
from dataclasses import dataclass
import json
from http.client import HTTPException
import re
from urllib import request, error
import time

API_URL = 'https://api.github.com/repos/D1ssolve/battery-dock/releases/latest'
MAX_BYTES = 128 * 1024
TIMEOUT = 5
_VERSION = re.compile(r'v?(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\Z')


class UpdateCheckError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    url: str
    update_available: bool


def version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise UpdateCheckError('Unsupported stable release version')
    return tuple(int(part) for part in match.groups())


def parse_release(data: object, current_version: str) -> ReleaseInfo:
    if not isinstance(data, dict) or data.get('draft') is not False or data.get('prerelease') is not False:
        raise UpdateCheckError('Not a published stable release')
    tag = data.get('tag_name')
    version = version_tuple(tag)
    url = data.get('html_url')
    if not isinstance(url, str):
        raise UpdateCheckError('Missing release link')
    # Strict canonical link: disallow userinfo, ports, encoded paths and redirects.
    expected = 'https://github.com/D1ssolve/battery-dock/releases/tag/' + tag
    if url != expected:
        raise UpdateCheckError('Unexpected release link')
    return ReleaseInfo(tag.removeprefix('v'), url, version > version_tuple(current_version))


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise UpdateCheckError('Unexpected redirect from release API')


def check_latest_release(current_version: str) -> ReleaseInfo:
    """Run off the GUI thread, only when the user requests a check.

    One request, a five-second socket timeout, and a capped response. No tokens,
    device identifiers or settings are sent. GitHub sees the caller's IP.
    """
    version_tuple(current_version)
    req = request.Request(API_URL, headers={
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'BatteryDock/manual-update-check',
        'X-GitHub-Api-Version': '2022-11-28',
    })
    try:
        opener = request.build_opener(_NoRedirect())
        with opener.open(req, timeout=TIMEOUT) as response:
            if response.geturl() != API_URL:
                raise UpdateCheckError('Unexpected release API location')
            deadline = time.monotonic() + TIMEOUT
            chunks = []
            size = 0
            while size <= MAX_BYTES:
                if time.monotonic() >= deadline:
                    raise UpdateCheckError('Release response timed out')
                chunk = response.read1(min(8192, MAX_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            payload = b''.join(chunks)
        if len(payload) > MAX_BYTES:
            raise UpdateCheckError('Release response is too large')
        return parse_release(json.loads(payload), current_version)
    except UpdateCheckError:
        raise
    except (OSError, error.URLError, HTTPException, ValueError, TypeError) as exc:
        # Do not expose proxy credentials/URLs or arbitrary remote content in UI.
        raise UpdateCheckError('Could not check releases; check connection or try later') from exc
