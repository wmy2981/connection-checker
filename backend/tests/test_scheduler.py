"""调度器回归测试：目标更新污染、任务死亡重建、watchdog 存活。"""

import asyncio

import pytest

from app.config import Settings
from app.models import Target, TimeRange
from app.notifier import Notifier
from app.scheduler import CONFIG_WATCH_INTERVAL, Scheduler
from app.storage import ConfigStore, ResultStore


async def _make_scheduler(tmp_path, settings: Settings) -> Scheduler:
    store = ConfigStore(tmp_path / "data")
    rs = ResultStore(tmp_path / "data" / "results.jsonl", 100)
    return Scheduler(store, rs, Notifier(store), settings)


async def test_update_target_keeps_time_range_model(logged_client, no_scheduler):
    """回归：PUT 更新目标后 time_ranges 必须是 TimeRange 模型。

    早期版本用 model_copy(update=dict) 不重新验证嵌套模型，time_ranges 会变成
    dict，调度循环里 is_time_in_ranges 访问 r.start 抛 AttributeError 杀死任务。
    """
    resp = logged_client.post(
        "/api/v1/targets",
        json={
            "name": "t1",
            "ip": "10.0.0.1",
            "check_method": "http",
            "check_interval": 60,
            "time_ranges": [{"start": "00:00", "end": "23:59"}],
        },
    )
    assert resp.status_code == 201
    tid = resp.json()["id"]

    resp = logged_client.put(
        f"/api/v1/targets/{tid}",
        json={"name": "t1-renamed", "time_ranges": [{"start": "08:00", "end": "20:00"}]},
    )
    assert resp.status_code == 200

    store: ConfigStore = logged_client.app.state.config_store
    target = await store.get_target(tid)
    assert target is not None
    assert isinstance(target.time_ranges[0], TimeRange)
    assert target.time_ranges[0].start == "08:00"


async def test_scheduler_loop_survives_polluted_time_ranges(tmp_path, settings, fake_checker):
    """回归：即便内存里 time_ranges 被污染为 dict，调度任务也不得死亡。"""
    fake_checker()
    sched = await _make_scheduler(tmp_path, settings)
    target = Target(id="x1", name="t", ip="127.0.0.1", check_method="http", check_interval=60)
    await sched.config_store.upsert_target(target)
    await sched.start()
    try:
        # 模拟旧版 API 路径造成的污染（dict 列表，缺 .start/.end 属性）
        polluted = target.model_copy(update={"time_ranges": [{"start": "00:00", "end": "23:59"}]})
        sched.config_store.targets[target.id] = polluted
        await asyncio.sleep(0.3)  # 给第一轮循环一点执行时间
        assert not sched._tasks[target.id].done(), "调度任务不应因 dict time_ranges 死亡"
        # 已恢复的类型（重新加载或后续保存）应能正常继续
        await sched.config_store.upsert_target(target)
        await asyncio.sleep(0.2)
        assert not sched._tasks[target.id].done()
    finally:
        await sched.stop()


async def test_reconcile_rebuilds_dead_task(tmp_path, settings, fake_checker):
    """回归：任务异常退出后 reconcile 必须重建，否则定时检查永久停摆。"""
    fake_checker()
    sched = await _make_scheduler(tmp_path, settings)
    target = Target(id="x1", name="t", ip="127.0.0.1", check_method="http", check_interval=60)
    await sched.config_store.upsert_target(target)
    await sched.start()
    try:
        task = sched._tasks[target.id]
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.done()

        await sched.reconcile()
        rebuilt = sched._tasks[target.id]
        assert rebuilt is not task
        assert not rebuilt.done()
    finally:
        await sched.stop()


async def test_watchdog_survives_config_change(tmp_path, settings, fake_checker):
    """回归：外部修改 config.json 触发热加载时 watchdog 不得死亡。

    早期版本在 watchdog 里 await 同步方法 resize（返回 None），Python 3.12 抛
    TypeError 杀死 watchdog，导致配置热加载永久失效。
    """
    fake_checker()
    sched = await _make_scheduler(tmp_path, settings)
    target = Target(id="x1", name="t", ip="127.0.0.1", check_method="http", check_interval=60)
    await sched.config_store.upsert_target(target)
    await sched.start()
    try:
        await asyncio.sleep(0.2)
        sched.config_store._persist()  # 改写磁盘使 mtime 变化，模拟外部编辑
        await asyncio.sleep(CONFIG_WATCH_INTERVAL + 1)
        assert not sched._watchdog.done(), "watchdog 不应因 resize TypeError 死亡"
        assert not sched._tasks[target.id].done()
    finally:
        await sched.stop()
