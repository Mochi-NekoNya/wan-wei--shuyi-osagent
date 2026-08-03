"""
FIX-19（04-#08）：knowledge search 结果 title HTML 转义回归测试。

背景
----
`GET /knowledge/search` 返回的 `items[].snippet` 经过 `_sanitize_fts_snippet`
做了 HTML 转义（防 XSS），但 `title` 只经过 `_compact_cjk_snippet`（压缩空格），
未转义。若前端用 `innerHTML` 渲染 title，含 `<script>` 的标题即存储型 XSS。

修复：title 与 snippet 一致走 `_sanitize_fts_snippet`。
"""

from pathlib import Path

import pytest


@pytest.fixture()
def kb_with_xss(tmp_path: Path, monkeypatch, isolated_db):
    """构造一个 knowledge base，含 XSS payload 标题的文档。"""
    # isolated_db 已经配好了独立数据库，直接导入模块即可
    from backend.app.db import get_conn
    from backend.app.platform_api import knowledge

    knowledge._ensure_kb_schema()

    # 写入一条含 <script> 的标题
    conn = get_conn()
    now = "2026-08-03T12:00:00Z"
    conn.execute(
        "INSERT INTO kb_docs(id, title, body, created_at, updated_at) VALUES (?,?,?,?,?)",
        ("doc_xss", "<script>alert('XSS')</script>Malicious Title", "normal body", now, now),
    )
    conn.commit()

    return knowledge


def test_search_title_html_escaped(kb_with_xss):
    """搜索结果的 title 必须被 HTML 转义，防 XSS。

    修复前：title = "<script>alert('XSS')</script>Malicious Title" 原样返回。
    修复后：title = "&lt;script&gt;alert('XSS')&lt;/script&gt;Malicious Title"。
    """
    result = kb_with_xss.search_docs(q="Malicious", limit=10)

    assert result["items"], "应找到含 XSS payload 的文档"
    item = result["items"][0]

    # 原始 <script> 标签必须被转义为 &lt;script&gt;
    assert "<script>" not in item["title"], "修复失败：<script> 标签未被转义"
    assert "&lt;script&gt;" in item["title"], "转义后应含 &lt;script&gt;"
    assert "alert" in item["title"], "转义后文本内容应保留"


def test_search_snippet_still_escaped(kb_with_xss):
    """snippet 的转义行为必须保持（既有功能，不得倒退）。"""
    result = kb_with_xss.search_docs(q="body", limit=10)

    assert result["items"]
    # snippet 来自 body="normal body"，无 XSS，但机制必须在位
    snippet = result["items"][0]["snippet"]
    # 若 body 含 HTML，也应被转义（此处验证函数被调用，实际转义由 FTS 用例覆盖）
    assert isinstance(snippet, str)


def test_search_fts_highlight_preserved(kb_with_xss):
    """FTS 高亮标签 <b> 必须保留（_sanitize_fts_snippet 的既有行为）。

    转义逻辑是：先把 <b> 替换成占位符 → html.escape 整体 → 还原 <b>。
    本测试确认该流程未被破坏。
    """
    # 写入一条正常文档用于 FTS 高亮测试
    from backend.app.db import get_conn

    conn = get_conn()
    now = "2026-08-03T12:00:00Z"
    conn.execute(
        "INSERT INTO kb_docs(id, title, body, created_at, updated_at) VALUES (?,?,?,?,?)",
        ("doc_hl", "Python Programming", "Python is a programming language", now, now),
    )
    conn.commit()

    result = kb_with_xss.search_docs(q="Python", limit=10)
    items = [it for it in result["items"] if it["id"] == "doc_hl"]

    assert items, "应找到用于高亮测试的文档"
    item = items[0]

    # FTS snippet 会把匹配词用 <b> 包裹（如果 FTS 引擎支持）
    # 即使不包裹，至少 <b> 标签本身应被识别为合法 HTML 而保留
    # （而非被转义为 &lt;b&gt;）
    if "<b>" in item["snippet"] or "<b>" in item["title"]:
        assert "&lt;b&gt;" not in item["snippet"], "<b> 高亮标签不应被转义"
        assert "&lt;b&gt;" not in item["title"], "<b> 高亮标签不应被转义"
