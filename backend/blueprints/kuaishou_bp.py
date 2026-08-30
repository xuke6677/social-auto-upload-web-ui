"""快手创作者平台相关 API 代理（合集列表）。

用 CloakBrowser 打开快手发布页 → 上传探测视频触发表单渲染 →
点开「选择合集」antd 下拉 → 解析选项文本(第一行是合集名) → 返回给前端。

DOM（实测 cp.kuaishou.com/article/publish/video）:
  入口: .ant-select:has(span.ant-select-selection-placeholder:has-text('合集')) .ant-select-selector
        （placeholder 上层有 search input 遮挡，需 force 点击）
  下拉: .ant-select-dropdown .ant-select-item-option
        inner_text 第一行是合集名，第二行是「共N个作品」
"""

from __future__ import annotations

import asyncio
import shutil
import sqlite3
import subprocess
from pathlib import Path

from flask import Blueprint, request, jsonify

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from conf import BASE_DIR
from util._logger import get_channel_logger
from impl._browser import create_browser, create_context

logger = get_channel_logger("kuaishou")

kuaishou_bp = Blueprint('kuaishou', __name__, url_prefix='/api/kuaishou')

_KS_UPLOAD_URL = "https://cp.kuaishou.com/article/publish/video"


def _get_cookie_path(cookie_file: str) -> str:
    return str(Path(BASE_DIR / "cookiesFile" / cookie_file))


