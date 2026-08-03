"""
FIX-19（04-#08）：knowledge search 结果 title HTML 转义回归测试。

背景
----
`GET /knowledge/search` 返回的 `items[].snippet` 经过 `_sanitize_fts_snippet`
做了 HTML 转义（防 XSS），但 `title` 只经过 `_compact_cjk_snippet`（压缩空格），
未转义。若前端用 `innerHTML` 渲染 title，含 `<script>` 的标题即存储型 XSS。

修复：title 通过 `_escape_search_title` 完整转义；snippet 通过
`_sanitize_fts_snippet` 仅保留 FTS 生成的高亮标记。
"""

import pytest


@pytest.fixture()
def kb_with_xss(isolated_db):
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
    item = next(item for item in result["items"] if item["id"] == "doc_xss")

    # 原始 <script> 标签必须被转义为 &lt;script&gt;
    assert "<script>" not in item["title"], "修复失败：<script> 标签未被转义"
    assert "&lt;script&gt;" in item["title"], "转义后应含 &lt;script&gt;"
    assert "alert" in item["title"], "转义后文本内容应保留"


def test_latest_titles_are_html_escaped(kb_with_xss):
    """空查询的最新文档路径也必须遵守相同的输出边界。"""
    result = kb_with_xss.search_docs(q="", limit=10)

    item = next(item for item in result["items"] if item["id"] == "doc_xss")
    assert "<script>" not in item["title"]
    assert "&lt;script&gt;" in item["title"]


def test_search_snippet_still_escaped(kb_with_xss):
    """snippet 的转义行为必须保持（既有功能，不得倒退）。"""
    from backend.app.db import get_conn

    conn = get_conn()
    now = "2026-08-03T12:00:00Z"
    conn.execute(
        "INSERT INTO kb_docs(id, title, body, created_at, updated_at) VALUES (?,?,?,?,?)",
        (
            "doc_body_xss",
            "Snippet safety",
            "unique_snippet_marker <img src=x onerror=alert(1)>",
            now,
            now,
        ),
    )
    conn.commit()

    result = kb_with_xss.search_docs(q="unique_snippet_marker", limit=10)

    item = next(item for item in result["items"] if item["id"] == "doc_body_xss")
    assert "<img" not in item["snippet"]
    assert "&lt;img" in item["snippet"]


def test_fts_highlight_preserved_while_raw_html_is_escaped(kb_with_xss):
    """高亮标记必须保留，紧邻的原始 HTML 必须转义。"""
    sanitized = kb_with_xss._sanitize_fts_snippet(
        "<b>Python</b><script>alert(1)</script>"
    )

    assert sanitized == (
        "<b>Python</b>&lt;script&gt;alert(1)&lt;/script&gt;"
    )


def test_title_does_not_preserve_user_supplied_highlight_tags(kb_with_xss):
    """标题不是 FTS snippet，用户写入的 <b> 也必须作为文本转义。"""
    assert kb_with_xss._escape_search_title("<b>title</b>") == (
        "&lt;b&gt;title&lt;/b&gt;"
    )
