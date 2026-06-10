"""
backend/src/db/sqlserver.py
============================
SQL Server connection + schema init + CRUD helpers for flight data.
"""
import os
import time
import logging
import pandas as pd
import pyodbc
import re
import queue
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _validate_identifier(name: str) -> str:
    """Validate a SQL identifier (database/table name) to prevent SQL injection."""
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
        raise ValueError(f"Invalid SQL identifier: {name}")
    return name


_DRIVER = "ODBC Driver 18 for SQL Server"
try:
    _installed_drivers = pyodbc.drivers()
    for _d in ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server"]:
        if _d in _installed_drivers:
            _DRIVER = _d
            break
except Exception:
    pass


def _get_conn_str(server: str, database: str, user: str, password: str) -> str:
    return (
        f"DRIVER={{{_DRIVER}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        "TrustServerCertificate=yes;"
        "Encrypt=no;"
    )

class PyodbcConnectionPool:
    def __init__(self, max_size: int = 15):
        self.max_size = max_size
        self.pool = queue.Queue(maxsize=max_size)
        
    def get_connection(self) -> pyodbc.Connection:
        try:
            conn = self.pool.get_nowait()
            # Test connection
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
                return conn
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                return self._create_new()
        except queue.Empty:
            return self._create_new()
            
    def release_connection(self, conn: pyodbc.Connection):
        if conn is None:
            return
        try:
            self.pool.put_nowait(conn)
        except queue.Full:
            try:
                conn.close()
            except Exception:
                pass

    def _create_new(self, retries: int = 5, delay: float = 2.0) -> pyodbc.Connection:
        server   = os.getenv("DB_SERVER",   "localhost")
        database = os.getenv("DB_NAME",     "airline_db")
        user     = os.getenv("DB_USER",     "sa")
        password = os.getenv("DB_PASSWORD") or os.getenv("MSSQL_SA_PASSWORD")
        if not password:
            raise ValueError("DB_PASSWORD or MSSQL_SA_PASSWORD environment variable is not set!")
        
        conn_str = _get_conn_str(server, database, user, password)
        
        for attempt in range(1, retries + 1):
            try:
                conn = pyodbc.connect(conn_str, timeout=10)
                conn.autocommit = True
                logger.info(f"[db] Connected to SQL Server {server}/{database} (pooled)")
                return conn
            except pyodbc.Error as ex:
                logger.warning(f"[db] Connection attempt {attempt}/{retries} failed: {ex}")
                if attempt == retries:
                    raise
                time.sleep(delay)

class PooledConnectionProxy:
    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool
        
    def __getattr__(self, name):
        return getattr(self._conn, name)
        
    def close(self):
        if self._conn is not None:
            self._pool.release_connection(self._conn)
            self._conn = None
            
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

_DB_POOL = PyodbcConnectionPool(max_size=15)

def _connect() -> pyodbc.Connection:
    conn = _DB_POOL.get_connection()
    return PooledConnectionProxy(conn, _DB_POOL)

