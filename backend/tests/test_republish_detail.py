"""测试 POST /api/v2/publish-details/<detail_id>/republish（按账号重新发布）。

覆盖：
- 视频：失败 detail 成功重建任务并入队（stub TaskQueue，不真实执行）
- 视频：非 failed 状态 → 409（成功账号绝不重复发布）
- 视频：账号已删除 → 400
- 视频：原视频文件被删 → 400
- 图集：失败 detail 同步重发成功（stub execute_image_publish）
- TaskQueue.republish_task：重置 DB 行为 queued + 刷新 batch 聚合
"""
import asyncio
import json
import os
import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS publish_batches (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    video_material_id TEXT DEFAULT '',
    image_material_ids TEXT DEFAULT '[]',
    landscape_cover_material_id TEXT DEFAULT '',
    portrait_cover_material_id TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    account_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    schedule_time TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS publish_details (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    account_id INTEGER,
    account_name TEXT NOT NULL DEFAULT '',
    platform TEXT NOT NULL DEFAULT '',
    account_configs TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    error_message TEXT NOT NULL DEFAULT '',
    publish_url TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    finished_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS user_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type INTEGER NOT NULL,
    filePath TEXT NOT NULL DEFAULT '',
    userName TEXT NOT NULL DEFAULT '',
    status INTEGER DEFAULT 0,
    avatar TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS materials (
    id TEXT PRIMARY KEY,
    original_filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    file_type TEXT NOT NULL,
    mime_type TEXT,
    file_size INTEGER DEFAULT 0,
    storage_type TEXT NOT NULL DEFAULT 'local'
);
"""


def _setup(db_path: Path, video_file: str):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA_SQL)
    # 账号：id=1 抖音(type=3)
    conn.execute(
        "INSERT INTO user_info (id, type, filePath, userName) VALUES (1, 3, 'cookies/dy1.json', '账号A')"
    )
    # 视频 batch：1 失败 + 1 成功 + 1 账号已删除 + 1 文件丢失
    conn.execute(
        "INSERT INTO publish_batches (id, type, title, status, created_at)"
        " VALUES ('bv1', 'video', '重发视频', 'partial', '2026-09-01')"
    )
    payload_ok = {
        "files": [video_file],
        "account_file": ["old_cookie.json"],
        "title": "重发视频", "desc": "描述", "tags": ["t1"],
        "schedule_time_str": "", "enableTimer": 0,
    }
    cfg_ok = json.dumps({
        "title": "重发视频", "description": "描述", "tags": ["t1"],
        "publishPayload": payload_ok,
    }, ensure_ascii=False)
    conn.execute(
        "INSERT INTO publish_details (id, batch_id, account_id, account_name, platform,"
        " account_configs, status, error_message)"
        " VALUES ('dv-failed', 'bv1', 1, '账号A', '抖音', ?, 'failed', 'cookie 过期')",
        (cfg_ok,),
    )
    conn.execute(
        "INSERT INTO publish_details (id, batch_id, account_id, account_name, platform,"
        " account_configs, status)"
        " VALUES ('dv-success', 'bv1', 1, '账号A', '抖音', ?, 'success')",
        (cfg_ok,),
    )
    conn.execute(
        "INSERT INTO publish_details (id, batch_id, account_id, account_name, platform,"
        " account_configs, status)"
        " VALUES ('dv-no-account', 'bv1', 999, '已删账号', '抖音', ?, 'failed')",
        (cfg_ok,),
    )
    cfg_missing_file = json.dumps({
        "title": "重发视频",
        "publishPayload": {"files": ["/nonexistent/gone.mp4"], "title": "x"},
    }, ensure_ascii=False)
    conn.execute(
        "INSERT INTO publish_details (id, batch_id, account_id, account_name, platform,"
        " account_configs, status)"
        " VALUES ('dv-no-file', 'bv1', 1, '账号A', '抖音', ?, 'failed')",
        (cfg_missing_file,),
    )
    # 图集 batch：1 失败
    conn.execute(
        "INSERT INTO publish_batches (id, type, title, status, image_material_ids, created_at)"
        " VALUES ('bi1', 'image', '重发图集', 'failed', '[\"mi1\"]', '2026-09-01')"
    )
    conn.execute(
        "INSERT INTO materials (id, original_filename, stored_path, file_type)"
        " VALUES ('mi1', 'p1.jpg', 'materials/2026/09/01/p1.jpg', 'image')"
    )
    conn.execute(
        "INSERT INTO publish_details (id, batch_id, account_id, account_name, platform,"
        " account_configs, status)"
        " VALUES ('di-failed', 'bi1', 1, '账号A', '抖音', ?, 'failed')",
        (json.dumps({"title": "重发图集", "dry_run": True}),),
    )
    conn.commit()
    conn.close()


class TestRepublishDetail(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp()
        os.environ['SAU_DATA_DIR'] = cls._tmpdir
        cls.DB_PATH = Path(cls._tmpdir) / "db" / "database.db"
        # 真实视频文件（重发要过 os.path.isfile 校验）
        cls.video_file = str(Path(cls._tmpdir) / "v.mp4")
        Path(cls.video_file).write_bytes(b"fake")
        _setup(cls.DB_PATH, cls.video_file)
        from ext_api import app
        cls.client = app.test_client()

    def setUp(self):
        self._patches = [
            patch('ext_api.DB_PATH', self.DB_PATH),
            patch('ext_api.task_queue.DB_PATH', self.DB_PATH),
            patch('blueprints.image_publish_bp.DB_PATH', self.DB_PATH),
        ]
        for p in self._patches:
            p.start()
        # stub TaskQueue：绝不真实执行发布
        self.captured = []
        self.tq_stub = MagicMock()
        self.tq_stub.republish_task.side_effect = lambda task: (
            self.captured.append(task) or True
        )
        self._tq_patch = patch('ext_api.get_task_queue', return_value=self.tq_stub)
        self._tq_patch.start()

    def tearDown(self):
        self._tq_patch.stop()
        for p in self._patches:
            p.stop()

    # ---------- 视频 ----------

    def test_video_failed_detail_republish_ok(self):
        resp = self.client.post('/api/v2/publish-details/dv-failed/republish')
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data['code'], 200)
        self.assertEqual(data['data']['status'], 'queued')
        # 任务用同一 detail id 重建，payload 完整透传
        self.assertEqual(len(self.captured), 1)
        task = self.captured[0]
        self.assertEqual(task.id, 'dv-failed')
        self.assertEqual(task.batch_id, 'bv1')
        self.assertEqual(task.platform_type, 3)
        self.assertEqual(task.platform, '抖音')
        self.assertEqual(task.video_path, self.video_file)
        self.assertEqual(task.payload['files'], [self.video_file])
        # cookie 以 user_info 当前值为准（可能重新导入过）
        self.assertEqual(task.payload['account_file'], ['cookies/dy1.json'])
        self.assertEqual(task.account_cookie_path, 'cookies/dy1.json')

    def test_success_detail_rejected_409(self):
        """成功的账号绝不重复发布"""
        resp = self.client.post('/api/v2/publish-details/dv-success/republish')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(len(self.captured), 0)

    def test_account_deleted_rejected_400(self):
        resp = self.client.post('/api/v2/publish-details/dv-no-account/republish')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('账号', resp.get_json()['msg'])
        self.assertEqual(len(self.captured), 0)

    def test_video_file_missing_rejected_400(self):
        resp = self.client.post('/api/v2/publish-details/dv-no-file/republish')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('文件', resp.get_json()['msg'])
        self.assertEqual(len(self.captured), 0)

    def test_detail_not_found_404(self):
        resp = self.client.post('/api/v2/publish-details/nope/republish')
        self.assertEqual(resp.status_code, 404)

    def test_queue_conflict_returns_409(self):
        """同 id 任务已在队列/执行中 → 409（幂等防连点）"""
        self.tq_stub.republish_task.side_effect = lambda task: False
        resp = self.client.post('/api/v2/publish-details/dv-failed/republish')
        self.assertEqual(resp.status_code, 409)

    # ---------- 图集 ----------

    def test_image_failed_detail_republish_ok(self):
        import blueprints.image_publish_bp as ipb
        with patch.object(ipb, 'execute_image_publish', return_value=(True, '')) as exec_mock:
            resp = self.client.post('/api/v2/publish-details/di-failed/republish')
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data['data']['status'], 'success')
        # config 补上了 filePath（存储时排除），图片从 batch.image_material_ids 解析
        called_config, called_files = exec_mock.call_args[0]
        self.assertEqual(called_config['filePath'], 'cookies/dy1.json')
        self.assertEqual(called_files, ['materials/2026/09/01/p1.jpg'])
        # detail 落 success
        conn = sqlite3.connect(str(self.DB_PATH))
        row = conn.execute(
            "SELECT status FROM publish_details WHERE id='di-failed'"
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], 'success')


class TestRepublishTaskQueueDBReset(unittest.TestCase):
    """TaskQueue.republish_task 的 DB 行为：重置原行为 queued + 刷新 batch 聚合。"""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp()
        os.environ['SAU_DATA_DIR'] = cls._tmpdir
        cls.DB_PATH = Path(cls._tmpdir) / "db" / "database.db"
        _setup(cls.DB_PATH, str(Path(cls._tmpdir) / "v.mp4"))

    def test_republish_task_resets_db(self):
        from ext_api.task_queue import TaskQueue, PublishTask
        with patch('ext_api.task_queue.DB_PATH', self.DB_PATH):
            tq = TaskQueue()
            tq._started = True           # 跳过 start()，不起真实事件循环
            tq._loop = None
            tq.queue = asyncio.Queue()
            task = PublishTask(
                id='dv-failed', batch_id='bv1', platform='抖音', platform_type=3,
                account_name='账号A', account_cookie_path='cookies/dy1.json',
                video_path='/tmp/v.mp4', title='重发视频',
            )
            # run_coroutine_threadsafe 收到的协程直接 close，避免未 await 告警
            with patch('ext_api.task_queue.asyncio.run_coroutine_threadsafe',
                       side_effect=lambda coro, loop: coro.close()):
                ok = tq.republish_task(task)
            self.assertTrue(ok)
            self.assertIn('dv-failed', tq._queued_ids)

        conn = sqlite3.connect(str(self.DB_PATH))
        d = conn.execute(
            "SELECT status, error_message, publish_url, started_at, finished_at"
            " FROM publish_details WHERE id='dv-failed'"
        ).fetchone()
        b = conn.execute(
            "SELECT status FROM publish_batches WHERE id='bv1'"
        ).fetchone()
        conn.close()
        self.assertEqual(d[0], 'queued')
        self.assertEqual(d[1], '')      # 错误清空
        self.assertIsNone(d[3])         # started_at 重置
        self.assertIsNone(d[4])         # finished_at 重置
        self.assertEqual(b[0], 'running')  # 有 queued detail → batch 回到 running

    def test_republish_task_rejects_when_in_queue(self):
        from ext_api.task_queue import TaskQueue, PublishTask
        with patch('ext_api.task_queue.DB_PATH', self.DB_PATH):
            tq = TaskQueue()
            tq._started = True
            tq._loop = None
            tq.queue = asyncio.Queue()
            tq._queued_ids.add('dv-failed')  # 模拟已在队列
            task = PublishTask(id='dv-failed', batch_id='bv1', platform='抖音')
            self.assertFalse(tq.republish_task(task))


if __name__ == '__main__':
    unittest.main()
