# Technical Report: CloudBridge Hybrid Storage

CloudBridge is a robust hybrid cloud storage daemon for Linux that synchronizes a local directory with Yandex.Disk while minimizing local disk usage through "de-hydration" (stubbing).

## 1. System Architecture

The project is built on a modular asynchronous architecture:

-   **`HybridManager`**: The core "brain" of the system. It handles the state machine (SYNCING, SYNCED, OFFLINE), coordinates uploads/deletions, and performs the initial bootstrap scan.
-   **`StateDB` (SQLite)**: A persistent database that tracks every file. Key metadata stored: path, inode (for FUSE), cloud status, original size, and modification time.
-   **`YandexDiskProvider`**: Implements the communication layer with the Yandex.Disk API (WebDAV-like) for streaming reads, uploads, and recursive directory scans.
-   **`CloudBridgeFS` (FUSE)**: Provides a virtual filesystem mount (`/tmp/yandex_mount`) where files look local but are actually pulled from the cloud on-demand when read.
-   **`AsyncWatcher` (Inotify)**: Real-time monitoring of the local directory (`copypapka`) using `watchdog`.

## 2. Key Synchronization Logic

### De-hydration (Stubbing)
Once a file is successfully uploaded to the cloud, its local version is "de-hydrated" — truncated to 0 bytes.
-   **Preservation**: Before truncation, we capture the file's size and mtime and store them in the `StateDB`.
-   **Visibility**: The FUSE layer uses this DB metadata to report the *original* size to the OS, so files don't appear empty to the user.

### Loop Prevention (Critical Bugfix)
We implemented a two-tier protection system to prevent the system from sync-looping:
1.  **Watcher Awareness**: The watcher checks the file's size and database status. If it's a 0-byte file marked as `OFFLINE`, it's recognized as a "stubbing modification" and ignored.
2.  **Safety Guard**: The `upload_file` method refuses to upload any 0-byte file unless it's a genuinely new empty file. This protects cloud files from being overwritten by local stubs.

### Bootstrap & Pruning
On startup, the system performs:
-   **Selective Sync**: Scans the local folder and uploads only what's new. It correctly identifies existing stubs to avoid redundant uploads.
-   **Pruning**: Automatically deletes files from the cloud that no longer exist in the local folder, ensuring a strict mirror.

## 3. Reliability & Recovery
-   **Hanging Mounts**: The script automatically detects and clears "Transport endpoint is not connected" errors using `fusermount3 -u` on startup.
-   **Fault Tolerance**: The main watcher loop is protected by exception handlers. Corrupted or missing files during sync are logged, but they don't crash the daemon.

## 4. Usage Instructions
1.  Set `YANDEX_TOKEN` and `LOCAL_PATH`.
2.  Run `python3 -m src.main`.
3.  Access cloud files via `/tmp/yandex_mount`.
4.  Monitor real-time sync in the `LOCAL_PATH` directory.
