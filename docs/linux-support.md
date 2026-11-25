# Linux (POSIX) support

Secure Entry 0.5.21 runs its private Link output inbox on Linux and macOS as well as Windows. Windows behavior is unchanged.

## Private inbox on POSIX

The Windows inbox relies on a protected DACL and a no-sharing, delete-on-close handle. The POSIX inbox keeps the same refusals with POSIX primitives:

| Step | Windows | POSIX (this change) |
| --- | --- | --- |
| Create the inbox directory | Protected DACL, user and SYSTEM only, before creation | `mkdir` mode `0700` (the umask can only remove bits) |
| Link child process | Inherits the protected DACL | Started with `umask 077`, so its output is owner-only |
| Directory check | Not a reparse point; DACL and owner checked | Opened with `O_NOFOLLOW` and `O_DIRECTORY`; a symlink fails; owner must be the effective uid; no group or other bits |
| File open | No-follow, no-share, delete-on-close handle | Opened `O_NOFOLLOW` relative to the verified directory descriptor, `O_NONBLOCK` so a FIFO cannot hang |
| File checks | Regular file, one hard link, size limit, DACL and owner | Regular file, `st_nlink == 1`, size at most 16384 bytes, owner is the effective uid, no group or other bits |
| Read and delete | Read through the handle, delete on close | Read through the same descriptor, then unlink by name only if the name still refers to the same inode |

Every refusal is a fixed category. Nothing from the file is logged or returned.

Named ACL entries cannot widen access past the group bits on POSIX, so a clear group and other mask also rules out named users and groups.

## Known limits

- A same-user process can still read the file while Link has it. This is the same boundary as on Windows, where the owner can read its own files.
- There is a small window between the check that the name still points at our inode and the unlink. Only the same user can exploit it, and that user could already read the file.
- Owner changes need root, so the tests simulate a foreign owner by changing the uid the check compares against. The stat results are real.
- Abrupt process termination can leave a file in the inbox. No restart sweeper is claimed, as on Windows.

## Running the tests on Linux

```bash
PYTHONPATH=/absolute/hermes-source:/absolute/hermes-secure-entry \
  /absolute/scratch/secure-entry-env/bin/python -m unittest discover -s tests -v
```

- Install Chrome for Playwright with `python -m playwright install --with-deps chrome`. The browser tests use `channel="chrome"`.
- Set `TMPDIR` to a short path. Chrome's singleton socket lives under `TMPDIR`, and the full path must fit the 108-byte Unix socket limit. A path such as `/tmp/se` works; a long home-directory path can fail with `Socket path too long`.
- Windows-only tests (`tests/test_payment_file_owner.py`, and the DACL edit test in `tests/test_payment_file.py`) skip on Linux with a platform reason. Their POSIX equivalents run in `tests/test_payment_file_posix.py`.

The `linux` job in `.github/workflows/tests.yml` runs this on `ubuntu-latest` with the same pinned Hermes revision as the Windows job.
