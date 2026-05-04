---
id: "018"
type: research
title: "MAVLink Bridge Issues — FTP API Mismatch & IMU Orientation"
status: ✅ Complete
created: "2026-05-04"
current_phase: "3 of 3"
---

## Introduction

The VSLAM MAVLink bridge (`mower-vslam-bridge.service`) has two active issues observed after the latest Jetson reboot. First, the Lua script auto-deploy fails at startup because the `_FTPSession` wrapper in `lua_deploy.py` was written against an older callback-based pymavlink MAVFTP API, but pymavlink 2.4.49 on the Jetson uses a synchronous return-value API. Second, RTAB-Map continuously logs "Received IMU doesn't have orientation set! It is ignored," meaning the OAK-D Pro's BNO086 IMU data is being passed without the orientation quaternion, reducing VSLAM to visual-only odometry.

## Objectives

- Determine the correct pymavlink 2.4.49 MAVFTP API surface and how `_FTPSession` must be rewritten
- Understand how `cmd_list` returns directory listings (via `self.list_result` attribute vs return value)
- Determine whether `cmd_get`/`cmd_put` callbacks are still needed or if the synchronous return is sufficient
- Identify how the OAK-D Pro IMU data reaches RTAB-Map and why orientation is missing
- Determine the fix for populating IMU orientation (DepthAI config, RTAB-Map parameter, or both)

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | pymavlink 2.4.49 MAVFTP API | ✅ Complete | Full API surface for cmd_mkdir, cmd_list, cmd_get, cmd_put; MAVFTPReturn semantics; how to read listing results; MAVFTP.__init__ changes | 2026-05-04 |
| 2 | lua_deploy.py rewrite requirements | ✅ Complete | Map current callback-based code to synchronous API; identify all breaking changes; determine if _pump() is still needed; write migration spec | 2026-05-04 |
| 3 | RTAB-Map IMU orientation fix | ✅ Complete | DepthAI IMU pipeline config (rotation vector vs raw); RTAB-Map expected IMU format; rtabmap_slam_node launch params; fix options | 2026-05-04 |

## Phase 1: pymavlink 2.4.49 MAVFTP API

**Status:** ✅ Complete  
**Session:** 2026-05-04

**Source of truth:** `/home/vincent/.local/share/uv/tools/mower-rover/lib/python3.11/site-packages/pymavlink/mavftp.py` (1671 lines, pymavlink 2.4.49 on the Jetson). All citations below are line numbers in that file.

### 1.1 `MAVFTPReturn` (lines 165–226)

```python
class MAVFTPReturn:
    def __init__(self, operation_name, error_code, system_error=0,
                 invalid_error_code=0, invalid_opcode=0, invalid_payload_size=0):
        self.operation_name = operation_name
        self.error_code = error_code           # FtpError IntEnum value
        self.system_error = system_error       # only set when error_code == FailErrno
        ...
    def display_message(self):                 # logs success/failure with proper level
        ...
    @property
    def return_code(self):
        return self.error_code
```

`return_code` is a **property** (alias for `error_code`), not an integer attribute. Use `ret.error_code == FtpError.Success` for idiomatic success checks.

### 1.2 `FtpError` enum (lines 60–82)

```python
class FtpError(IntEnum):
    Success = 0
    Fail = 1
    FailErrno = 2
    InvalidDataSize = 3
    InvalidSession = 4
    NoSessionsAvailable = 5
    EndOfFile = 6
    UnknownCommand = 7
    FileExists = 8           # ← important for idempotent mkdir
    FileProtected = 9
    FileNotFound = 10
    NoErrorCodeInPayload = 64
    NoErrorCodeInNack = 65
    NoFilesystemErrorInPayload = 66
    InvalidErrorCode = 67
    PayloadTooLarge = 68
    InvalidOpcode = 69
    InvalidArguments = 70
    PutAlreadyInProgress = 71
    FailToOpenLocalFile = 72
    RemoteReplyTimeout = 73
```

`Success == 0` is the only success value. **`FileExists`** is the value to special-case for idempotent `mkdir` (we want to swallow it).

### 1.3 `DirectoryEntry` dataclass (lines 88–93)

```python
@dataclass
class DirectoryEntry:
    name: str
    is_dir: bool
    size_b: int
```

`cmd_list` populates `self.list_result: List[DirectoryEntry]` directly. Iterate and read `.name` / `.is_dir` / `.size_b`.

### 1.4 `MAVFTP.__init__` (line 234)

```python
def __init__(self, master, target_system, target_component,
             settings=MAVFTPSettings(
                 [('debug', int, 0),
                  ('pkt_loss_tx', int, 0),
                  ('pkt_loss_rx', int, 0),
                  ('max_backlog', int, 5),
                  ('burst_read_size', int, 80),
                  ('write_size', int, 80),
                  ('write_qsize', int, 5),
                  ('idle_detection_time', float, 3.7),    # ← affects sync timing
                  ('read_retry_time', float, 1.0),
                  ('retry_time', float, 0.5)])):
    ...
    # Reset the flight controller FTP state-machine
    self.__send(FTP_OP(self.seq, self.session, OP_ResetSessions, ...))
    self.process_ftp_reply('ResetSessions')                 # ← blocks during init
```