def init_db():
    """
    Ensures the airline_db database and flights table exist.
    Safe to call multiple times.
    """
    # First connect to master to create the database if needed
    server   = os.getenv("DB_SERVER",   "localhost")
    database = os.getenv("DB_NAME",     "airline_db")
    user     = os.getenv("DB_USER",     "sa")
    password = os.getenv("DB_PASSWORD") or os.getenv("MSSQL_SA_PASSWORD")
    if not password:
        raise ValueError("DB_PASSWORD or MSSQL_SA_PASSWORD environment variable is not set!")

    master_conn_str = _get_conn_str(server, "master", user, password)
    try:
        with pyodbc.connect(master_conn_str, timeout=10) as conn:
            conn.autocommit = True
            cursor = conn.cursor()
            safe_db = _validate_identifier(database)
            cursor.execute(f"IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = N'{safe_db}') CREATE DATABASE [{safe_db}]")
            cursor.execute(f"USE [{safe_db}]")
            logger.info(f"[db] Database '{database}' ready")
    except pyodbc.Error as ex:
        logger.error(f"[db] Failed to create database: {ex}")
        raise ex

    # Now create the flights table
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute("""
    IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = N'flights' AND type = N'U')
    CREATE TABLE flights (
        id                    BIGINT IDENTITY(1,1) PRIMARY KEY,
        flight_no             NVARCHAR(20)  NULL,
        flight_date           DATE          NOT NULL,
        str_Dep               NVARCHAR(10)  NOT NULL,
        str_Arr               NVARCHAR(10)  NOT NULL,
        str_Fare_Category     NVARCHAR(10)  NOT NULL DEFAULT 'N/A',
        route                 AS (str_Dep + '-' + str_Arr) PERSISTED,
        mny_GL_Charges_Total  FLOAT         NOT NULL,
        LF_by_date            FLOAT         NOT NULL,
        LF_by_fare            FLOAT         NULL,
        lead_time_days        INT           NULL,
        booking_velocity_3d   FLOAT         NULL,
        booking_velocity_7d   FLOAT         NULL,
        Weekday               INT           NULL,
        IsHoliday             INT           DEFAULT 0,
        is_oneway             INT           DEFAULT 1,
        lng_Capacity          INT           DEFAULT 230,
        lng_Seats             INT           DEFAULT 1,
        count_sked            INT           DEFAULT 1,
        fare_family           NVARCHAR(20)  NULL,
        lng_fuel              FLOAT         NULL,
        created_at            DATETIME      DEFAULT GETDATE(),
        updated_at            DATETIME      DEFAULT GETDATE(),
    );
    """)
    cursor.execute("""
    IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = N'IX_flights_route')
    CREATE INDEX IX_flights_route ON flights(route);
    """)
    cursor.execute("""
    IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = N'IX_flights_flight_date')
    CREATE INDEX IX_flights_flight_date ON flights(flight_date);
    """)
    
    # Create chat history tables
    cursor.execute("""
    IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = N'chat_sessions' AND type = N'U')
    CREATE TABLE chat_sessions (
        id BIGINT IDENTITY(1,1) PRIMARY KEY,
        title NVARCHAR(255) NOT NULL DEFAULT N'Cuộc trò chuyện mới',
        created_at DATETIME DEFAULT GETDATE(),
        updated_at DATETIME DEFAULT GETDATE()
    );
    """)
    cursor.execute("""
    IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = N'chat_messages' AND type = N'U')
    CREATE TABLE chat_messages (
        id BIGINT IDENTITY(1,1) PRIMARY KEY,
        session_id BIGINT FOREIGN KEY REFERENCES chat_sessions(id) ON DELETE CASCADE,
        role NVARCHAR(20) NOT NULL,
        content NVARCHAR(MAX) NOT NULL,
        thinking NVARCHAR(MAX) NULL,
        tools_called NVARCHAR(MAX) NULL,
        action NVARCHAR(MAX) NULL,
        created_at DATETIME DEFAULT GETDATE()
    );
    """)
    
    # autocommit=True on connection handles commits
    cursor.close()
    conn.close()
    logger.info("[db] Tables flights, chat_sessions, chat_messages ready")

def load_flights(
    route: str | None = None,
    dep: str | None = None,
    arr: str | None = None,
    flight_date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    flight_no: str | None = None,
    fare_family: str | None = None,
    sort_by: str = "flight_date",
    sort_dir: str = "asc",
    page: int = 1,
    page_size: int = 100,
) -> pd.DataFrame:
    """
    Query flights with optional filters and pagination.
    """
    conn = _connect()
    cursor = conn.cursor()

    where_clauses = []
    params: list = []

    if route:
        where_clauses.append("(str_Dep = ? OR str_Arr = ? OR route = ?)")
        params.extend([route, route, route])

    if dep:
        where_clauses.append("str_Dep = ?")
        params.append(dep)

    if arr:
        where_clauses.append("str_Arr = ?")
        params.append(arr)

    if flight_date:
        where_clauses.append("flight_date = ?")
        params.append(flight_date)
    elif date_from:
        where_clauses.append("flight_date >= ?")
        params.append(date_from)

    if date_to:
        where_clauses.append("flight_date <= ?")
        params.append(date_to)

    if flight_no:
        where_clauses.append("flight_no LIKE ?")
        params.append(f"%{flight_no}%")

    if fare_family:
        where_clauses.append("fare_family = ?")
        params.append(fare_family)

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    allowed_sorts = {
        "flight_date": "flight_date",
        "price":      "mny_GL_Charges_Total",
        "lf":         "LF_by_date",
        "route":      "route",
        "flight_no":  "flight_no",
    }
    order_col = allowed_sorts.get(sort_by, "flight_date")
    order_dir = "DESC" if sort_dir.lower() == "desc" else "ASC"

    offset = (page - 1) * page_size

    query = f"""
    SELECT
        id, flight_no, flight_date, str_Dep, str_Arr, str_Fare_Category, route,
        mny_GL_Charges_Total AS price,
        LF_by_date AS lf,
        LF_by_fare, lead_time_days,
        booking_velocity_3d, booking_velocity_7d,
        Weekday, IsHoliday, is_oneway,
        lng_Capacity, lng_Seats,
        lng_fuel, count_sked,
        fare_family
    FROM flights
    WHERE {where_sql}
    ORDER BY {order_col} {order_dir}, id ASC
    OFFSET {offset} ROWS FETCH NEXT {page_size} ROWS ONLY
    """

    try:
        rows = pd.read_sql(query, conn, params=params)
    except Exception:
        cursor.close()
        conn.close()
        raise
    cursor.close()
    conn.close()
    return rows


