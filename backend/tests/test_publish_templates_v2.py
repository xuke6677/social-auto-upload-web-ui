"""
测试 GET /api/v2/publish-templates 读新表的行为。
旧的 test_publish_templates.py 仍要更新（Task 5），但本次先新建针对新表语义的测试。
"""
import os
import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
    finished_at TIMESTAMP,
    FOREIGN KEY (batch_id) REFERENCES publish_batches(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS materials (
    id TEXT PRIMARY KEY,
    original_filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    file_type TEXT NOT NULL,
    mime_type TEXT,
    file_size INTEGER,
    storage_type TEXT NOT NULL DEFAULT 'local',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _setup(db_path: Path):
    """建 schema 并塞测试数据。不能调 init_db.init_database()，因为 init_db.DB_PATH 在 import 时已绑定。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA_SQL)
    # 1 个视频 batch：1 个 detail 带 account_configs
    conn.execute("INSERT INTO publish_batches (id, type, title, status, account_count, success_count, created_at) VALUES ('bv1', 'video', '可复用视频', 'success', 1, 1, '2026-06-01')")
    conn.execute("INSERT INTO publish_details (id, batch_id, account_name, platform, account_configs, status) VALUES ('dv1', 'bv1', '账号A', '抖音', '{\"title\":\"可复用视频\",\"description\":\"描述\",\"tags\":[\"标签1\"]}', 'success')")
    # 1 个图文 batch（带首图素材，cover_url 应兜底到第一张图）
    conn.execute("INSERT INTO publish_batches (id, type, title, status, account_count, success_count, image_material_ids, created_at) VALUES ('bi1', 'image', '可复用图文', 'success', 1, 1, '[\"mat-img-1\"]', '2026-06-02')")
    conn.execute("INSERT INTO publish_details (id, batch_id, account_name, platform, account_configs, status) VALUES ('di1', 'bi1', '账号B', '抖音', '{\"title\":\"可复用图文\"}', 'success')")
    # 1 个失败的 batch：不应被返回
    conn.execute("INSERT INTO publish_batches (id, type, title, status, account_count, success_count, created_at) VALUES ('bx1', 'video', '失败视频', 'failed', 1, 0, '2026-06-03')")
    conn.execute("INSERT INTO publish_details (id, batch_id, account_name, platform, account_configs, status) VALUES ('dx1', 'bx1', '账号C', '抖音', '{}', 'failed')")
    # 1 个无 cover material_id、封面只在 account_configs 里的视频 batch（抽帧/个性化封面场景）
    conn.execute("INSERT INTO publish_batches (id, type, title, status, account_count, success_count, created_at) VALUES ('bv2', 'video', '抽帧封面视频', 'success', 1, 1, '2026-05-31')")
    conn.execute("INSERT INTO publish_details (id, batch_id, account_name, platform, account_configs, status) VALUES ('dv2', 'bv2', '账号A', '抖音', '{\"title\":\"抽帧封面视频\",\"coverLandscape\":{\"stored_path\":\"covers/2026/09/03/cover.png\"}}', 'success')")
    # material 行：让 cover material_id 解析得到 stored_path
    conn.execute(
        "INSERT INTO materials (id, original_filename, stored_path, file_type, mime_type, file_size, storage_type) "
        "VALUES ('mat-cover-1', 'cover.jpg', 'materials/2026/06/01/cover.jpg', 'image', 'image/jpeg', 12345, 'local')"
    )
    conn.execute(
        "INSERT INTO materials (id, original_filename, stored_path, file_type, mime_type, file_size, storage_type) "
        "VALUES ('mat-img-1', 'p1.jpg', 'materials/2026/06/02/p1.jpg', 'image', 'image/jpeg', 12345, 'local')"
    )
    conn.execute(
        "UPDATE publish_batches SET landscape_cover_material_id = 'mat-cover-1' WHERE id = 'bv1'"
    )
    conn.commit()
    conn.close()


class TestPublishTemplatesV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 临时数据目录 + DB 路径都建在 setUpClass 里，避免模块级 setup 污染其他测试
        cls._tmpdir = tempfile.mkdtemp()
        os.environ['SAU_DATA_DIR'] = cls._tmpdir
        cls.DB_PATH = Path(cls._tmpdir) / "db" / "database.db"
        _setup(cls.DB_PATH)
        from ext_api import app
        cls.client = app.test_client()

    def setUp(self):
        # 强制 ext_api._db_conn() 用测试 DB（ext_api.DB_PATH 在 import 时已绑定）
        self._db_path_patch = patch('ext_api.DB_PATH', self.DB_PATH)
        self._db_path_patch.start()

    def tearDown(self):
        self._db_path_patch.stop()

    def test_video_type_returns_video_batches(self):
        resp = self.client.get('/api/v2/publish-templates?type=video')
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data['code'], 200)
        items = data['data']['list']
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['type'], 'video')
        self.assertEqual(items[0]['title'], '可复用视频')
        # account_configs 取第一个 detail 的
        self.assertEqual(items[0]['account_configs'].get('title'), '可复用视频')
        self.assertEqual(len(items[0]['channels']), 1)
        self.assertEqual(items[0]['channels'][0]['platform'], '抖音')

    def test_image_type_returns_image_batches(self):
        resp = self.client.get('/api/v2/publish-templates?type=image')
        items = resp.get_json()['data']['list']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['type'], 'image')

    def test_failed_batches_excluded(self):
        """status=failed 的 batch 不应在 templates 列表里（因为 EXIST 过滤 + status IN）"""
        resp = self.client.get('/api/v2/publish-templates?type=video')
        items = resp.get_json()['data']['list']
        ids = [i['id'] for i in items]
        self.assertNotIn('bx1', ids)

    def test_missing_type_returns_400(self):
        resp = self.client.get('/api/v2/publish-templates')
        self.assertEqual(resp.status_code, 400)

    def test_video_thumbnail_path_resolves_to_material_stored_path(self):
        """thumbnail_path 应该是 material_id 解析后的 stored_path，不是 raw UUID"""
        resp = self.client.get('/api/v2/publish-templates?type=video')
        items = resp.get_json()['data']['list']
        self.assertEqual(items[0]['thumbnail_path'], 'materials/2026/06/01/cover.jpg')

    def test_cover_url_from_cover_material_id(self):
        """cover_url：batch 上有 cover material_id 时，直接解析为 /api/materials/file/<quoted>"""
        resp = self.client.get('/api/v2/publish-templates?type=video')
        items = resp.get_json()['data']['list']
        bv1 = next(i for i in items if i['id'] == 'bv1')
        self.assertEqual(
            bv1['cover_url'],
            '/api/materials/file/materials%2F2026%2F06%2F01%2Fcover.jpg',
        )

    def test_cover_url_fallback_to_account_configs(self):
        """cover_url：batch 上无 cover material_id（抽帧/个性化封面）时，
        兜底到 account_configs.coverLandscape.stored_path —— 这是一键填写弹窗
        图片不显示的根因场景"""
        resp = self.client.get('/api/v2/publish-templates?type=video')
        items = resp.get_json()['data']['list']
        bv2 = next(i for i in items if i['id'] == 'bv2')
        self.assertEqual(bv2['thumbnail_path'], '')  # batch 列上确实没有
        self.assertEqual(
            bv2['cover_url'],
            '/api/materials/file/covers%2F2026%2F09%2F03%2Fcover.png',
        )

    def test_cover_url_image_type_fallback_to_first_image(self):
        """cover_url：image 类型无封面配置时，兜底到 image_material_ids 第一张图"""
        resp = self.client.get('/api/v2/publish-templates?type=image')
        items = resp.get_json()['data']['list']
        self.assertEqual(
            items[0]['cover_url'],
            '/api/materials/file/materials%2F2026%2F06%2F02%2Fp1.jpg',
        )


if __name__ == '__main__':
    unittest.main()