Constructor signature matches our current code. **Side effect:** the constructor itself sends `ResetSessions` and blocks on `process_ftp_reply` — so a second `MAVFTP(...)` immediately after another may stomp the prior session. Re-using one instance per session is preferable.

`MAVFTPSettings` keys we may want to tune:
- `idle_detection_time` (default 3.7s) — `process_ftp_reply` only returns once the bus has been idle this long. Lowering it speeds up sync ops but risks premature return; **must remain `> read_retry_time` (assert in source)**.
- `read_retry_time` (default 1.0s) — retry interval for stalled reads.
- `burst_read_size` (default 80, capped to 239) — chunk size for cmd_get downloads.

### 1.5 `cmd_mkdir(args)` — fully synchronous (lines 911–921)

```python
def cmd_mkdir(self, args) -> MAVFTPReturn:
    if len(args) != 1:
        return MAVFTPReturn("CreateDirectory", FtpError.InvalidArguments)
    name = args[0]
    enc_name = bytearray(name, 'ascii')
    op = FTP_OP(self.seq, self.session, OP_CreateDirectory, len(enc_name), 0, 0, 0, enc_name)
    self.__send(op)
    return self.process_ftp_reply('CreateDirectory')      # ← BLOCKS until ack/nack/timeout
```

- **Args:** `list[str]` of exactly 1 element (the directory path).
- **Does NOT accept `callback=`.** Passing it raises `TypeError: cmd_mkdir() got an unexpected keyword argument 'callback'`.
- **Synchronous:** `process_ftp_reply` drives `recv_match` and `__idle_task` internally until ack, nack, or timeout.
- **Idempotent check:** `ret.error_code in (FtpError.Success, FtpError.FileExists)`.

### 1.6 `cmd_list(args)` — fully synchronous (lines 383–401)

```python
def cmd_list(self, args) -> MAVFTPReturn:
    self.list_result = []
    self.list_temp_result = []
    if len(args) == 0:
        dname = '/'
    elif len(args) == 1:
        dname = args[0]
    else:
        return MAVFTPReturn("ListDirectory", FtpError.InvalidArguments)
    ...
    self.__send(op)
    return self.process_ftp_reply('ListDirectory')
```

- **Args:** `list[str]` with 0 or 1 element (defaults to `'/'`).
- **No callback kwarg.**
- **Result:** `self._ftp.list_result` is a `List[DirectoryEntry]` populated as a side effect by `__handle_list_reply`.
- The handler issues paged follow-up requests until it receives a `Nack` with payload byte `6` (= `EndOfFile`), at which point it commits `list_temp_result → list_result`.
- **Reading the listing:**
  ```python
  ret = ftp.cmd_list([path])
  if ret.error_code != FtpError.Success:
      raise OSError(...)
  names = [e.name for e in ftp.list_result if not e.is_dir]
  ```

### 1.7 `cmd_get(args, callback=None, progress_callback=None)` — *NOT* fully blocking (lines 481–509)

```python
def cmd_get(self, args, callback=None, progress_callback=None) -> MAVFTPReturn:
    if len(args) == 0 or len(args) > 2:
        return MAVFTPReturn("OpenFileRO", FtpError.InvalidArguments)
    fname = args[0]
    self.filename = args[1] if len(args) > 1 else os.path.basename(fname)
    ...
    self.callback = callback
    ...
    op = FTP_OP(self.seq, self.session, OP_OpenFileRO, len(enc_fname), 0, 0, 0, enc_fname)
    self.__send(op)
    return MAVFTPReturn("OpenFileRO", FtpError.Success)   # ← returns IMMEDIATELY after sending OpenFileRO
```

⚠️ **`cmd_get` does not pump the bus.** It sends `OpenFileRO` and returns "Success" meaning "the open request was queued", not "the download finished". The caller MUST drive a `recv_match` pump loop afterwards.

- **Args:** `[remote_path]` or `[remote_path, local_name]`.
- **Callback signature:** `callback(fh)` where `fh` is a `BytesIO` (`SIO`), **not raw bytes**. Source from `__check_read_finished` (lines 591–615):
  ```python
  if self.callback is not None:
      self.fh.seek(0)
      self.callback(self.fh)        # ← passes the file handle, caller .read() to get bytes
      self.callback = None
  ```
- **Without callback:** writes the file to `self.temp_filename` (`/tmp/temp_mavftp_file` by default) then moves it to `self.filename`. Side-effect-heavy.
- **There is NO public method that returns bytes synchronously**, but `MAVFTP.read(path, size, offset=0) -> Optional[bytes]` (line 436) implements its own pump loop and returns bytes. It still writes a local file as side effect — `self.filename` must be set to a writable path first.