def count_flights(
    route: str | None = None,
    dep: str | None = None,
    arr: str | None = None,
    flight_date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    flight_no: str | None = None,
    fare_family: str | None = None,
) -> int:
    """
    Count total flights matching filters (for pagination).
    """
    try:
        conn = _connect()
        where_clauses = []
        params: list = []

        if route:
            where_clauses.append("(str_Dep = ? OR str_Arr = ? OR route = ?)")
            params.extend([route, route, route])

        if dep:
            where_clauses.append("str_Dep = ?")
            params.append(dep)

        if arr:
            where_clauses.append("str_Arr = ?")
            params.append(arr)

        if flight_date:
            where_clauses.append("flight_date = ?")
            params.append(flight_date)
        elif date_from:
            where_clauses.append("flight_date >= ?")
            params.append(date_from)

        if date_to:
            where_clauses.append("flight_date <= ?")
            params.append(date_to)

        if flight_no:
            where_clauses.append("flight_no LIKE ?")
            params.append(f"%{flight_no}%")

        if fare_family:
            where_clauses.append("fare_family = ?")
            params.append(fare_family)

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM flights WHERE {where_sql}", params)
        total = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return int(total)
    except Exception as ex:
        logger.error(f"[db] count_flights failed: {ex}")
        return 0


