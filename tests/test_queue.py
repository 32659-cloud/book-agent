import asyncio

from book_agent.queue_worker import Job, JobQueue


def test_per_minute_limit_and_window():
    q = JobQueue(per_user_limit=99, per_minute=3)
    assert [q.reserve(1, now=t) for t in (0, 1, 2)] == [None, None, None]
    assert "每分鐘" in q.reserve(1, now=3)
    assert q.reserve(2, now=3) is None  # 別人不受影響
    assert q.reserve(1, now=61) is None  # 一分鐘後恢復


def test_per_user_and_total_limit():
    q = JobQueue(total_limit=3, per_user_limit=2, per_minute=99)
    assert q.reserve(1) is None and q.reserve(1) is None
    assert "排隊" in q.reserve(1)
    assert q.reserve(2) is None
    assert "太多" in q.reserve(3)
    q.release(1)
    assert q.reserve(3) is None


def test_worker_processes_one_at_a_time_in_order():
    async def main():
        q = JobQueue()
        running, peak, done = 0, 0, []

        async def process(job):
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            done.append(job.user_name)
            running -= 1

        task = asyncio.create_task(q.run(process))
        for i, n in enumerate("abc"):
            assert q.reserve(i) is None
            q.enqueue(Job(i, n, None, None, False))
        await asyncio.sleep(0.2)
        task.cancel()
        return peak, done

    peak, done = asyncio.run(main())
    assert peak == 1 and done == ["a", "b", "c"]


def test_worker_survives_a_failing_job():
    async def main():
        q = JobQueue()
        done = []

        async def process(job):
            if job.user_name == "bad":
                raise RuntimeError("boom")
            done.append(job.user_name)

        task = asyncio.create_task(q.run(process))
        for i, n in enumerate(["bad", "ok"]):
            q.reserve(i)
            q.enqueue(Job(i, n, None, None, False))
        await asyncio.sleep(0.1)
        task.cancel()
        return done

    assert asyncio.run(main()) == ["ok"]