**Pump pattern (from `read()` at lines 436–476, the canonical form):**

```python
timeout = time.time() + 5
while not self.done and time.time() < timeout:
    m = self.master.recv_match(type="FILE_TRANSFER_PROTOCOL", blocking=True, timeout=1.0)
    if m is None:
        self.__idle_task()
        continue
    timeout = time.time() + 5
    self.__mavlink_packet(m)
    self.__idle_task()
    time.sleep(0.0001)
```

Both `__idle_task` and `__mavlink_packet` are name-mangled (double-underscore prefix → `_MAVFTP__idle_task` / `_MAVFTP__mavlink_packet`). External callers must use the mangled names, OR call `process_ftp_reply('OpenFileRO')` **after** `cmd_get` to drive the pump using the public method (`process_ftp_reply` recv_matches on `FILE_TRANSFER_PROTOCOL` and calls `__idle_task` internally — see lines 1131–1155).

### 1.8 `cmd_put(args, fh=None, callback=None, progress_callback=None)` — *NOT* fully blocking (lines 731–784)

```python
def cmd_put(self, args, fh=None, callback=None, progress_callback=None) -> MAVFTPReturn:
    if len(args) == 0 or len(args) > 2:
        return MAVFTPReturn("CreateFile", FtpError.InvalidArguments)
    if self.write_list is not None:
        return MAVFTPReturn("CreateFile", FtpError.PutAlreadyInProgress)
    fname = args[0]
    self.fh = fh
    if self.fh is None:
        self.fh = open(fname, 'rb')           # ← opens local file from disk if fh not given
    if len(args) > 1:
        self.filename = args[1]               # ← remote name
    else:
        self.filename = os.path.basename(fname)
    ...
    self.fh.seek(0,2)
    file_size = self.fh.tell()
    self.fh.seek(0)
    ...
    self.put_callback = callback
    op = FTP_OP(self.seq, self.session, OP_CreateFile, ...)
    self.__send(op)
    return MAVFTPReturn("CreateFile", FtpError.Success)   # ← returns IMMEDIATELY after CreateFile send
```

- **Args:** `[anything, remote_path]` when supplying an `fh`. (When `fh is None`, args[0] is the local path to open. With `fh` supplied, args[0] is only used for log messages and as a fallback name; **always pass `args=[remote_path, remote_path]` or `[<dummy>, remote_path]` plus `fh=BytesIO(data)` to upload from memory.**)
- **`fh` parameter:** any seekable, readable file-like — **`io.BytesIO(data)` works perfectly** for in-memory upload (uses `seek(0,2)`, `tell()`, `seek(0)`, `read(block_size)`).
- **Callback signature:** `callback(file_size_bytes: int)` — called with the total flen on completion (`__put_finished` line 784–797). Optional.
- **NOT pumped internally.** Caller must drive a pump loop after `cmd_put`, same as `cmd_get`. The completion is signaled when `__send_more_writes` finds `len(self.write_list) == 0` and calls `__put_finished` then `__terminate_session`. There is no public "done" flag; callers either supply a callback that flips a sentinel or use `process_ftp_reply('CreateFile')` to drive the pump (it returns when the bus goes idle for `idle_detection_time`).

### 1.9 Public `MAVFTP.read(path, size, offset=0) -> Optional[bytes]` (lines 436–476)

```python
def read(self, path: str, size: int, offset: int = 0) -> Optional[bytes]:
    self.get_result = None
    self.requested_offset = offset
    self.requested_size = size
    self.filename = path           # ← used for the local file write side-effect
    self.done = False
    ...
    op = FTP_OP(..., OP_OpenFileRO, ...)
    self.__send(op)
    timeout = time.time() + 5
    while not self.done and time.time() < timeout:
        m = self.master.recv_match(type="FILE_TRANSFER_PROTOCOL", blocking=True, timeout=1.0)
        if m is None:
            self.__idle_task()
            continue
        timeout = time.time() + 5
        self.__mavlink_packet(m)
        self.__idle_task()
        time.sleep(0.0001)
    if len(self.read_gaps) == 0:
        return self.get_result
    return None
```

- **Already pumps internally.** Returns bytes (or `None` on gaps).
- **Side effect:** writes a copy to `self.filename` on the local filesystem. For the lua_deploy use case, set `ftp.filename = '/tmp/mavftp_lua_dl'` before the call (or just tolerate the temp write).
- **`size` is overwritten** by `__handle_open_ro_reply` from the OpenFileRO ack's reported file size, so passing a generous upper bound (e.g. `0x40000` = 256 KiB — well above any Lua script size) is fine.

### 1.10 `process_ftp_reply(operation_name, timeout=5)` (lines 1131–1155)