def upsert_flights(df: pd.DataFrame) -> dict:
    """
    Insert only truly new flight records from a DataFrame (deduplicate across files).
    Strategy:
      1. Bulk-insert all rows into a #temp staging table (fast, minimal round-trips)
      2. LEFT JOIN staging with flights to find unmatched rows
      3. INSERT only the unmatched rows (no UPDATE, no duplicate rows)
    Returns {"inserted": N, "updated": 0}.
    """
    if df.empty:
        logger.warning("[db] upsert_flights called with empty DataFrame")
        return {"inserted": 0, "updated": 0}

    logger.info(f"[db] upsert_flights: {len(df)} rows")

    # ── Normalize column names ──────────────────────────────────────────────────
    rename = {
        "dep":                        "str_Dep",
        "arr":                        "str_Arr",
        "price":                      "mny_GL_Charges_Total",
        "lf":                         "LF_by_date",
        "lf_fare":                    "LF_by_fare",
        "fuel_price":                 "lng_fuel",
        "str_Fare_Class_Short":       "str_Fare_Category",
        "str_Fare_Family_Ident":      "fare_family",
        "str_Fare_Category_Ident":    "str_Fare_Category",
    }
    df = df.rename(columns=rename)
    # Defend against duplicate column names (keep first occurrence only)
    df = df.loc[:, ~df.columns.duplicated()]
    logger.info(f"[db] After rename: {len(df)} rows, columns: {list(df.columns)}")

    # ── Extract flight_date ──────────────────────────────────────────────────────
    if "dtm_Local_ETD_Date" in df.columns:
        df["flight_date"] = pd.to_datetime(df["dtm_Local_ETD_Date"], errors="coerce").dt.date
        logger.info(f"[db] flight_date from dtm_Local_ETD_Date: {df['flight_date'].nunique()} unique dates")
    elif "dtm_Creation_Date" in df.columns:
        df["flight_date"] = pd.to_datetime(df["dtm_Creation_Date"], errors="coerce").dt.date
        logger.info(f"[db] flight_date from dtm_Creation_Date: {df['flight_date'].nunique()} unique dates")
    else:
        df["flight_date"] = pd.Timestamp.today().date()
        logger.warning("[db] No date column found, using today")
    print(f"[db] Date range: {df['flight_date'].min()} to {df['flight_date'].max()}")

    # ── Deduplicate: keep row with highest LF_by_date per (str_Dep, str_Arr, flight_date, fare_family) ──
    lf_col = "LF_by_date"
    if lf_col not in df.columns:
        df[lf_col] = 0.0
    df[lf_col] = pd.to_numeric(df[lf_col], errors="coerce").fillna(0)

    # Normalize fare_family for grouping
    if "fare_family" in df.columns:
        df["fare_family"] = df["fare_family"].fillna("N/A").astype(str).str.strip().str[:20]
    else:
        df["fare_family"] = "N/A"

    logger.info(f"[db] Before dedup: {len(df)} rows, unique keys: {df.groupby(['str_Dep', 'str_Arr', 'flight_date', 'fare_family']).ngroups}")
    
    # Group by key columns and keep row with highest LF_by_date per fare_family
    df = (
        df.sort_values(lf_col, ascending=False)
          .drop_duplicates(subset=["str_Dep", "str_Arr", "flight_date", "fare_family"], keep="first")
          .sort_index()
    )
    logger.info(f"[db] After dedup by (str_Dep, str_Arr, flight_date, fare_family): {len(df)} rows")

    # ── Build rows list ─────────────────────────────────────────────────────────
    rows = []
    skipped = 0
    for _, row in df.iterrows():
        str_dep = str(row.get("str_Dep", ""))[:10]
        str_arr = str(row.get("str_Arr", ""))[:10]
        if not str_dep or not str_arr:
            skipped += 1
            continue

        rows.append((
            _to_python(str(row.get("flight_no", "") or "")[:20] or None),
            _to_date(row.get("flight_date")),
            _to_python(str_dep),
            _to_python(str_arr),
            _to_python(str(row.get("str_Fare_Category", "") or "") or None),
            _to_python(float(row.get("mny_GL_Charges_Total", 0))),
            _to_python(float(row.get("LF_by_date", 0))),
            _to_python(float(row["LF_by_fare"]) if pd.notna(row.get("LF_by_fare")) else None),
            _to_python(int(row["lead_time_days"]) if pd.notna(row.get("lead_time_days")) else None),
            _to_python(float(row["booking_velocity_3d"]) if pd.notna(row.get("booking_velocity_3d")) else None),
            _to_python(float(row["booking_velocity_7d"]) if pd.notna(row.get("booking_velocity_7d")) else None),
            _to_python(int(row["Weekday"]) if pd.notna(row.get("Weekday")) else None),
            _to_python(int(row.get("IsHoliday", 0))),
            _to_python(int(row.get("is_oneway", 1))),
            _to_python(int(row.get("lng_Capacity", 230))),
            _to_python(int(row.get("lng_Seats", 1)) if pd.notna(row.get("lng_Seats")) else 1),
            _to_python(int(row.get("count_sked", 1))),
            _to_python(str(row["fare_family"])[:20] if pd.notna(row.get("fare_family")) else None),
            _to_python(float(row["lng_fuel"]) if pd.notna(row.get("lng_fuel")) else None),
        ))

    if skipped:
        logger.warning(f"[db] Skipped {skipped} rows due to missing str_Dep or str_Arr")
    if not rows:
        return {"inserted": 0, "updated": 0}

    conn = _connect()
    cursor = conn.cursor()
    BATCH_SIZE = 1000
    total_inserted = 0
    total_updated = 0

    INSERT_COLS = (
        "flight_no, flight_date, str_Dep, str_Arr, str_Fare_Category, "
        "mny_GL_Charges_Total, LF_by_date, LF_by_fare, "
        "lead_time_days, booking_velocity_3d, booking_velocity_7d, "
        "Weekday, IsHoliday, is_oneway, "
        "lng_Capacity, lng_Seats, count_sked, "
        "fare_family, lng_fuel"
    )
    N_COLS = 19
    placeholders = ", ".join(["?" for _ in range(N_COLS)])

    for batch_start in range(0, len(rows), BATCH_SIZE):
        batch = rows[batch_start : batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1

        # Step 1: Create temp staging table
        cursor.execute("DROP TABLE IF EXISTS #flight_staging")
        cursor.execute(f"""
            CREATE TABLE #flight_staging (
                flight_no            NVARCHAR(20),
                flight_date          DATE,
                str_Dep              NVARCHAR(10),
                str_Arr              NVARCHAR(10),
                str_Fare_Category    NVARCHAR(10),
                mny_GL_Charges_Total FLOAT,
                LF_by_date           FLOAT,
                LF_by_fare           FLOAT,
                lead_time_days       INT,
                booking_velocity_3d  FLOAT,
                booking_velocity_7d  FLOAT,
                Weekday              INT,
                IsHoliday            INT,
                is_oneway            INT,
                lng_Capacity         INT,
                lng_Seats            INT,
                count_sked           INT,
                fare_family          NVARCHAR(20),
                lng_fuel             FLOAT
            )
        """)

        # Step 2: Bulk-insert into staging using named parameters
        insert_stage_sql = f"INSERT INTO #flight_staging ({INSERT_COLS}) VALUES ({placeholders})"
        for row in batch:
            cursor.execute(insert_stage_sql, tuple(row))

        # Step 3: Debug — sample keys from staging vs existing DB
        cursor.execute("""
            SELECT TOP 3 str_Dep, str_Arr, flight_date, ISNULL(fare_family, 'N/A') AS fare_family
            FROM #flight_staging ORDER BY 1, 2
        """)
        staging_sample = cursor.fetchall()
        logger.info(f"[db] Staging sample keys: {staging_sample}")

        cursor.execute("""
            SELECT TOP 3 str_Dep, str_Arr, flight_date, ISNULL(fare_family, 'N/A') AS fare_family
            FROM flights ORDER BY 1, 2
        """)
        db_sample = cursor.fetchall()
        logger.info(f"[db] DB sample keys: {db_sample}")

        # Count how many staging rows have a match in flights
        cursor.execute("""
            SELECT COUNT(*)
            FROM #flight_staging s
            INNER JOIN flights f
              ON f.str_Dep = s.str_Dep
             AND f.str_Arr = s.str_Arr
             AND f.flight_date = s.flight_date
             AND ISNULL(f.fare_family, 'N/A') = ISNULL(s.fare_family, 'N/A')
        """)
        matched = cursor.fetchone()[0]
        logger.info(f"[db] Staging rows matched in DB: {matched} / {len(batch)}")

        # Step 4: UPDATE matching rows with the latest uploaded details
        cursor.execute("""
            UPDATE f
            SET f.flight_no = s.flight_no,
                f.str_Fare_Category = s.str_Fare_Category,
                f.mny_GL_Charges_Total = s.mny_GL_Charges_Total,
                f.LF_by_date = s.LF_by_date,
                f.LF_by_fare = s.LF_by_fare,
                f.lead_time_days = s.lead_time_days,
                f.booking_velocity_3d = s.booking_velocity_3d,
                f.booking_velocity_7d = s.booking_velocity_7d,
                f.Weekday = s.Weekday,
                f.IsHoliday = s.IsHoliday,
                f.is_oneway = s.is_oneway,
                f.lng_Capacity = s.lng_Capacity,
                f.lng_Seats = s.lng_Seats,
                f.count_sked = s.count_sked,
                f.lng_fuel = s.lng_fuel,
                f.updated_at = GETDATE()
            FROM flights f
            INNER JOIN #flight_staging s
              ON f.str_Dep = s.str_Dep
             AND f.str_Arr = s.str_Arr
             AND f.flight_date = s.flight_date
             AND ISNULL(f.fare_family, 'N/A') = ISNULL(s.fare_family, 'N/A')
        """)
        batch_updated = cursor.rowcount
        total_updated += batch_updated

        # Step 5: INSERT only new rows — skip rows already in flights (deduplicate across files via LEFT JOIN)
        cursor.execute(f"""
            INSERT INTO flights ({INSERT_COLS})
            SELECT s.flight_no, s.flight_date, s.str_Dep, s.str_Arr, s.str_Fare_Category,
                   s.mny_GL_Charges_Total, s.LF_by_date, s.LF_by_fare,
                   s.lead_time_days, s.booking_velocity_3d, s.booking_velocity_7d,
                   s.Weekday, s.IsHoliday, s.is_oneway,
                   s.lng_Capacity, s.lng_Seats, s.count_sked,
                   s.fare_family, s.lng_fuel
            FROM #flight_staging s
            LEFT JOIN flights f
              ON f.str_Dep = s.str_Dep
             AND f.str_Arr = s.str_Arr
             AND f.flight_date = s.flight_date
             AND ISNULL(f.fare_family, 'N/A') = ISNULL(s.fare_family, 'N/A')
            WHERE f.id IS NULL
        """)
        batch_inserted = cursor.rowcount
        total_inserted += batch_inserted

        # Cleanup
        cursor.execute("DROP TABLE IF EXISTS #flight_staging")
        logger.info(
            f"[db] Batch {batch_num}: {batch_inserted} inserted, {batch_updated} updated "
            f"(total inserted: {total_inserted}, total updated: {total_updated})"
        )

    conn.commit()
    cursor.close()
    conn.close()
    logger.info(f"[db] upsert_flights complete: {total_inserted} inserted, {total_updated} updated")
    return {"inserted": total_inserted, "updated": total_updated}


def _scalar(val):
    """Extract scalar from value; handle Series (duplicate columns), None, etc."""
    if val is None or isinstance(val, (bool, int, float, str)):
        return val
    if isinstance(val, pd.Series):
        return val.iloc[0] if len(val) > 0 else None
    if hasattr(val, "item"):
        return val.item()
    return val


def _to_python(val):
    """Convert numpy/pandas types to native Python for safe ODBC parameter binding."""
    if val is None:
        return None
    if isinstance(val, (bool, int, float, str)):
        return val
    # numpy types
    if hasattr(val, "item"):
        try:
            return val.item()
        except Exception:
            pass
    if hasattr(val, "astype"):
        try:
            return val.astype("U").item() if hasattr(val, "astype") else str(val)
        except Exception:
            pass
    return str(val)


def _to_date(val) -> str:
    """Convert a date-like value to YYYY-MM-DD string."""
    val = _scalar(val)
    if val is None:
        return pd.Timestamp.today().strftime("%Y-%m-%d")
    try:
        return pd.to_datetime(val).strftime("%Y-%m-%d")
    except Exception:
        return pd.Timestamp.today().strftime("%Y-%m-%d")


def get_routes(flight_date: str | None = None, dep: str | None = None, arr: str | None = None) -> list[dict]:
    """Return aggregated route stats from the DB. Returns empty list if DB is empty.
    
    Args:
        flight_date: Optional YYYY-MM-DD string to filter by specific date.
        dep: Optional departure airport code.
        arr: Optional arrival airport code.
    """
    try:
        conn = _connect()
        where_clauses = []
        params = []
        
        if flight_date:
            where_clauses.append("CAST(flight_date AS DATE) = ?")
            params.append(flight_date)
        if dep:
            where_clauses.append("str_Dep = ?")
            params.append(dep)
        if arr:
            where_clauses.append("str_Arr = ?")
            params.append(arr)
        
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        
        rows = pd.read_sql(f"""
            SELECT
                route,
                str_Dep,
                str_Arr,
                COUNT(*) AS count,
                AVG(mny_GL_Charges_Total) AS avg_price,
                AVG(LF_by_date) AS avg_lf,
                MIN(mny_GL_Charges_Total) AS min_price,
                MAX(mny_GL_Charges_Total) AS max_price
            FROM flights
            WHERE {where_sql}
            GROUP BY route, str_Dep, str_Arr
            ORDER BY count DESC
            """, conn, params=params)
        conn.close()
        return rows.to_dict(orient="records")
    except Exception:
        return []


def get_distinct_routes() -> list[dict]:
    """Return all distinct routes from the DB."""
    try:
        conn = _connect()
        rows = pd.read_sql(
            "SELECT route, str_Dep, str_Arr FROM flights GROUP BY route, str_Dep, str_Arr ORDER BY route",
            conn
        )
        conn.close()
        return rows.to_dict(orient="records")
    except Exception:
        return []


def get_distinct_airports() -> dict:
    """Return distinct departure and arrival airports."""
    try:
        conn = _connect()
        dep_rows = pd.read_sql(
            "SELECT DISTINCT str_Dep FROM flights WHERE str_Dep IS NOT NULL ORDER BY str_Dep",
            conn
        )
        arr_rows = pd.read_sql(
            "SELECT DISTINCT str_Arr FROM flights WHERE str_Arr IS NOT NULL ORDER BY str_Arr",
            conn
        )
        conn.close()
        return {
            "departures": dep_rows["str_Dep"].tolist(),
            "arrivals": arr_rows["str_Arr"].tolist(),
        }
    except Exception:
        return {"departures": [], "arrivals": []}


def load_flight_by_id(flight_id: int) -> dict | None:
    """Load a single flight by its DB id."""
    try:
        conn = _connect()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                id, flight_no, flight_date, str_Dep, str_Arr, str_Fare_Category, route,
                mny_GL_Charges_Total AS price,
                LF_by_date AS lf,
                LF_by_fare, lead_time_days,
                booking_velocity_3d, booking_velocity_7d,
                Weekday, IsHoliday, is_oneway,
                lng_Capacity, lng_Seats,
                lng_fuel, count_sked,
                fare_family
            FROM flights
            WHERE id = ?
        """, (flight_id,))
        row = cursor.fetchone()
        cols = [d[0] for d in cursor.description]
        cursor.close()
        conn.close()
        if row is None:
            return None
        return dict(zip(cols, row))
    except Exception as ex:
        logger.error(f"[db] load_flight_by_id failed: {ex}")
        return None


def load_flights_by_date(date: str, limit: int = 100) -> pd.DataFrame:
    """Load flights for a specific date, fallback to top N recent flights."""
    try:
        conn = _connect()
        limit = int(limit)  # Ensure limit is integer to prevent SQL injection
        df = pd.read_sql(f"""
            SELECT TOP {limit}
                id, flight_no, flight_date, str_Dep, str_Arr, str_Fare_Category, route,
                mny_GL_Charges_Total AS price,
                LF_by_date AS lf,
                LF_by_fare, lead_time_days,
                booking_velocity_3d, booking_velocity_7d,
                Weekday, IsHoliday, is_oneway,
                lng_Capacity, lng_Seats,
                lng_fuel, count_sked,
                fare_family
            FROM flights
            WHERE flight_date = ?
            ORDER BY flight_date DESC
        """, conn, params=[date])
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


def load_recent_flights(limit: int = 100) -> pd.DataFrame:
    """Load most recent flights when no date match found."""
    try:
        conn = _connect()
        limit = int(limit)  # Ensure limit is integer to prevent SQL injection
        df = pd.read_sql(f"""
            SELECT TOP {limit}
                id, flight_no, flight_date, str_Dep, str_Arr, str_Fare_Category, route,
                mny_GL_Charges_Total AS price,
                LF_by_date AS lf,
                LF_by_fare, lead_time_days,
                booking_velocity_3d, booking_velocity_7d,
                Weekday, IsHoliday, is_oneway,
                lng_Capacity, lng_Seats,
                lng_fuel, count_sked,
                fare_family
            FROM flights
            ORDER BY flight_date DESC
        """, conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


def update_flight_price(flight_id: int, new_price: float) -> bool:
    """Update price for a single flight."""
    try:
        conn = _connect()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE flights
            SET mny_GL_Charges_Total = ?, updated_at = GETDATE()
            WHERE id = ?
        """, (new_price, flight_id))
        conn.commit()
        affected = cursor.rowcount
        cursor.close()
        conn.close()
        return affected > 0
    except Exception as ex:
        logger.error(f"[db] update_flight_price failed: {ex}")
        return False


