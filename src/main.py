import importlib
import os
import sys
import traceback


def _project_venv_python() -> str | None:
    project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    candidates = [
        os.path.join(project_dir, ".venv", "bin", "python"),
        os.path.join(project_dir, ".venv", "Scripts", "python.exe"),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return None


def _ensure_runtime_dependencies():
    required_modules = ("aiohttp", "aiosqlite", "pyfuse3", "watchdog")
    missing_module = None

    for module_name in required_modules:
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            missing_module = exc.name or module_name
            break

    if not missing_module:
        return

    venv_python = _project_venv_python()
    if (
        venv_python
        and os.path.abspath(sys.executable) != os.path.abspath(venv_python)
        and os.getenv("CLOUDBRIDGE_REEXEC") != "1"
    ):
        os.environ["CLOUDBRIDGE_REEXEC"] = "1"
        os.execv(venv_python, [venv_python, "-m", "src.main", *sys.argv[1:]])

    raise ModuleNotFoundError(
        f"Missing Python dependency '{missing_module}'. "
        f"Run ./setup.sh to create .venv and install requirements, or start via cloudbridge-start."
    )


_ensure_runtime_dependencies()

try:
    import asyncio
    import logging
    import signal
    import aiohttp
    import pyfuse3
    import pyfuse3.asyncio
    pyfuse3.asyncio.enable()
    from .core.database import StateDB
    from .core.provider.yandex import YandexDiskProvider
    from .core.manager import HybridManager
    from .fs.bridge_fs import CloudBridgeFS
    from .watcher.service import AsyncWatcher

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

    async def main():
        # ... existing main content ...
        TOKEN = os.getenv("YANDEX_TOKEN", "y0__xCzmrXmCBjOv0Ag0o_Vjhdt6Z44hHi-AWWAayZ3qZpaNNl-jw")
        REMOTE_ROOT = os.getenv("YANDEX_PATH", "/")
        DB_PATH = os.getenv("CLOUDBRIDGE_DB_PATH", os.path.expanduser("~/.cache/cloudbridge/state.db"))
        CACHE_DIR = os.getenv("CLOUDBRIDGE_CACHE_DIR", "/tmp/cache")
        MOUNT_POINT = os.getenv("MOUNT_POINT", "/tmp/yandex_mount")
        MIRROR_DIR = os.getenv("LOCAL_PATH", "/tmp/yandex_mirror")
        REMOTE_POLL_INTERVAL = float(os.getenv("CLOUDBRIDGE_REMOTE_POLL_INTERVAL", "60"))

        logger.info("Starting CloudBridge selective sync for path: %s", REMOTE_ROOT)

        db_dir = os.path.dirname(DB_PATH)
        for d in [db_dir, CACHE_DIR, MOUNT_POINT, MIRROR_DIR]:
            try:
                os.makedirs(d, exist_ok=True)
            except FileExistsError:
                # This can happen if the mount point is currently a file or a broken mount
                if d == MOUNT_POINT:
                    logger.warning("Mount point %s already exists and might be a file. Continuing...", d)
                else:
                    raise

        db = StateDB(DB_PATH)
        await db.initialize()
        
        provider = YandexDiskProvider(TOKEN)
        try:
            manager = HybridManager(db, provider, CACHE_DIR, remote_root=REMOTE_ROOT)
            
            # 3. Initial Bootstrap
            logger.info("Initializing remote structure for %s...", REMOTE_ROOT)
            await provider.create_directory(REMOTE_ROOT)
            await manager.sync_directory(REMOTE_ROOT)
            await manager.materialize_remote_placeholders(MIRROR_DIR)
            await manager.bootstrap_local_sync(MIRROR_DIR)
            if os.getenv("PRUNE_REMOTE") == "1":
                await manager.prune_remote_only_files(MIRROR_DIR)

            import subprocess
            # 4. Clean up any hanging mount from previous crashes
            try:
                subprocess.run(['fusermount3', '-u', '-z', MOUNT_POINT], 
                             stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            except Exception:
                pass

            # 5. Component Setup
            fs = CloudBridgeFS(manager)
            watcher = AsyncWatcher(manager, MIRROR_DIR)
            
            # 6. Starting FUSE
            fuse_options = set(pyfuse3.default_options)
            fuse_options.add('fsname=cloudbridge')
            fuse_options.add('allow_other') # Added to allow other users to access
            
            try:
                pyfuse3.init(fs, MOUNT_POINT, fuse_options)
            except RuntimeError as e:
                logger.error("Failed to init FUSE. Try running: sudo umount -l %s", MOUNT_POINT)
                raise e
            
            logger.info("Mounting FUSE on %s", MOUNT_POINT)
            
            async def run_fuse():
                try:
                    await pyfuse3.main()
                except Exception as e:
                    logger.exception("FUSE task failed")
                    
            async def run_watcher():
                try:
                    await watcher.start()
                except Exception as e:
                    logger.exception("Watcher task failed")

            async def run_remote_poll():
                if REMOTE_POLL_INTERVAL <= 0:
                    logger.info("Remote polling is disabled")
                    return
                logger.info("Remote polling started, interval=%ss", REMOTE_POLL_INTERVAL)
                try:
                    while True:
                        await asyncio.sleep(REMOTE_POLL_INTERVAL)
                        try:
                            await manager.materialize_remote_placeholders(MIRROR_DIR)
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            logger.exception("Remote poll failed")
                except asyncio.CancelledError:
                    logger.info("Remote polling stopped")
                    raise

            fuse_task = asyncio.create_task(run_fuse())
            watcher_task = asyncio.create_task(run_watcher())
            remote_poll_task = asyncio.create_task(run_remote_poll())
            
            def shutdown_signal():
                logger.info("Shutdown signal received")
                fuse_task.cancel()
                watcher_task.cancel()
                remote_poll_task.cancel()
                
            for s in (signal.SIGINT, signal.SIGTERM):
                asyncio.get_running_loop().add_signal_handler(s, shutdown_signal)

            try:
                await asyncio.gather(fuse_task, watcher_task, remote_poll_task)
            except asyncio.CancelledError:
                logger.info("Tasks cancelled")
            finally:
                logger.info("Unmounting %s", MOUNT_POINT)
                pyfuse3.unmount()
        except aiohttp.ClientConnectorError as e:
            logger.error(
                "Cannot connect to Yandex.Disk API (%s). Check Kali internet/DNS and restart CloudBridge.",
                e.host,
            )
            raise
        finally:
            await provider.close()

    if __name__ == "__main__":
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            pass
except Exception:
    traceback.print_exc()