The canonical public synchronous pump used by `cmd_list`, `cmd_mkdir`, `cmd_rm`, `cmd_rmdir`, `cmd_rename`, `cmd_crc`. Returns when `__idle_task()` returns True (bus idle for `idle_detection_time`) or `timeout` elapses. **`timeout` must be `> idle_detection_time` (3.7s default)** — there is an `assert` for this.

### Key Discoveries

- The pymavlink 2.4.49 MAVFTP API **rejects all `callback=` kwargs** on `cmd_mkdir` and `cmd_list` — the entire async-callback pattern in our `_FTPSession` is invalid against this version.
- `MAVFTP` has no public `idle_task()` method — it's `_MAVFTP__idle_task` (name-mangled). Our `_pump()` call to `self._ftp.idle_task()` raises `AttributeError`.
- `cmd_list`, `cmd_mkdir`, `cmd_rm`, `cmd_rmdir`, `cmd_rename`, `cmd_crc` are **fully synchronous** (they call `process_ftp_reply()` internally).
- `cmd_get` and `cmd_put` are **half-async**: they only send the initial open/create op and return. The caller must pump.
- For downloads, the cleanest path is `MAVFTP.read(path, size_hint)` which has its own pump loop and returns `bytes` directly.
- For uploads, `cmd_put(args=[remote_path, remote_path], fh=BytesIO(data))` works for in-memory data; pumping must be done by the caller, e.g. via `process_ftp_reply('CreateFile', timeout=30)` after the `cmd_put` call. The default `idle_detection_time` of 3.7s means `process_ftp_reply` adds at least ~3.7s of dead time at the end of every operation — acceptable for a once-per-startup deploy.
- `cmd_get` callback receives a `BytesIO` (`fh`), not raw bytes. Source: `__check_read_finished` line 605: `self.callback(self.fh)`.
- `MAVFTPReturn.error_code == FtpError.Success` is the success check. `FileExists` (8) is the value to swallow for idempotent `mkdir`.
- The MAVFTP constructor itself blocks on `process_ftp_reply('ResetSessions')` — instantiating MAVFTP twice in quick succession will both reset the FC's FTP state machine.

### Files Analyzed

| File | Relevance |
|------|-----------|
| `/home/vincent/.local/share/uv/tools/mower-rover/lib/python3.11/site-packages/pymavlink/mavftp.py` | Authoritative pymavlink 2.4.49 source on the Jetson (1671 lines) |
| `src/mower_rover/vslam/lua_deploy.py` | Current callback-based implementation — needs full rewrite of `_FTPSession` |

### External Sources

- pymavlink GitHub (cross-reference, not authoritative for this version): https://github.com/ArduPilot/pymavlink

### Gaps

None for the API documentation itself. Phase 2 will turn these findings into a concrete migration spec.

### Assumptions

- The Jetson's pymavlink 2.4.49 will not be downgraded; the bridge must adapt to this API.
- `idle_detection_time = 3.7s` adds ~3.7s of latency to every synchronous FTP op. Acceptable for once-per-startup Lua deploy (the bridge service tolerates the delay).

## Phase 2: lua_deploy.py Rewrite Requirements

**Status:** ✅ Complete  
**Session:** 2026-05-04

### Current `_FTPSession` Class Anatomy

**File:** `src/mower_rover/vslam/lua_deploy.py` (lines 47–148)

#### State Flags (all obsolete under new API)

| Flag | Type | Purpose | Lines |
|------|------|---------|-------|
| `_result` | `bytes \| None` | Holds downloaded file content from `_read_cb` | 57 |
| `_error` | `str \| None` | Error string set by any `_*_cb` callback | 58 |
| `_listing` | `list[str] \| None` | Accumulated directory listing from `_list_cb` | 59 |
| `_done` | `bool` | Completion signal checked by `_pump()` | 60 |

#### Current Methods and Their API Calls

| Method | Signature | Lines | pymavlink call | Broken reason |
|--------|-----------|-------|----------------|---------------|
| `__init__` | `(conn)` | 50–60 | `mavftp.MAVFTP(conn, target_system=..., target_component=...)` | Constructor itself is fine |
| `list_directory` | `(path) -> list[str]` | 64–72 | `self._ftp.cmd_list([path], callback=self._list_cb)` | `callback=` kwarg raises TypeError |
| `read_file` | `(path) -> bytes` | 74–82 | `self._ftp.cmd_get([path], callback=self._read_cb)` | `callback=` kwarg raises TypeError |
| `write_file` | `(path, data) -> None` | 84–91 | `self._ftp.cmd_put([path], data, callback=self._write_cb)` | Wrong positional args + `callback=` raises TypeError |
| `mkdir` | `(path) -> None` | 93–100 | `self._ftp.cmd_mkdir([path], callback=self._generic_cb)` | `callback=` kwarg raises TypeError |
| `_list_cb` / `_read_cb` / `_write_cb` / `_generic_cb` | various | 104–133 | — | Dead code under new API |
| `_pump` | `(timeout_s=10.0)` | 135–142 | `self._ftp.idle_task()` | `idle_task` is name-mangled (`_MAVFTP__idle_task`); direct call fails with AttributeError |

