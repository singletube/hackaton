import traceback
try:
    import asyncio
    import logging
    import os
    import signal
    from contextlib import suppress
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
    from .config import ensure_runtime_directories, load_runtime_config, remove_pid, write_pid, write_status

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

    async def main():
        config = load_runtime_config()
        if not config.token:
            raise RuntimeError("YANDEX_TOKEN is required")

        logger.info("Starting CloudBridge selective sync for path: %s", config.remote_root)
        write_pid(config.pid_path, os.getpid())
        write_status(config.status_path, "starting", remote_root=config.remote_root)

        for d in [config.cache_dir, config.mount_point, config.mirror_dir]:
            try:
                os.makedirs(d, exist_ok=True)
            except FileExistsError:
                # This can happen if the mount point is currently a file or a broken mount
                if d == config.mount_point:
                    logger.warning("Mount point %s already exists and might be a file. Continuing...", d)
                else:
                    raise

        ensure_runtime_directories(config)
        db = StateDB(config.db_path)
        await db.initialize()
        
        provider = YandexDiskProvider(config.token)
        try:
            manager = HybridManager(db, provider, config.cache_dir, remote_root=config.remote_root)
            
            # 3. Initial Bootstrap
            logger.info("Initializing remote structure for %s...", config.remote_root)
            write_status(config.status_path, "syncing", message="Initial directory sync", remote_root=config.remote_root)
            await provider.create_directory(config.remote_root)
            await manager.sync_directory(config.remote_root)
            if os.getenv("BOOTSTRAP_LOCAL") == "1":
                await manager.bootstrap_local_sync(config.mirror_dir)
            if os.getenv("PRUNE_REMOTE") == "1":
                await manager.prune_remote_only_files(config.mirror_dir)

            import subprocess
            # 4. Clean up any hanging mount from previous crashes
            try:
                subprocess.run(['fusermount3', '-u', '-z', config.mount_point], 
                             stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            except Exception:
                pass

            # 5. Component Setup
            fs = CloudBridgeFS(manager)
            watcher = AsyncWatcher(manager, config.mirror_dir)
            
            # 6. Starting FUSE
            fuse_options = set(pyfuse3.default_options)
            fuse_options.add('fsname=cloudbridge')
            fuse_options.add('allow_other') # Added to allow other users to access
            
            try:
                pyfuse3.init(fs, config.mount_point, fuse_options)
            except RuntimeError as e:
                logger.error("Failed to init FUSE. Try running: sudo umount -l %s", config.mount_point)
                write_status(config.status_path, "error", message=f"FUSE init failed: {e}")
                raise e
            
            logger.info("Mounting FUSE on %s", config.mount_point)
            write_status(config.status_path, "running", remote_root=config.remote_root, mount_point=config.mount_point)

            async def publish_heartbeat():
                while True:
                    await asyncio.sleep(10)
                    write_status(
                        config.status_path,
                        "running",
                        remote_root=config.remote_root,
                        mount_point=config.mount_point,
                        pid=os.getpid(),
                    )
            
            async def run_fuse():
                try:
                    await pyfuse3.main()
                except Exception:
                    write_status(config.status_path, "error", message="FUSE task failed")
                    logger.exception("FUSE task failed")
                    
            async def run_watcher():
                try:
                    await watcher.start()
                except Exception:
                    write_status(config.status_path, "error", message="Watcher task failed")
                    logger.exception("Watcher task failed")

            fuse_task = asyncio.create_task(run_fuse())
            watcher_task = asyncio.create_task(run_watcher())
            heartbeat_task = asyncio.create_task(publish_heartbeat())
            
            def shutdown_signal():
                logger.info("Shutdown signal received")
                write_status(config.status_path, "stopping", message="Signal received")
                fuse_task.cancel()
                watcher_task.cancel()
                heartbeat_task.cancel()
                
            for s in (signal.SIGINT, signal.SIGTERM):
                asyncio.get_running_loop().add_signal_handler(s, shutdown_signal)

            try:
                await asyncio.gather(fuse_task, watcher_task)
            except asyncio.CancelledError:
                logger.info("Tasks cancelled")
            finally:
                heartbeat_task.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat_task
                logger.info("Unmounting %s", config.mount_point)
                write_status(config.status_path, "stopping", message="Unmounting")
                pyfuse3.unmount()
        except aiohttp.ClientConnectorError as e:
            logger.error(
                "Cannot connect to Yandex.Disk API (%s). Check Kali internet/DNS and restart CloudBridge.",
                e.host,
            )
            write_status(config.status_path, "error", message=f"Cannot connect to Yandex API: {e.host}")
            raise
        except Exception as e:
            write_status(config.status_path, "error", message=str(e))
            raise
        finally:
            await provider.close()
            write_status(config.status_path, "stopped", remote_root=config.remote_root)
            remove_pid(config.pid_path)

    if __name__ == "__main__":
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            pass
except Exception:
    traceback.print_exc()
