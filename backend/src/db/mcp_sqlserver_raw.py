"""
backend/src/db/mcp_sqlserver_raw.py
===================================
MCP Server for raw SQL Server database exploration.
Provides generic tools to inspect tables, discover schemas, and query data.
"""
import os
import sys
import json
import logging
import pyodbc

# Ensure project root is in python path
_DB_DIR = os.path.dirname(os.path.abspath(__file__))  # backend/src/db
_SRC_DIR = os.path.dirname(_DB_DIR)                  # backend/src
_BACKEND_DIR = os.path.dirname(_SRC_DIR)             # backend
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)        # D:\AI Hackathon\LLM
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# Load env variables
load_dotenv(dotenv_path=os.path.join(_PROJECT_ROOT, ".env"))

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("mcp_sqlserver_raw")

# Initialize FastMCP Server
mcp = FastMCP("Vietjet Raw SQL Server Explorer")

def _get_connection() -> pyodbc.Connection:
    """Establish connection to SQL Server using env variables."""
    server = os.getenv("DB_SERVER", "localhost")
    database = os.getenv("DB_NAME", "airline_db")
    user = os.getenv("DB_USER", "sa")
    password = os.getenv("DB_SA_PASSWORD") or os.getenv("DB_PASSWORD") or os.getenv("MSSQL_SA_PASSWORD")
    
    if not password:
        raise ValueError("DB_PASSWORD or DB_SA_PASSWORD environment variable is not set!")

    # Search for available ODBC drivers
    installed_drivers = pyodbc.drivers()
    driver = "ODBC Driver 18 for SQL Server"
    for d in ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server"]:
        if d in installed_drivers:
            driver = d
            break

    conn_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        "TrustServerCertificate=yes;"
        "Encrypt=no;"
    )
    return pyodbc.connect(conn_str)

@mcp.tool()
def list_tables() -> str:
    """
    List all user tables in the current SQL Server database.
    Returns a JSON string containing the table names.
    """
    logger.info("Listing all tables in the database.")
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT TABLE_NAME 
            FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """)
        tables = [row[0] for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return json.dumps({"status": "success", "tables": tables}, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error listing tables: {e}")
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

@mcp.tool()
def get_table_schema(table_name: str) -> str:
    """
    Get column names, data types, and nullability for a specific table.
    Requires table_name. Returns a JSON string.
    """
    logger.info(f"Retrieving schema for table: {table_name}")
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, CHARACTER_MAXIMUM_LENGTH
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = ?
            ORDER BY ORDINAL_POSITION
        """, (table_name,))
        columns = []
        for row in cursor.fetchall():
            columns.append({
                "column_name": row[0],
                "data_type": row[1],
                "is_nullable": row[2],
                "max_length": row[3]
            })
        cursor.close()
        conn.close()
        return json.dumps({"status": "success", "table": table_name, "columns": columns}, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error getting schema for {table_name}: {e}")
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

@mcp.tool()
def get_sample_data(table_name: str, limit: int = 5) -> str:
    """
    Retrieve the top N sample rows from a table to understand the data format.
    Requires table_name. Optionally set limit (default 5).
    """
    logger.info(f"Retrieving top {limit} rows from table: {table_name}")
    try:
        # Validate table name to avoid SQL injection
        if not table_name.replace('_', '').isalnum():
            raise ValueError(f"Invalid table name: {table_name}")
            
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(f"SELECT TOP {int(limit)} * FROM [{table_name}]")
        
        cols = [d[0] for d in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        
        results = []
        for r in rows:
            row_dict = {}
            for col, val in zip(cols, r):
                # Convert date/time values to string for JSON serialization
                if hasattr(val, "isoformat"):
                    row_dict[col] = val.isoformat()
                else:
                    row_dict[col] = val
            results.append(row_dict)
            
        cursor.close()
        conn.close()
        return json.dumps({"status": "success", "table": table_name, "count": len(results), "data": results}, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error getting sample data for {table_name}: {e}")
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

@mcp.tool()
def run_read_only_query(sql_query: str) -> str:
    """
    Execute a custom read-only SQL query (e.g., SELECT statements only).
    Returns a JSON string containing the results.
    """
    logger.info(f"Executing read-only SQL query: {sql_query}")
    # Simple check to avoid DDL/DML statements
    sql_clean = sql_query.strip().upper()
    forbidden_keywords = ["INSERT ", "UPDATE ", "DELETE ", "DROP ", "CREATE ", "ALTER ", "TRUNCATE "]
    if any(keyword in sql_clean for keyword in forbidden_keywords):
        return json.dumps({"status": "error", "message": "DDL or DML queries are not allowed via this tool. Please use SELECT only."}, ensure_ascii=False)
        
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(sql_query)
        
        cols = [d[0] for d in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        
        results = []
        for r in rows:
            row_dict = {}
            for col, val in zip(cols, r):
                if hasattr(val, "isoformat"):
                    row_dict[col] = val.isoformat()
                else:
                    row_dict[col] = val
            results.append(row_dict)
            
        cursor.close()
        conn.close()
        return json.dumps({"status": "success", "rows_count": len(results), "data": results}, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error executing query: {e}")
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

if __name__ == "__main__":
    # Start the FastMCP server over standard I/O (stdio)
    logger.info("Starting Vietjet Raw SQL Server MCP Server...")
    mcp.run(transport="stdio")