### Sole Call Site

**File:** `src/mower_rover/vslam/bridge.py` line 207: `check_and_deploy_lua(conn)`. `_FTPSession` is private and only instantiated inside that function. **No external code references `_FTPSession` directly.** The function's contract (takes a `mavutil.mavlink_connection`, returns `None`, never raises) does NOT change.

### FTP Operations Actually Used

Only four FTP operations. **No `rm`, `rmdir`, or `rename`:**

1. **mkdir** — create `/APM/scripts` idempotently
2. **list** — list `/APM/scripts` to check if Lua file exists
3. **get** (read) — download remote Lua file to compare versions
4. **put** (write) — upload bundled Lua script

---

### Migration Spec: Current → New API

#### Operation 1: `mkdir` (idempotent)

```python
def mkdir(self, path: str) -> None:
    from pymavlink.mavftp import FtpError
    ret = self._ftp.cmd_mkdir([path])
    if ret.error_code not in (FtpError.Success, FtpError.FileExists):
        raise OSError(f"mkdir {path}: FTP error {ret.error_code}")
```

Already synchronous; idempotent via `FileExists` swallow.

#### Operation 2: `list_directory`

```python
def list_directory(self, path: str) -> list[str]:
    from pymavlink.mavftp import FtpError
    ret = self._ftp.cmd_list([path])
    if ret.error_code != FtpError.Success:
        raise OSError(f"list {path}: FTP error {ret.error_code}")
    return [entry.name for entry in self._ftp.list_result]
```

Results populated as side-effect into `self._ftp.list_result: List[DirectoryEntry]`. Each entry has `.name` / `.is_dir` / `.size_b`.

#### Operation 3: `read_file` (get/download)

```python
def read_file(self, path: str) -> bytes:
    import os
    self._ftp.filename = os.path.join(self._tmpdir, "mavftp_dl")  # redirect side-effect write
    data = self._ftp.read(path, 0x40000)
    if data is None:
        raise OSError(f"read {path}: FTP transfer failed")
    return data
```

`MAVFTP.read()` has its own internal pump loop, returns `Optional[bytes]`. **Side effect:** writes copy to `self._ftp.filename` — must redirect to a controlled tempdir. `0x40000` is a safe size hint (overwritten by ack from OpenFileRO).

#### Operation 4: `write_file` (put/upload)

```python
def write_file(self, path: str, data: bytes) -> None:
    from io import BytesIO
    from pymavlink.mavftp import FtpError
    self._ftp.cmd_put([path, path], fh=BytesIO(data))
    ret = self._ftp.process_ftp_reply('CreateFile', timeout=30)
    if ret.error_code != FtpError.Success:
        raise OSError(f"write {path}: FTP error {ret.error_code}")
```

**Half-async** — `cmd_put` returns after CreateFile send; we drive the rest with `process_ftp_reply('CreateFile', timeout=30)`. Args `[path, path]` because the second slot is the unused-when-fh-supplied "local path" placeholder.

---

### Deletions Checklist

| Item | Lines | Reason |
|------|-------|--------|
| `self._result`, `self._error`, `self._listing`, `self._done` fields | 57–60 | State flags obsolete under sync API |
| `_list_cb`, `_read_cb`, `_write_cb`, `_generic_cb` methods | 104–133 | Callback API removed |
| `_pump` method | 135–142 | Sync API drives its own message loops |
| Per-method state resets | 65–70, 75–78, 85–87, 94–96 | State flags deleted |

### Additions Checklist

| Item | Reason |
|------|--------|
| `from pymavlink.mavftp import FtpError` | Error code checks |
| `from io import BytesIO` | Wrap upload bytes for `cmd_put(fh=...)` |
| `import tempfile`, `self._tmpdir = tempfile.mkdtemp()` in `__init__` | Capture temp dir for `MAVFTP.read()` side-effect file |
| Set `self._ftp.filename` before each `read()` call | Redirect side-effect write |
| `MAVFTPReturn.error_code` checks in every method | Replace string-based `_error` checks |
| `process_ftp_reply('CreateFile', timeout=30)` in `write_file` | Drive half-async upload to completion |

### Caller-Side & Test Impact

- **Public API of `_FTPSession` is unchanged** — same method signatures, same `OSError` raising semantics. **No caller changes needed** in `bridge.py`.
- **All 12 tests in `tests/test_vslam_lua_deploy.py` pass unchanged.** They mock `_FTPSession` at the class level via `@patch("mower_rover.vslam.lua_deploy._FTPSession")` and configure return values on the public methods. The internal callback/pump rewrite is invisible to the test boundary.

### Open Questions for Planner/Coder

