import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path


def _default_data_dir() -> Path:
    configured = os.environ.get("WANWEI_DATA_DIR")
    if configured:
        return Path(configured)

    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "wanwei-shuyi"

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / "wanwei-shuyi"
    return Path.home() / ".local" / "share" / "wanwei-shuyi"


# 03-#20: mkdir/exists/chmod 三个 syscall 按路径 once 化，不再随每次
# get_conn 重复执行。就绪集合登记在 _prepared_paths，close_all() 时随连接
# 缓存一并失效——测试在 close_all 后更换/删除 DB 文件，下一次访问会重新
# prepare，语义与旧版「每次调用都 prepare」对齐。
_prepared_paths: set[str] = set()


def _db_path() -> Path:
    # Allow tests / arena runner to point at an isolated DB via env.
    env = os.environ.get("WANWEI_MEMORY_DB")
    if env:
        p = Path(env)
    else:
        p = _default_data_dir() / "memory.db"
    key = str(p)
    with _registry_lock:
        prepared = key in _prepared_paths
    if not prepared:
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.touch(mode=0o600)
        else:
            try:
                p.chmod(0o600)
            except PermissionError:
                pass
        with _registry_lock:
            _prepared_paths.add(key)
    return p


def database_path() -> Path:
    return _db_path()


# v0.9.6 (T3): thread-local connection reuse.
#
# Rationale / boundaries:
# - FastAPI runs sync endpoints in a worker threadpool, so each thread gets its
#   own cached connection. A connection is only closed by its owner thread;
#   closing a handle from shutdown or test teardown while that thread is inside
#   SQLite can crash the interpreter instead of raising a Python exception.
#   `check_same_thread=False` is retained for compatibility, not as permission
#   to share connections between threads.
# - Tests swap the DB file via WANWEI_MEMORY_DB between cases, so the cache is
#   keyed by resolved path; a path change transparently opens a fresh handle.
# - WAL is enabled for better concurrent read/write behaviour. For a local
#   SQLite file the raw connect() cost is sub-millisecond, so reuse is a modest
#   correctness/concurrency improvement, not a headline latency win. The
#   perf report records the measured before/after honestly.
_local = threading.local()
_registry_lock = threading.Lock()
_generation = 0


def _configure(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    # WAL: concurrent readers do not block a writer; survives across connections
    # (stored in the DB header). synchronous=NORMAL is the WAL-safe fast setting.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    # Avoid spurious "database is locked" under threadpool concurrency.
    conn.execute("PRAGMA busy_timeout=5000")
    # 03-#10: 启用外键约束（soul_persona → affect_state/dream_lock 等 5 处
    # FOREIGN KEY 此前空转）。PRAGMA 为连接级设置，每个新建连接都要执行。
    conn.execute("PRAGMA foreign_keys=ON")


def _close_connections(connections: dict[str, sqlite3.Connection]) -> None:
    """Close connections owned by the calling thread."""
    for conn in connections.values():
        try:
            conn.close()
        except Exception:
            pass


def get_conn() -> sqlite3.Connection:
    global _generation

    path = str(_db_path())
    with _registry_lock:
        local_generation = getattr(_local, "generation", -1)
        if local_generation != _generation:
            stale_connections = getattr(_local, "conns", {})
            _local.conns = {}
            _local.generation = _generation
            # The generation may be advanced by another thread, but only this
            # owner thread may safely dispose of its cached SQLite handles.
            _close_connections(stale_connections)

        cache = _local.conns
        conn = cache.get(path)
        if conn is None:
            conn = sqlite3.connect(path, check_same_thread=False)
            _configure(conn)
            cache[path] = conn
        return conn


@contextmanager
def transaction(*, immediate: bool = False):
    """事务上下文：成功时 commit，异常时 rollback。

    线程本地连接复用场景下，所有写路径必须用此上下文包裹。否则一旦 DML 抛
    异常，sqlite3 模块隐式开启的事务会悬挂在连接上，污染同线程后续请求——
    下一个 commit 可能把上一个请求的部分写入提交（脏数据跨请求泄漏），或
    后续查询读到未提交的中间状态。

    用法::

        with transaction() as conn:
            conn.execute("INSERT ...", (...))
            conn.execute("INSERT ...", (...))
        # 正常退出自动 commit；异常自动 rollback 并向上抛出

    ``immediate=True`` 在 yield 前执行 ``BEGIN IMMEDIATE``，用于必须从首个
    读取开始锁定写入快照的读-改-写流程。普通模式仍沿用 sqlite3 首个 DML
    隐式开启事务的既有行为。
    """
    conn = get_conn()
    try:
        if immediate:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def close_all() -> None:
    """Invalidate all caches and close this thread's cached connections.

    Tests swap WANWEI_MEMORY_DB and unlink temp DB files between cases; calling
    this on teardown releases handles owned by the test thread. Other threads
    keep any in-flight connection alive and close it themselves when they next
    call get_conn(). This ownership rule prevents native SQLite crashes caused
    by one thread closing a handle while another thread is executing a query.
    """
    global _generation

    with _registry_lock:
        local_connections = getattr(_local, "conns", {})
        _generation += 1
        _local.conns = {}
        _local.generation = _generation
        # 路径级 prepare 缓存随连接代际一并失效：测试可能在 teardown 删除
        # DB 文件后以相同路径重建，下一次 get_conn 必须重新 mkdir/touch。
        _prepared_paths.clear()

    _close_connections(local_connections)
