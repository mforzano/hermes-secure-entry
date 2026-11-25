"""Private Link output inbox. No model-supplied file paths or stdout.

Windows: ACLs are established before Link creates the file, not repaired after
a leak. A no-sharing, no-follow, delete-on-close kernel handle consumes each
file once.

POSIX (Linux, macOS): the inbox directory is created mode 0700 and the file is
accepted only if it is a regular, single-link, owner-owned file with no group
or other permission bits (0600 is what Link requests). It is opened with
O_NOFOLLOW relative to the directory handle, read through that descriptor and
unlinked by name only while the name still refers to the same inode.
"""

import json
import os
import re
import secrets
import stat
from pathlib import Path
from urllib.parse import urlsplit
from contextlib import contextmanager

_WINDOWS = os.name == "nt"
# Name of the category used when the access-control check itself fails.
ACL_CATEGORY = "windows_acl" if _WINDOWS else "posix_acl"
_MAX_BYTES = 16384
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)


class PrivateFileRefused(ValueError):
    """Only fixed categories cross the private-artifact boundary."""

    CATEGORIES = frozenset({
        "closed", "windows_api", "directory_open", "directory_info",
        "directory_reparse", "windows_acl", "posix_acl", "owner", "file_open",
        "file_info", "filetype", "linkcount", "size", "read", "json", "object",
        "request_match", "merchant_origin", "card_type", "card_number_type",
        "card_number_format", "cvc_type_format", "expiry_type_range",
        "billing_type", "billing_field_type", "billing_field_format",
        "private_file_failed", "owner_normalize",
    })

    def __init__(self, category, *, owner_class=None):
        super().__init__("private_file_refused")
        self.category = category if category in self.CATEGORIES else "private_file_failed"
        self.owner_class = owner_class if owner_class in self.OWNER_CLASSES else None
        self.object_type = None

    OWNER_CLASSES = frozenset({"user", "system", "token_default", "administrators", "other"})


@contextmanager
def _handle(handle):
    try:
        yield handle
    finally:
        handle.Close()


def _windows():
    import win32api
    import win32con
    import win32file
    import win32security
    import pywintypes

    return win32api, win32con, win32file, win32security, pywintypes


def _token_identity():
    """Use the effective token; only ERROR_NO_TOKEN permits process fallback."""
    api, con, _, sec, _ = _windows()
    try:
        token = sec.OpenThreadToken(api.GetCurrentThread(), con.TOKEN_QUERY, True)
    except Exception as exc:
        if getattr(exc, "winerror", None) != 1008:
            raise
        token = sec.OpenProcessToken(api.GetCurrentProcess(), con.TOKEN_QUERY)
    with _handle(token):
        return (sec.GetTokenInformation(token, sec.TokenUser)[0],
                sec.GetTokenInformation(token, sec.TokenOwner))


def _identity():
    return _token_identity()[0]


def _check_acl(handle):
    _, con, _, sec, _ = _windows()
    sd = sec.GetSecurityInfo(
        handle,
        sec.SE_FILE_OBJECT,
        sec.OWNER_SECURITY_INFORMATION | sec.DACL_SECURITY_INFORMATION,
    )
    user, default_owner = _token_identity()
    allowed = {sec.ConvertSidToStringSid(user), "S-1-5-18"}
    acl = sd.GetSecurityDescriptorDacl()
    if acl is None:
        raise PrivateFileRefused("windows_acl")
    for i in range(acl.GetAceCount()):
        header, mask, sid = acl.GetAce(i)
        if (
            header[0] != con.ACCESS_ALLOWED_ACE_TYPE
            or sec.ConvertSidToStringSid(sid) not in allowed
        ):
            raise PrivateFileRefused("windows_acl")
    owner = sd.GetSecurityDescriptorOwner()
    if sec.ConvertSidToStringSid(owner) not in allowed:
        if owner != default_owner:
            classification = "administrators" if sec.ConvertSidToStringSid(owner) == "S-1-5-32-544" else "other"
            raise PrivateFileRefused("owner", owner_class=classification)
        # Windows can assign an enabled token group as the creator's default
        # owner. Never accept that group's implicit WRITE_DAC authority: narrow
        # ownership to TokenUser on the same exclusive handle before any read.
        # DACL validation precedes this write; no foreign owner is repaired.
        try:
            sec.SetSecurityInfo(handle, sec.SE_FILE_OBJECT,
                                sec.OWNER_SECURITY_INFORMATION, user, None, None, None)
        except Exception:
            raise PrivateFileRefused("owner_normalize", owner_class="token_default") from None
        verified = sec.GetSecurityInfo(handle, sec.SE_FILE_OBJECT,
                                      sec.OWNER_SECURITY_INFORMATION | sec.DACL_SECURITY_INFORMATION)
        if verified.GetSecurityDescriptorOwner() != user:
            raise PrivateFileRefused("owner")
        # Changing owner must not change any DACL ACE.
        after = verified.GetSecurityDescriptorDacl()
        if (after is None or after.GetAceCount() != acl.GetAceCount()
                or any(after.GetAce(i) != acl.GetAce(i) for i in range(acl.GetAceCount()))):
            raise PrivateFileRefused("windows_acl")