1. **Tempdir lifecycle:** Recommend leaving the tempdir uncleaned (single small file, process-scoped session, bridge restarts rarely). Alternative: `shutil.rmtree` in a `__del__` or context-manager pattern.
2. **`cmd_put` args dual-path:** Phase 1 confirmed `[remote_path, remote_path]` works. Keep this form to match pymavlink's internal expectations rather than substituting a placeholder string.
3. **`MAVFTP.read()` failure semantics:** Documented as returning `None` on failure. If it actually raises (untested edge case), wrap in try/except and re-raise as `OSError`.
4. **idle_detection_time latency:** Worst-case 4 ops × ~3.7s = ~15s startup delay. Acceptable for once-per-boot. Tune `self._ftp.idle_detection_time` (must remain > `read_retry_time`, default 1.0s) if needed.

**Key Discoveries:**
- All 12 existing tests pass unchanged — they mock at the public method level
- Only ONE call site (`bridge.py:207`) and it needs no change
- Public method signatures (`mkdir`, `list_directory`, `read_file`, `write_file`) all preserved
- `_pump()` and all 4 `_*_cb` methods are pure dead code to delete
- `write_file` is the only half-async migration (needs `process_ftp_reply` after `cmd_put`)
- `read_file` needs a tempdir for `MAVFTP.read()`'s local-file side effect
- No `rm`/`rmdir`/`rename` operations used — only 4 FTP ops to migrate

| File | Relevance |
|------|-----------|
| `src/mower_rover/vslam/lua_deploy.py` | The file being migrated; `_FTPSession` class internals get rewritten |
| `tests/test_vslam_lua_deploy.py` | All 12 tests will pass unchanged due to class-boundary mocking |
| `src/mower_rover/vslam/bridge.py` (line 207) | Sole call site of `check_and_deploy_lua`; no caller-side changes |

**Gaps:** None.  
**Assumptions:** `MAVFTP.read()` returns `None` on failure (per Phase 1 type hint); `process_ftp_reply` returns a `MAVFTPReturn` (per Phase 1 §1.10).

## Phase 3: RTAB-Map IMU Orientation Fix

**Status:** ✅ Complete  
**Session:** 2026-05-04

### Root Cause: Failure Mode (A) — No Rotation-Vector Sensor Enabled

The DepthAI pipeline in `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` (lines 247–252) enables ONLY the two raw inertial sensors:

```cpp
auto imu = result.pipeline->create<dai::node::IMU>();
imu->enableIMUSensor(dai::IMUSensor::ACCELEROMETER_RAW, cfg.imu_rate_hz);
imu->enableIMUSensor(dai::IMUSensor::GYROSCOPE_RAW, cfg.imu_rate_hz);
```

No rotation-vector sensor (`ROTATION_VECTOR`, `GAME_ROTATION_VECTOR`, etc.) is enabled, so the BNO086 firmware never produces a fused quaternion. The `rotationVector` field of every `dai::IMUPacket` stays at its default `{i=0, j=0, k=0, real=0}`.

### How the Warning is Triggered

1. **IMU drain loop** (lines 663–675): reads `p.acceleroMeter` and `p.gyroscope` only — never touches `p.rotationVector`.
2. **IMU struct construction** (lines 686–691): uses RTAB-Map's **2-argument** `rtabmap::IMU` constructor (gyro + accel only — see `IMU.h` line 39). Leaves `orientation_` as `cv::Vec4d(0,0,0,0)`.
3. **RTAB-Map check** (`Odometry.cpp` line 310): `if(!(orientation()[0]==0 && [1]==0 && [2]==0))` — fails (all zeros), falls through to line 336: `UWARN("Received IMU doesn't have orientation set! It is ignored.");`

### Consequence

Without orientation, RTAB-Map **completely discards the IMU packet**. No initial pose alignment, no motion-model prediction, no velocity estimation. The system is effectively visual-only odometry — fragile on a vibrating mower platform when visual tracking glitches.

### Recommended Fix: Enable `GAME_ROTATION_VECTOR`

| Sensor | Mag required | Yaw drift | Suitability |
|--------|--------------|-----------|-------------|
| `ROTATION_VECTOR` (9-DoF) | Yes | None | ❌ Magnetometer is unreliable on this platform (steel deck, engine, motors). Project mandates `COMPASS_USE=0`. |
| `GAME_ROTATION_VECTOR` (6-DoF) | No | Slow gyro drift | ✅ **Best.** RTAB-Map only uses the IMU quaternion for gravity (roll/pitch) — yaw comes from visual features. Per `Odometry.cpp` line 313 comment: "orientation includes roll and pitch but not yaw in local transform." |
| `GEOMAGNETIC_ROTATION_VECTOR` | Yes | N/A | ❌ Same mag problem |
| `ARVR_STABILIZED_GAME_ROTATION_VECTOR` | No | Slower drift | ⚠️ Higher latency; no clear odometry benefit |