def _get_account_cookie_file(account_id: str) -> str | None:
    """从数据库取快手账号(type=4) cookie 文件名。account_id 为空时取任意一个。"""
    # 前端模板字符串可能把 null 拼成 "null"/"undefined"，统一视为未传
    if account_id in (None, "", "null", "undefined", "None"):
        account_id = None
    conn = sqlite3.connect(str(Path(BASE_DIR / "db" / "database.db")))
    cursor = conn.cursor()
    if account_id:
        cursor.execute("SELECT filePath FROM user_info WHERE id = ? AND type = 4", (account_id,))
    else:
        cursor.execute("SELECT filePath FROM user_info WHERE type = 4 LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import threading
            result = {}

            def _run():
                new_loop = asyncio.new_event_loop()
                try:
                    result["v"] = new_loop.run_until_complete(coro)
                finally:
                    new_loop.close()

            t = threading.Thread(target=_run)
            t.start()
            t.join()
            return result.get("v")
    except RuntimeError:
        pass
    return asyncio.run(coro)


def _ensure_probe_video() -> Path | None:
    """生成 2s 黑屏探测视频（ffmpeg），用于触发发布表单渲染。缓存复用。

    注意：快手会校验视频流（支付宝用的最小 MP4 头在快手会报「视频流不存在」），
    必须是有真实视频流的文件。
    """
    probe = Path(BASE_DIR / ".ks_probe_video.mp4")
    if probe.exists():
        return probe
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logger.warning("[合集列表] 未找到 ffmpeg，无法生成探测视频")
        return None
    try:
        subprocess.run(
            [ffmpeg, "-y", "-f", "lavfi", "-i", "color=black:s=640x360:d=2:r=15",
             "-pix_fmt", "yuv420p", "-c:v", "libx264", str(probe)],
            check=True, capture_output=True, timeout=60,
        )
        return probe if probe.exists() else None
    except Exception as e:
        logger.warning(f"[合集列表] 生成探测视频失败: {e}")
        return None


@kuaishou_bp.route('/collections', methods=['GET'])
def list_collections():
    """获取快手账号的合集列表。

    Query params:
        account_id: 账号 id（可空，空则取任意一个快手账号）

    Returns:
        {"code": 200, "data": {"list": [{"name": ...}], "total": N}}
    """
    account_id = request.args.get('account_id')
    logger.info(f"[合集列表] 收到请求: account_id={account_id}")

    try:
        cookie_file = _get_account_cookie_file(account_id)
        if not cookie_file:
            logger.warning(f"[合集列表] 账号不存在: {account_id}")
            return jsonify({"code": 404, "msg": "没有可用的快手账号"}), 404

        result = run_async(_fetch_collections_via_browser(cookie_file))

        if result.get("success"):
            data = result.get("data", {})
            logger.info(f"[合集列表] 成功,共 {data.get('total', 0)} 个合集")
            return jsonify({"code": 200, "data": data})
        else:
            logger.error(f"[合集列表] 失败: {result.get('error')}")
            return jsonify({"code": 500, "msg": result.get("error", "请求失败")}), 500
    except Exception as e:
        logger.error(f"[合集列表] 异常: {e}", exc_info=True)
        return jsonify({"code": 500, "msg": str(e)}), 500


async def _fetch_collections_via_browser(cookie_file: str) -> dict:
    """打开快手发布页 → 上传探测视频触发表单 → 点开「选择合集」→ 解析下拉合集名。"""
    cookie_path = _get_cookie_path(cookie_file)

    probe_video = _ensure_probe_video()
    if not probe_video:
        return {"success": False, "error": "无法生成探测视频（需要 ffmpeg）"}

    browser = await create_browser(headless=True)
    try:
        context = await create_context(browser, storage_state=cookie_path)
        try:
            page = await context.new_page()
            try:
                await page.goto(_KS_UPLOAD_URL, timeout=30000)
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception as e:
                logger.info(f"[合集列表] 页面加载(非致命): {e}")
            await asyncio.sleep(3)

            # 登录态失效时快手会跳登录页，直接给出明确报错
            if "login" in page.url:
                return {"success": False, "error": "快手登录态已过期,请先在「账号管理」重新登录该账号"}

            # 上传探测视频触发表单渲染（合集字段在表单渲染后才出现）
            file_input = page.locator("input[type='file']").first
            for _ in range(30):
                if await file_input.count() > 0:
                    break
                await asyncio.sleep(0.5)
            if await file_input.count() == 0:
                return {"success": False, "error": "未找到视频上传入口"}
            await file_input.set_input_files(str(probe_video))
            logger.info("[合集列表] 探测视频已上传,等待表单渲染...")
            await asyncio.sleep(12)

            # 关闭可能的提示弹窗（我知道了/确定/知道了）
            for btn_text in ("我知道了", "确定", "知道了"):
                btn = page.get_by_role("button", name=btn_text)
                if await btn.count() > 0:
                    try:
                        await btn.first.click(timeout=2000)
                        await asyncio.sleep(0.5)
                    except Exception:
                        pass

            # 点开「选择合集」（placeholder 有 search input 遮挡，force 点击 selector 容器）
            sel = page.locator(
                ".ant-select:has(span.ant-select-selection-placeholder:has-text('合集')) "
                ".ant-select-selector"
            ).first
            if await sel.count() == 0:
                return {"success": False, "error": "未找到「选择合集」下拉（表单可能未渲染完成）"}
            await sel.click(force=True, timeout=8000)
            await asyncio.sleep(2)

            options = page.locator(".ant-select-dropdown .ant-select-item-option")
            for _ in range(20):
                if await options.count() > 0:
                    break
                await asyncio.sleep(0.5)

            count = await options.count()
            if count == 0:
                # 账号没有任何合集时下拉为空，属正常情况
                logger.info("[合集列表] 该账号暂无合集")
                return {"success": True, "data": {"list": [], "total": 0}}

            items = []
            for i in range(count):
                try:
                    text = (await options.nth(i).inner_text()).strip()
                except Exception:
                    continue
                # inner_text 第一行是合集名（第二行是「共N个作品」）
                name = text.split("\n")[0].strip()
                if name:
                    items.append({"name": name})

            logger.info(f"[合集列表] 解析完成,共 {len(items)} 个合集")
            return {"success": True, "data": {"list": items, "total": len(items)}}
        finally:
            await context.close()
    finally:
        await browser.close()