def update_flight_price_and_lf(flight_id: int, new_price: float, new_lf: float) -> bool:
    """Update price and load factor for a single flight."""
    try:
        conn = _connect()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE flights
            SET mny_GL_Charges_Total = ?, LF_by_date = ?, LF_by_fare = ?, updated_at = GETDATE()
            WHERE id = ?
        """, (new_price, new_lf, new_lf, flight_id))
        conn.commit()
        affected = cursor.rowcount
        cursor.close()
        conn.close()
        return affected > 0
    except Exception as ex:
        logger.error(f"[db] update_flight_price_and_lf failed: {ex}")
        return False


def bulk_update_flight_prices(updates: list[dict]) -> dict:
    """
    Bulk update flight prices. updates = [{"id": int, "price": float}, ...]
    Returns {"updated": N, "failed": M}.
    """
    updated = 0
    failed = 0
    if not updates:
        return {"updated": 0, "failed": 0}
        
    conn = _connect()
    cursor = conn.cursor()
    try:
        for item in updates:
            try:
                fid = int(item["id"])
                price = float(item["price"])
                cursor.execute("""
                    UPDATE flights
                    SET mny_GL_Charges_Total = ?, updated_at = GETDATE()
                    WHERE id = ?
                """, (price, fid))
                if cursor.rowcount > 0:
                    updated += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
        conn.commit()
    except Exception as ex:
        logger.error(f"[db] bulk_update_flight_prices failed: {ex}")
        failed += len(updates) - updated
    finally:
        cursor.close()
        conn.close()
    return {"updated": updated, "failed": failed}


import json as _json

def create_chat_session(title: str = "Cuộc trò chuyện mới") -> int:
    """Create a new chat session and return its ID."""
    try:
        conn = _connect()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO chat_sessions (title, created_at, updated_at)
            OUTPUT INSERTED.id
            VALUES (?, GETDATE(), GETDATE());
        """, (title,))
        session_id = int(cursor.fetchone()[0])
        cursor.close()
        conn.close()
        return session_id
    except Exception as ex:
        logger.error(f"[db] create_chat_session failed: {ex}")
        raise