`GAME_ROTATION_VECTOR` is correct because (a) RTAB-Map only needs gravity from the IMU, (b) the magnetometer environment is hostile, (c) the BNO086's on-chip 6-DoF fusion already gives smooth, low-latency gravity tracking.

### Code Changes Required

**File:** `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp`

**Change 1 — Enable the sensor (after line 251):**
```cpp
imu->enableIMUSensor(dai::IMUSensor::GAME_ROTATION_VECTOR, cfg.imu_rate_hz);
```

**Change 2 — Read the quaternion in the drain loop (around lines 663–675):**
```cpp
cv::Vec4d orientation(0, 0, 0, 0);  // qx, qy, qz, qw
// Inside the per-packet loop, after gyro extraction:
if (p.rotationVector.real != 0 || p.rotationVector.i != 0 ||
    p.rotationVector.j != 0 || p.rotationVector.k != 0) {
    orientation[0] = p.rotationVector.i;
    orientation[1] = p.rotationVector.j;
    orientation[2] = p.rotationVector.k;
    orientation[3] = p.rotationVector.real;
}
```

**Change 3 — Use the orientation-aware IMU constructor (replaces lines 686–691):**
```cpp
sensor_data.setIMU(rtabmap::IMU(
    orientation, cv::Mat::eye(3, 3, CV_64FC1),
    gyro,        cv::Mat::eye(3, 3, CV_64FC1),
    accel,       cv::Mat::eye(3, 3, CV_64FC1),
    imu_local_transform));
```
(The 7-argument constructor is `rtabmap::IMU.h` line 23.)

### Python-Side Config Impact

**None required.** The C++ node's `cfg.imu_rate_hz` already comes from the existing `VslamConfig` dataclass and applies to all enabled sensors. Hardcoding `GAME_ROTATION_VECTOR` matches the project's "avoid abstractions for one-time operations" principle. Adding a configurable `imu_rotation_sensor` field is a future enhancement, not part of this fix.

### Test Impact

| Test | Impact |
|------|--------|
| `tests/test_vslam_config.py` | No change — Python schema unchanged |
| `tests/test_probe_vslam.py` | No change — unrelated path |
| `tests/test_vslam_health.py` | No change — IPC, not IMU data |
| `tests/test_vslam_ipc.py` | No change — wire format, not IMU |
| `tests/test_vslam_frames.py` | Review — if it mocks IMU payloads, may need to expect a non-zero quaternion |

**New test (field-required):** A `@pytest.mark.field` integration test that scans the RTAB-Map log after bridge startup and asserts the "orientation set" warning is absent. Cannot be validated in SITL.

### `IMUPacket.rotationVector` Field Notes

The `dai::IMUPacket` struct ALWAYS contains a `rotationVector` member (type `IMUReportRotationVectorWAcc`), regardless of which sensors are enabled. Both `ROTATION_VECTOR` and `GAME_ROTATION_VECTOR` populate the same field — they share the `IMUReportRotationVectorWAcc` output type. When neither sensor is enabled (current state), the field stays at zeros.

### Alternatives Ranked

