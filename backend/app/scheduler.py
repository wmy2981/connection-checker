"""检查调度器：每个启用的目标一个 asyncio 任务，独立间隔循环；配置变更热生效。"""
import asyncio
import logging
from datetime import datetime

from app.checkers import build_checker
from app.config import Settings
from app.logging_setup import apply_level
from app.models import CheckResult, Target
from app.notifier import Notifier
from app.storage import ConfigStore, ResultStore, SecretsStore
from app.timeutil import is_time_in_ranges

logger = logging.getLogger(__name__)

CONFIG_WATCH_INTERVAL = 5.0


class Scheduler:
    def __init__(
        self,
        config_store: ConfigStore,
        result_store: ResultStore,
        notifier: Notifier,
        settings: Settings,
        secrets_store: SecretsStore | None = None,
    ) -> None:
        self.config_store = config_store
        self.result_store = result_store
        self.notifier = notifier
        self.settings = settings
        self.secrets_store = secrets_store
        self._tasks: dict[str, asyncio.Task] = {}
        self._watchdog: asyncio.Task | None = None
        self._last_mtime: float | None = config_store.file_mtime()

    async def start(self) -> None:
        await self.reconcile()
        self._watchdog = asyncio.create_task(self._watch_config(), name="config-watchdog")

    async def stop(self) -> None:
        if self._watchdog:
            self._watchdog.cancel()
        for task in list(self._tasks.values()):
            task.cancel()
        self._tasks.clear()

    async def reconcile(self) -> None:
        """按当前配置创建/停止目标任务。"""
        targets = await self.config_store.list_targets()
        # check_interval=0 表示仅手动检查，不创建定时任务
        enabled_ids = {t.id for t in targets if t.enabled and t.check_interval > 0}
        for tid in list(self._tasks):
            if tid not in enabled_ids:
                self._stop_task(tid)
        for t in targets:
            if not (t.enabled and t.check_interval > 0):
                continue
            task = self._tasks.get(t.id)
            if task is not None and task.done():
                # 任务异常退出（如早期版本被污染的 time_ranges 触发 AttributeError）：
                # 死亡任务残留在字典里会导致永不重建，此处移除并重建
                logger.warning(
                    "Scheduler task for target %s (%s) exited (cancelled=%s), rebuilding",
                    t.name or t.ip,
                    t.id,
                    task.cancelled(),
                )
                self._tasks.pop(t.id, None)
            if t.id not in self._tasks:
                self._tasks[t.id] = asyncio.create_task(
                    self._run_loop(t.id), name=f"check:{t.id}"
                )
                logger.info("Scheduled target %s (%s)", t.name or t.ip, t.id)

    def _stop_task(self, target_id: str) -> None:
        task = self._tasks.pop(target_id, None)
        if task:
            task.cancel()

    async def _run_loop(self, target_id: str) -> None:
        try:
            while True:
                target = await self.config_store.get_target(target_id)
                if target is None:
                    break
                now = datetime.now().astimezone()
                try:
                    if is_time_in_ranges(now, target.time_ranges):
                        await self.run_check(target)
                except Exception as e:  # noqa: BLE001
                    # 任何单次异常（含数据被污染）都不能杀死任务；记录后继续下一轮
                    logger.exception(
                        "Scheduler loop error for target %s: %s",
                        target.name or target.ip,
                        e,
                    )
                await asyncio.sleep(target.check_interval)
        except asyncio.CancelledError:
            pass

    async def run_check(self, target: Target) -> CheckResult:
        """对单个目标执行一次检查并落库。"""
        app_cfg = await self.config_store.get_app_settings()
        default_timeout = (
            app_cfg.http_timeout
            if target.check_method == "http"
            else app_cfg.connect_timeout
        )
        logger.debug(
            "Starting check %s (%s) [%s] timeout=%ss ping_count=%s",
            target.name or target.ip,
            target.id,
            target.check_method,
            default_timeout,
            target.ping_count or app_cfg.ping_count,
        )
        checker = build_checker(
            target,
            default_timeout=default_timeout,
            ping_count=target.ping_count or app_cfg.ping_count,
            success_codes=self.settings.http_success_codes,
        )
        outcome = await checker.check(target)
        result = CheckResult(
            target_id=target.id,
            target_name=target.name,
            ip=target.ip,
            check_method=target.check_method,
            status=outcome.status,
            latency_ms=outcome.latency_ms,
            message=outcome.message,
            extra=outcome.extra,
        )
        await self.result_store.append(result)
        logger.debug(
            "Result stored: id=%s status=%s latency=%sms",
            result.id,
            result.status,
            result.latency_ms,
        )
        await self.notifier.observe(result)
        args = (
            target.name or target.ip,
            target.id,
            target.check_method,
            result.status,
            result.latency_ms,
            result.message,
        )
        if result.status == "error":
            logger.error("Check error %s (%s) [%s] status=%s latency=%sms msg=%s", *args)
        elif result.status == "timeout":
            logger.warning(
                "Check timed out %s (%s) [%s] status=%s latency=%sms msg=%s", *args
            )
        elif result.status == "fail":
            logger.warning("Check failed %s (%s) [%s] status=%s latency=%sms msg=%s", *args)
        else:
            logger.info("Check finished %s (%s) [%s] status=%s latency=%sms msg=%s", *args)
        return result

    async def manual_run(self, target_id: str | None = None) -> list[CheckResult]:
        """手动立即检查。target_id 为空则并发检查全部启用的目标（限流 10 并发）。"""
        targets = await self.config_store.list_targets()
        selected = [
            t
            for t in targets
            if t.enabled and (target_id is None or t.id == target_id)
        ]
        if not selected:
            return []
        sem = asyncio.Semaphore(10)

        async def _guarded(t: Target) -> CheckResult:
            # 单个目标异常（防御性，检查器通常不抛）不拖垮其他目标，
            # 但以 error 结果返回：崩溃在界面可见，而不是被静默丢弃（前端会误报「全部正常」）
            try:
                async with sem:
                    return await self.run_check(t)
            except Exception as e:  # noqa: BLE001
                logger.error(
                    "Manual check failed for %s (%s): %s", t.name or t.ip, t.id, e
                )
                return CheckResult(
                    target_id=t.id,
                    target_name=t.name,
                    ip=t.ip,
                    check_method=t.check_method,
                    status="error",
                    latency_ms=None,
                    message=f"check crashed: {e}",
                    extra={},
                )

        results = await asyncio.gather(*(_guarded(t) for t in selected))
        return list(results)

    async def _watch_config(self) -> None:
        """检测 config.json 被外部编辑并热重载。"""
        try:
            while True:
                await asyncio.sleep(CONFIG_WATCH_INTERVAL)
                mtime = self.config_store.file_mtime()
                if mtime is not None and mtime != self._last_mtime:
                    self._last_mtime = mtime
                    await self.config_store.reload()
                    app_cfg = await self.config_store.get_app_settings()
                    # resize 是同步方法；await 它会在 Python 3.12 抛 TypeError 杀死 watchdog
                    self.result_store.resize(app_cfg.result_max_records)
                    if self.secrets_store is not None:
                        s3_cfg = await self.config_store.get_s3_config()
                        self.result_store.set_s3_mode(
                            app_cfg.storage_mode,
                            s3_cfg,
                            self.secrets_store.s3_access_id,
                            self.secrets_store.s3_access_key,
                        )
                    apply_level(app_cfg.log_level)
                    await self.reconcile()
                    logger.info(
                        "Config hot-reloaded: targets=%d, result_max_records=%d, log_level=%s",
                        len(await self.config_store.list_targets()),
                        app_cfg.result_max_records,
                        app_cfg.log_level,
                    )
        except asyncio.CancelledError:
            pass