def get_chat_sessions() -> list[dict]:
    """Retrieve all chat sessions sorted by updated_at descending."""
    try:
        conn = _connect()
        df = pd.read_sql("""
            SELECT id, title, created_at, updated_at
            FROM chat_sessions
            ORDER BY updated_at DESC
        """, conn)
        conn.close()
        # Convert datetime columns to ISO strings
        for col in ["created_at", "updated_at"]:
            if col in df.columns:
                df[col] = df[col].astype(str)
        return df.to_dict(orient="records")
    except Exception as ex:
        logger.error(f"[db] get_chat_sessions failed: {ex}")
        return []

def get_chat_messages(session_id: int) -> list[dict]:
    """Retrieve all messages for a chat session sorted by created_at ascending."""
    try:
        conn = _connect()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, session_id, role, content, thinking, tools_called, action, created_at
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY created_at ASC
        """, (session_id,))
        rows = cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        cursor.close()
        conn.close()

        messages = []
        for r in rows:
            data = dict(zip(cols, r))
            if "created_at" in data and hasattr(data["created_at"], "isoformat"):
                data["created_at"] = data["created_at"].isoformat()
            
            # Deserialize JSON fields
            if data.get("tools_called"):
                try:
                    data["tools_called"] = _json.loads(data["tools_called"])
                except Exception:
                    data["tools_called"] = []
            else:
                data["tools_called"] = []

            if data.get("action"):
                try:
                    data["action"] = _json.loads(data["action"])
                except Exception:
                    data["action"] = None
            else:
                data["action"] = None

            messages.append(data)
        return messages
    except Exception as ex:
        logger.error(f"[db] get_chat_messages failed: {ex}")
        return []

def save_chat_message(session_id: int, role: str, content: str, thinking: str = None, tools_called: list = None, action: dict = None) -> None:
    """Save a chat message and update the session's updated_at timestamp."""
    try:
        tools_str = _json.dumps(tools_called, ensure_ascii=False) if tools_called else None
        action_str = _json.dumps(action, ensure_ascii=False) if action else None
        
        conn = _connect()
        cursor = conn.cursor()
        # Insert message
        cursor.execute("""
            INSERT INTO chat_messages (session_id, role, content, thinking, tools_called, action, created_at)
            VALUES (?, ?, ?, ?, ?, ?, GETDATE());
        """, (session_id, role, content, thinking, tools_str, action_str))
        
        # Update session timestamp
        cursor.execute("""
            UPDATE chat_sessions
            SET updated_at = GETDATE()
            WHERE id = ?;
        """, (session_id,))
        
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as ex:
        logger.error(f"[db] save_chat_message failed: {ex}")
        raise

