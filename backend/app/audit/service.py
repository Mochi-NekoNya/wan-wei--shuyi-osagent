import secrets,json,sqlite3
from ..db import get_conn
from ..security.redaction import redact_audit_payload
from ..utils.datetime_utils import utc_now_iso


def _ensure_audit_table(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS audit_logs(audit_id TEXT PRIMARY KEY, event_type TEXT, payload TEXT, created_at TEXT)')
    conn.commit()


def record_in_transaction(conn, event_type: str, payload: dict) -> str:
    """Insert an audit row without initializing the schema or committing."""
    audit_id = 'audit_' + secrets.token_hex(6)
    safe_payload = redact_audit_payload(payload)
    conn.execute(
        'INSERT INTO audit_logs VALUES (?,?,?,?)',
        (audit_id, event_type, json.dumps(safe_payload, ensure_ascii=False), utc_now_iso()),
    )
    return audit_id


def record(event_type:str,payload:dict)->str:
    """Record audit event with sensitive data redaction."""
    conn = get_conn()
    _ensure_audit_table(conn)
    audit_id = record_in_transaction(conn, event_type, payload)
    conn.commit()
    return audit_id


def _escape_like(value: str) -> str:
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def list_logs(limit:int=50,trace_id:str|None=None)->list[dict]:
    capped=max(1,min(limit,200))
    conn=get_conn(); _ensure_audit_table(conn)
    if trace_id:
        # 03-#21: json_extract 精确匹配，替代 LIKE 脆弱匹配——旧写法依赖
        # json.dumps 的 ": " 空格格式，且 trace_id 含 %/_ 会被当成通配符，
        # 还可能误命中嵌套同名字段。
        try:
            rows=conn.execute(
                "SELECT * FROM audit_logs WHERE json_extract(payload,'$.trace_id')=? "
                "ORDER BY created_at DESC LIMIT ?",
                (trace_id,capped),
            ).fetchall()
        except sqlite3.OperationalError:
            # JSON1 不可用的旧 SQLite 构建回退原 LIKE 语义（兼容性兜底）。
            # ESCAPE 子句的转义符必须是带引号的字符字面量：Python 源码中的
            # '\\' 在 SQL 里是 '\'，缺引号会让兜底查询本身语法错误直接 500。
            rows=conn.execute(
                "SELECT * FROM audit_logs WHERE payload LIKE ? ESCAPE '\\' ORDER BY created_at DESC LIMIT ?",
                (f'%"trace_id": "{_escape_like(trace_id)}"%',capped),
            ).fetchall()
    else:
        rows=conn.execute('SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT ?',(capped,)).fetchall()
    return [dict(r) for r in rows]