1. **✅ Hardcode `GAME_ROTATION_VECTOR`** — simplest, correct for this hardware, 3 code changes in one file
2. Make sensor configurable via YAML — more work, deferrable
3. Compute orientation from accel-only gravity tilt — inferior (noisy, no gyro smoothing, reinvents the BNO086's job)
4. `ARVR_STABILIZED_GAME_ROTATION_VECTOR` — higher latency, no benefit for odometry

**Key Discoveries:**
- Pipeline enables ONLY raw accel + gyro; no rotation vector sensor (line 248–251)
- C++ uses RTAB-Map's 2-arg IMU constructor; orientation stays at zero (line 688)
- RTAB-Map's check at `Odometry.cpp:310` discards entire packet when `qx=qy=qz=0`
- RTAB-Map only uses the quaternion for gravity (roll/pitch); yaw comes from visual features
- `GAME_ROTATION_VECTOR` (6-DoF, no mag) is correct given `COMPASS_USE=0` mandate
- Fix is 3 changes in one C++ file; no Python or YAML changes needed
- No existing Python tests need updating

| File | Relevance |
|------|-----------|
| `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` | Primary fix: pipeline (L247–252), drain loop (L663–675), IMU struct (L686–691) |
| `/opt/rtabmap-src/corelib/src/Odometry.cpp` (Jetson) | Warning origin: L310 check, L336 log |
| `/usr/local/include/rtabmap-0.21/rtabmap/core/IMU.h` (Jetson) | 7-arg constructor (L23) vs 2-arg constructor (L39) |
| `/usr/local/include/depthai/properties/IMUProperties.hpp` (Jetson) | `IMUSensor::GAME_ROTATION_VECTOR = 0x08` |
| `/usr/local/include/depthai/pipeline/datatype/IMUData.hpp` (Jetson) | `IMUPacket.rotationVector` field (always present) |

**Gaps:** None.  
**Assumptions:**
- Both `ROTATION_VECTOR` and `GAME_ROTATION_VECTOR` populate the same `IMUPacket.rotationVector` field (confirmed by struct serialization).
- BNO086 supports `GAME_ROTATION_VECTOR` at the configured rate (datasheet allows up to 400 Hz; we use much less).

## Overview

This research diagnosed two unrelated faults in the VSLAM MAVLink bridge surfaced after the latest Jetson reboot, and produced concrete migration specs for both.

### Issue 1: Lua Auto-Deploy FTP Failure (Phases 1–2)

The `_FTPSession` wrapper in `src/mower_rover/vslam/lua_deploy.py` was written against an older callback-based pymavlink MAVFTP API. The Jetson's installed pymavlink 2.4.49 uses a synchronous return-value API: `cmd_mkdir` and `cmd_list` block internally and reject `callback=` kwargs; `cmd_get`/`cmd_put` are half-async (caller pumps via `process_ftp_reply`). The wrapper's `_pump()` also calls a non-existent `idle_task()` (the real attribute is name-mangled `_MAVFTP__idle_task`). The fix is a clean internal rewrite of `_FTPSession`'s 4 methods using the documented sync patterns; the public method signatures, the sole caller (`bridge.py:207`), and all 12 existing tests are unaffected.

### Issue 2: RTAB-Map Missing IMU Orientation (Phase 3)

The DepthAI pipeline in `rtabmap_slam_node.cpp` enables only `ACCELEROMETER_RAW` + `GYROSCOPE_RAW`; no rotation-vector sensor is requested from the BNO086, so `IMUPacket.rotationVector` stays at zeros. The C++ wrapper then constructs `rtabmap::IMU` using the 2-arg gyro+accel constructor, leaving the orientation quaternion at zero. RTAB-Map's `Odometry.cpp:310` treats `qx=qy=qz=0` as "unset" and discards the entire packet. The system runs as visual-only odometry. Fix: enable `GAME_ROTATION_VECTOR` (6-DoF, no magnetometer — matches the project's `COMPASS_USE=0` mandate), read the quaternion from the packet, and use the 7-arg orientation-aware `rtabmap::IMU` constructor. Three changes in one C++ file; no Python or YAML changes; no existing tests need updating.

### Cross-Cutting Themes

- **Both issues hide behind silent or noisy-but-ignored failures.** The FTP wrapper raises `OSError` only when called; the IMU warning is logged but RTAB-Map continues running degraded. Field validation should add health-monitor checks for both: (a) Lua script SHA matches expected after deploy, (b) RTAB-Map log free of "orientation set" warnings.
- **The fixes are surgical and respect the project's anti-over-engineering principle.** No new abstractions, no configuration knobs added “just in case,” no caller-side or test changes.
- **Existing test suites are well-designed.** The `_FTPSession` mock-at-class-boundary pattern and the absence of Python-side IMU config both meant the migrations have minimal blast radius.

### Key Findings Summary

1. pymavlink 2.4.49 MAVFTP API is fully synchronous for `cmd_mkdir`/`cmd_list`, half-async for `cmd_get`/`cmd_put`; all `callback=` kwargs were removed.
2. `MAVFTP.read(path, size_hint)` is the cleanest download pattern (returns bytes, has internal pump loop, but writes a side-effect copy to `self.filename`).
3. `cmd_put(args=[remote, remote], fh=BytesIO(data))` + `process_ftp_reply('CreateFile', timeout=30)` is the upload pattern.
4. `_FTPSession` rewrite is internal-only; public API and tests unchanged.
5. The OAK-D Pro IMU pipeline has never enabled a rotation-vector sensor — root cause of the RTAB-Map warning.
6. `GAME_ROTATION_VECTOR` is the correct sensor for this platform (no magnetometer dependency).
7. RTAB-Map only uses the IMU quaternion for gravity (roll/pitch); visual features handle yaw.

### Actionable Conclusions

- **Hand off to `pch-planner`** for two parallel implementation plans:
  - Plan A: Rewrite `_FTPSession` internals per Phase 2 spec (Python; ~50 LOC delta)
  - Plan B: Add 3 changes to `rtabmap_slam_node.cpp` per Phase 3 spec (C++; ~10 LOC delta)
- **Consider a follow-up plan** to add health-monitor checks for both failure modes (Lua SHA verify after deploy; scan RTAB-Map log for the orientation warning).

### Open Questions

- Tempdir lifecycle for `MAVFTP.read()`'s side-effect file (recommend: leave it, single small file, process-scoped) — confirm during planning.
- Whether to add `imu_rotation_sensor` as a YAML config field (recommend: no, hardcode for now) — confirm during planning.

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-05-04 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete |
| Path | /docs/research/018-mavlink-ftp-imu-fixes.md |