def delete_chat_session(session_id: int) -> bool:
    """Delete a chat session (cascades to delete all its messages)."""
    try:
        conn = _connect()
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM chat_sessions
            WHERE id = ?;
        """, (session_id,))
        conn.commit()
        affected = cursor.rowcount
        cursor.close()
        conn.close()
        return affected > 0
    except Exception as ex:
        logger.error(f"[db] delete_chat_session failed: {ex}")
        return False

def rename_chat_session(session_id: int, title: str) -> bool:
    """Rename a chat session and update its timestamp."""
    try:
        conn = _connect()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE chat_sessions
            SET title = ?, updated_at = GETDATE()
            WHERE id = ?;
        """, (title, session_id))
        conn.commit()
        affected = cursor.rowcount
        cursor.close()
        conn.close()
        return affected > 0
    except Exception as ex:
        logger.error(f"[db] rename_chat_session failed: {ex}")
        return False


def bulk_update_flight_details(updates: list[dict]) -> dict:
    """
    Bulk update flight details (price & load factor). updates = [{"id": int, "price": float, "lf": float}, ...]
    Returns {"updated": N, "failed": M}.
    """
    updated = 0
    failed = 0
    if not updates:
        return {"updated": 0, "failed": 0}
        
    conn = _connect()
    cursor = conn.cursor()
    try:
        for item in updates:
            try:
                fid = int(item["id"])
                price = float(item["price"])
                lf = float(item["lf"])
                cursor.execute("""
                    UPDATE flights
                    SET mny_GL_Charges_Total = ?, LF_by_date = ?, LF_by_fare = ?, updated_at = GETDATE()
                    WHERE id = ?
                """, (price, lf, lf, fid))
                if cursor.rowcount > 0:
                    updated += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
        conn.commit()
    except Exception as ex:
        logger.error(f"[db] bulk_update_flight_details failed: {ex}")
        failed += len(updates) - updated
    finally:
        cursor.close()
        conn.close()
    return {"updated": updated, "failed": failed}


def chat_session_exists(session_id: int) -> bool:
    """Check if a chat session exists in the database."""
    try:
        conn = _connect()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM chat_sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row is not None
    except Exception as ex:
        logger.error(f"[db] chat_session_exists failed: {ex}")
        return False

