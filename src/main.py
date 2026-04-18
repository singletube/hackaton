import traceback
try:
    import asyncio
    import logging
    import os
    import signal
    import aiohttp
    import pyfuse3
    import pyfuse3.asyncio
    pyfuse3.asyncio.enable()
    import sys
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
        DB_PATH = "/tmp/state.db"
        CACHE_DIR = "/tmp/cache"
        MOUNT_POINT = os.getenv("MOUNT_POINT", "/tmp/yandex_mount")
        MIRROR_DIR = os.getenv("LOCAL_PATH", "/tmp/yandex_mirror")

        logger.info("Starting CloudBridge selective sync for path: %s", REMOTE_ROOT)

        for d in [CACHE_DIR, MOUNT_POINT, MIRROR_DIR]:
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
            if os.getenv("BOOTSTRAP_LOCAL") == "1":
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

            fuse_task = asyncio.create_task(run_fuse())
            watcher_task = asyncio.create_task(run_watcher())
            
            def shutdown_signal():
                logger.info("Shutdown signal received")
                fuse_task.cancel()
                watcher_task.cancel()
                
            for s in (signal.SIGINT, signal.SIGTERM):
                asyncio.get_running_loop().add_signal_handler(s, shutdown_signal)

            try:
                await asyncio.gather(fuse_task, watcher_task)
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