def _current_uid():
    return os.geteuid()


def _check_posix_acl(info):
    """Owner-only: the owner must be this user and no group/other bits may be set.

    A POSIX ACL cannot widen access past the group bits, so a clear group/other
    mask also rules out named-user and named-group entries.
    """
    if info.st_uid != _current_uid():
        raise PrivateFileRefused("owner", owner_class="other")
    if info.st_mode & 0o077:
        raise PrivateFileRefused("posix_acl")


def _read_bounded(fd, limit):
    chunks = []
    total = 0
    while total < limit:
        chunk = os.read(fd, min(65536, limit - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)


def _unlink_if_same(dir_fd, name, info):
    """Delete the consumed file only while the name still refers to our inode."""
    try:
        current = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return True
    if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
        return False
    os.unlink(name, dir_fd=dir_fd)
    return True


def _payload(raw, request_id, merchant_origin):
    """Validate the bounded Link artifact bytes. Raises only fixed categories."""
    try:
        data = json.loads(raw)
    except Exception:
        raise PrivateFileRefused("json") from None
    if not isinstance(data, dict):
        raise PrivateFileRefused("object")
    if data.get("spend_request_id") != request_id:
        raise PrivateFileRefused("request_match")
    try:
        origin = _origin(data.get("merchant_url", ""))
    except Exception:
        raise PrivateFileRefused("merchant_origin") from None
    if origin != merchant_origin:
        raise PrivateFileRefused("merchant_origin")
    card = data.get("card", {})
    if not isinstance(card, dict):
        raise PrivateFileRefused("card_type")
    if not isinstance(card.get("number"), str):
        raise PrivateFileRefused("card_number_type")
    if not re.fullmatch(r"[0-9]{12,19}", card["number"]):
        raise PrivateFileRefused("card_number_format")
    if "cvc" in card and (
        not isinstance(card["cvc"], str)
        or not re.fullmatch(r"[0-9]{3,4}", card["cvc"])
    ):
        raise PrivateFileRefused("cvc_type_format")
    if (
        type(card.get("exp_month")) is not int
        or not 1 <= card["exp_month"] <= 12
        or type(card.get("exp_year")) is not int
        or not 2026 <= card["exp_year"] <= 2100
    ):
        raise PrivateFileRefused("expiry_type_range")
    result = {
        k: card[k]
        for k in ("number", "cvc", "exp_month", "exp_year")
        if k in card
    }
    if "billing_address" in card:
        billing = card["billing_address"]
        if not isinstance(billing, dict):
            raise PrivateFileRefused("billing_type")
        if any(not isinstance(v, str) for v in billing.values()):
            raise PrivateFileRefused("billing_field_type")
        if any(
            len(v) > 256 or any(ord(c) < 32 for c in v)
            for v in billing.values()
        ):
            raise PrivateFileRefused("billing_field_format")
        result["billing_address"] = {
            k: v
            for k, v in billing.items()
            if k
            in (
                "name",
                "line1",
                "line2",
                "city",
                "state",
                "postal_code",
                "country",
            )
        }
    return result


class PrivateCard:
    def __init__(self, root):
        self.directory = Path(root) / ("link-payment-" + secrets.token_hex(24))
        self.path = self.directory / "card.json"
        self.closed = False

    def __enter__(self):
        if not _WINDOWS:
            # mkdir applies the umask only by removing bits, so the result is
            # owner-only from creation; no window exists with wider access.
            os.mkdir(self.directory, 0o700)
            return self
        _, con, file, sec, types = _windows()
        acl = sec.ACL()
        flags = con.OBJECT_INHERIT_ACE | con.CONTAINER_INHERIT_ACE
        for sid in (_identity(), sec.ConvertStringSidToSid("S-1-5-18")):
            acl.AddAccessAllowedAceEx(sec.ACL_REVISION, flags, 0x1F01FF, sid)
        sd = sec.SECURITY_DESCRIPTOR()
        sd.SetSecurityDescriptorOwner(_identity(), False)
        sd.SetSecurityDescriptorDacl(True, acl, False)
        sd.SetSecurityDescriptorControl(sec.SE_DACL_PROTECTED, sec.SE_DACL_PROTECTED)
        attrs = types.SECURITY_ATTRIBUTES()
        attrs.SECURITY_DESCRIPTOR = sd
        file.CreateDirectory(str(self.directory), attrs)
        return self

    def _consume_posix(self, request_id, merchant_origin):
        category = "directory_open"
        object_type = None
        dir_fd = None
        file_fd = None
        info = None
        try:
            if self.closed:
                raise PrivateFileRefused("closed")
            # O_NOFOLLOW on the directory refuses a symlinked inbox (ELOOP).
            dir_fd = os.open(self.directory, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
            category = "directory_info"
            dir_info = os.fstat(dir_fd)
            if not stat.S_ISDIR(dir_info.st_mode):
                raise PrivateFileRefused("directory_info")
            category = ACL_CATEGORY
            object_type = "directory"
            _check_posix_acl(dir_info)
            category = "file_open"
            # Relative to the verified directory handle; no-follow; FIFO-safe.
            file_fd = os.open(
                self.path.name,
                os.O_RDONLY | _O_NOFOLLOW | _O_NONBLOCK,
                dir_fd=dir_fd,
            )
            category = "file_info"
            info = os.fstat(file_fd)
            object_type = "file"
            if not stat.S_ISREG(info.st_mode):
                raise PrivateFileRefused("filetype")
            if info.st_nlink != 1:
                raise PrivateFileRefused("linkcount")
            if info.st_size > _MAX_BYTES:
                raise PrivateFileRefused("size")
            category = ACL_CATEGORY
            _check_posix_acl(info)
            category = "read"
            raw = _read_bounded(file_fd, _MAX_BYTES + 1)
            if len(raw) > _MAX_BYTES:
                raise PrivateFileRefused("size")
            category = "json"
            return _payload(raw, request_id, merchant_origin)
        except PrivateFileRefused as exc:
            exc.object_type = object_type
            raise
        except Exception:
            raise PrivateFileRefused(category) from None
        finally:
            if file_fd is not None:
                os.close(file_fd)
            if info is not None:
                # Single use: delete on success and refusal alike, as the
                # Windows delete-on-close handle does. A swapped-in name is
                # never deleted; it fails closed on the next step instead.
                if not _unlink_if_same(dir_fd, self.path.name, info):
                    raise PrivateFileRefused("file_info", owner_class=None)
            if dir_fd is not None:
                os.close(dir_fd)

    def consume(self, request_id, merchant_origin):
        if not _WINDOWS:
            return self._consume_posix(request_id, merchant_origin)
        return self._consume_windows(request_id, merchant_origin)

    def _consume_windows(self, request_id, merchant_origin):
        category = "windows_api"
        object_type = None
        try:
            _, con, file, _, _ = _windows()
            if self.closed:
                raise PrivateFileRefused("closed")
            category = "directory_open"
            with _handle(
                file.CreateFile(
                    str(self.directory),
                    con.READ_CONTROL | con.WRITE_OWNER,
                    0,
                    None,
                    con.OPEN_EXISTING,
                    con.FILE_FLAG_BACKUP_SEMANTICS | file.FILE_FLAG_OPEN_REPARSE_POINT,
                    None,
                )
            ) as directory:
                category = "directory_info"
                if (
                    file.GetFileInformationByHandle(directory)[0]
                    & con.FILE_ATTRIBUTE_REPARSE_POINT
                ):
                    raise PrivateFileRefused("directory_reparse")
                category = "windows_acl"
                object_type = "directory"
                _check_acl(directory)
                category = "file_open"
                with _handle(
                    file.CreateFile(
                        str(self.path),
                        con.GENERIC_READ | con.DELETE | con.READ_CONTROL | con.WRITE_OWNER,
                        0,
                        None,
                        con.OPEN_EXISTING,
                        file.FILE_FLAG_OPEN_REPARSE_POINT
                        | con.FILE_FLAG_DELETE_ON_CLOSE,
                        None,
                    )
                ) as handle:
                    category = "file_info"
                    info = file.GetFileInformationByHandle(handle)
                    object_type = "file"
                    if (
                        info[0]
                        & (
                            con.FILE_ATTRIBUTE_REPARSE_POINT
                            | con.FILE_ATTRIBUTE_DIRECTORY
                        )
                    ):
                        raise PrivateFileRefused("filetype")
                    if info[7] != 1:
                        raise PrivateFileRefused("linkcount")
                    if info[5] or info[6] > 16384:
                        raise PrivateFileRefused("size")
                    category = "windows_acl"
                    _check_acl(handle)
                    category = "read"
                    _, raw = file.ReadFile(handle, 16385)
                    category = "json"
                    return _payload(raw, request_id, merchant_origin)
        except PrivateFileRefused as exc:
            exc.object_type = object_type
            raise
        except Exception:
            raise PrivateFileRefused(category) from None

    def __exit__(self, *exc):
        self.closed = True
        self.path.unlink(missing_ok=True)
        self.directory.rmdir()


def _origin(url):
    p = urlsplit(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        raise ValueError("private_file_refused")
    return "https://" + p.netloc
