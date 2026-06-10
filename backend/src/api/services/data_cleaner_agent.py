"""
backend/src/api/services/data_cleaner_agent.py
=============================================
Autonomous Data Cleaning Agent for Vietjet SQL Server.
Discovers schemas, runs query cleanups, and materializes data into the flights table.
"""
import os
import sys
import json
import logging
import time
import pyodbc
from datetime import datetime

# Ensure project root is in python path
_SERVICES_DIR = os.path.dirname(os.path.abspath(__file__))  # backend/src/api/services
_API_DIR = os.path.dirname(_SERVICES_DIR)                  # backend/src/api
_SRC_DIR = os.path.dirname(_API_DIR)                      # backend/src
_BACKEND_DIR = os.path.dirname(_SRC_DIR)                  # backend
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)             # D:\AI Hackathon\LLM
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(_PROJECT_ROOT, ".env"))

logger = logging.getLogger("data_cleaner_agent")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

class DataCleaningAgent:
    def __init__(self):
        self.server = os.getenv("DB_SERVER", "localhost")
        self.database = os.getenv("DB_NAME", "airline_db")
        self.user = os.getenv("DB_USER", "sa")
        self.password = os.getenv("DB_SA_PASSWORD") or os.getenv("DB_PASSWORD") or os.getenv("MSSQL_SA_PASSWORD")
        self.logs = []
        
    def log(self, message: str):
        logger.info(message)
        self.logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    def _get_connection(self) -> pyodbc.Connection:
        if not self.password:
            raise ValueError("Database password environment variable is not set!")
            
        installed_drivers = pyodbc.drivers()
        driver = "ODBC Driver 18 for SQL Server"
        for d in ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server"]:
            if d in installed_drivers:
                driver = d
                break
                
        conn_str = (
            f"DRIVER={{{driver}}};"
            f"SERVER={self.server};"
            f"DATABASE={self.database};"
            f"UID={self.user};"
            f"PWD={self.password};"
            "TrustServerCertificate=yes;"
            "Encrypt=no;"
        )
        return pyodbc.connect(conn_str)

    def run_discovery(self) -> dict:
        """Step 1: Discover database tables and schemas to build database context."""
        self.log("Bắt đầu quy trình Khám phá Schema (Schema Discovery)...")
        self.log(f"Kết nối tới máy chủ: {self.server}, CSDL: {self.database}")
        
        context = {}
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # 1. List all tables
            cursor.execute("""
                SELECT TABLE_NAME 
                FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_TYPE = 'BASE TABLE'
            """)
            tables = [row[0] for row in cursor.fetchall()]
            self.log(f"Tìm thấy {len(tables)} bảng trong cơ sở dữ liệu.")
            
            # 2. Inspect specific target tables
            target_tables = [
                "tbl_Res_Header", "tbl_Res_Segments", "tbl_Res_Legs",
                "tbl_GL_Charges", "tbl_Sked_Detail", "tbl_Fare_Class",
                "tbl_Fare_Family_Definition", "tbl_Airport", "dimdate"
            ]
            
            for t in target_tables:
                if t in tables:
                    cursor.execute(f"SELECT COUNT(*) FROM [{t}]")
                    row_cnt = cursor.fetchone()[0]
                    
                    cursor.execute(f"SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ?", (t,))
                    cols = {row[0]: row[1] for row in cursor.fetchall()}
                    
                    context[t] = {
                        "row_count": row_cnt,
                        "columns": cols
                     }
                    self.log(f"Bảng '{t}': {row_cnt:,} dòng. Cột chính: {list(cols.keys())[:5]}...")
                else:
                    self.log(f"Cảnh báo: Không tìm thấy bảng mục tiêu '{t}'!")
                    
            cursor.close()
            conn.close()
            self.log("Hoàn thành bước Khám phá Schema.")
            return context
        except Exception as e:
            self.log(f"Lỗi khám phá cơ sở dữ liệu: {e}")
            raise e

    def run_cleaning_and_materialization(self, limit_days: int = 30) -> dict:
        """Step 2: Join, clean, compute derived features and save to flights table using pure SQL Server CTEs."""
        self.log("Khởi chạy tiến trình làm sạch và tổng hợp dữ liệu (Pure SQL Server CTEs)...")
        
        # Discover schema first
        self.run_discovery()
        
        t0 = time.time()
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Clean flights table
            self.log("Đang làm sạch bảng flights (TRUNCATE TABLE)...")
            cursor.execute("TRUNCATE TABLE flights")
            self.log("Đã làm sạch bảng flights.")
            
            # Execute the user's SQL Server query with null-handling corrections
            user_query = """
                IF OBJECT_ID('tempdb..#tmp') IS NOT NULL DROP TABLE #tmp;

                SELECT 
                    DATEADD(HOUR, 7, RES.dtm_Creation_Date) AS dtm_Creation_Date,
                    cur.str_Currency_Ident,
                    res.lng_Reservation_Nmbr,
                    res.lng_Agency_Id_Nmbr,
                    dtm_Local_ETD_Date,
                    SKED.str_Dep,
                    SKED.str_Arr,
                    leg.lng_Res_Pax_Group_Id_Nmbr,
                    str_Fare_Class_Short,
                    str_Fare_Family_Ident,
                    str_Fare_Category_Ident,
                    sked.lng_Sked_Detail_Id_Nmbr,
                    sked.str_Flight_Nmbr,
                    DATEDIFF(DAY, RES.dtm_Creation_Date, dtm_Local_ETD_Date) AS lead_time_days,
                    CASE WHEN pax.str_Gender not in ('C','X', 'Y', 'I') THEN 1 ELSE 0 END AS str_Gender,
                    lng_Capacity,
                    res.lng_Seats,
                    leg.lng_Leg_Nmbr,
                    ISNULL(sum(CASE
                        WHEN LCF.lng_Res_Legs_Id_Nmbr is not null  and CC.str_GL_Charge_Category = 'A' AND SKED.lng_Dep_Airport_Id_Nmbr = leg.lng_Dep_Airport_Id_Nmbr THEN mny_GL_Charges_Total
                        WHEN LCF.lng_Res_Legs_Id_Nmbr is not null  and CC.str_GL_Charge_Category = 'A' AND SKED.lng_Dep_Airport_Id_Nmbr <> leg.lng_Dep_Airport_Id_Nmbr THEN 0
                        WHEN LCF.lng_Res_Legs_Id_Nmbr is not null  then CAST(C.mny_GL_Charges_Total * LEGS.mny_Factor AS MONEY)
                        else mny_GL_Charges_Total
                    END), 0) AS mny_GL_Charges_Total
                INTO #tmp
                from dbo.tbl_GL_Charges (READUNCOMMITTED) C
                INNER JOIN dbo.tbl_Res_Legs (READUNCOMMITTED) leg ON c.lng_Res_Legs_Id_Nmbr = leg.lng_Res_Legs_Id_Nmbr
                INNER JOIN dbo.tbl_Res_Segments (READUNCOMMITTED) f ON f.lng_Res_Legs_Id_Nmbr = leg.lng_Res_Legs_Id_Nmbr
                INNER JOIN (
                    SELECT 
                        sked.lng_Sked_Detail_Id_Nmbr,
                        sked.str_Airline_Codes_Ident,
                        sked.str_Flight_Nmbr,
                        sked.dtm_Local_ETD_Date,
                        sked.dtm_Local_ETA_Date,
                        sked.str_Sked_Detail_Status,
                        sked.str_Sked_Detail_Type,
                        sked.lng_Capacity,
                        RTRIM(a1.str_Ident) AS str_Dep,
                        RTRIM(a2.str_Ident) str_Arr,
                        h.str_Active_Flag,
                        sked.dtm_ETD,
                        sked.dtm_ETA,
                        sked.lng_Aircraft_Id_Nmbr,
                        sked.mny_Distance,
                        sked.lng_Dep_Airport_Id_Nmbr,
                        sked.lng_Arr_Airport_Id_Nmbr
                    FROM dbo.tbl_Sked_Detail (READUNCOMMITTED) sked
                    INNER JOIN dbo.tbl_Sked_Header (READUNCOMMITTED) h ON h.lng_Sked_Header_Id_Nmbr = sked.lng_Sked_Header_Id_Nmbr
                    INNER JOIN dbo.tbl_Airport (READUNCOMMITTED) a1 ON a1.lng_Airport_Id_Nmbr = sked.lng_Dep_Airport_Id_Nmbr
                    INNER JOIN dbo.tbl_Airport (READUNCOMMITTED) a2 ON a2.lng_Airport_Id_Nmbr = sked.lng_Arr_Airport_Id_Nmbr
                    where dtm_Local_ETD_Date >= '2026-06-01' and dtm_Local_ETD_Date < '2026-07-01'
                ) sked ON sked.lng_Sked_Detail_Id_Nmbr = f.lng_Sked_Detail_Id_Nmbr
                INNER JOIN dbo.tbl_Users (READUNCOMMITTED) us ON us.lng_User_Id_Nmbr = c.lng_Creation_User_Id_Nmbr
                INNER JOIN dbo.tbl_GL_Charge_Type_Definition (READUNCOMMITTED) cty ON cty.lng_GL_Charge_Type_Id_Nmbr = c.lng_GL_Charge_Type_Id_Nmbr
                INNER JOIN dbo.tbl_Res_Header (READUNCOMMITTED) res ON res.lng_Reservation_Nmbr = c.lng_Reservation_Nmbr
                INNER JOIN dbo.tbl_Agency (READUNCOMMITTED) ag ON AG.lng_Agency_Id_Nmbr = res.lng_Agency_Id_Nmbr
                INNER JOIN dbo.tbl_Agency (READUNCOMMITTED) ag1 ON ag1.lng_Agency_Id_Nmbr = us.lng_Res_Agency_Id_Nmbr
                INNER JOIN dbo.tbl_currency cur (READUNCOMMITTED) on cur.lng_Currency_Id_Nmbr=c.lng_Currency_Id_Nmbr
                LEFT JOIN (select distinct lng_Res_Legs_Id_Nmbr from dbo.vw_Res_Legs_Connecting_Flight ) LCF ON c.lng_Res_Legs_Id_Nmbr = LCF.lng_Res_Legs_Id_Nmbr
                JOIN dbo.tbl_Charges_FareClass_XRef CFX (READUNCOMMITTED) ON CFX.lng_Res_Legs_Id_Nmbr = c.lng_Res_Legs_Id_Nmbr
                JOIN dbo.tbl_Fare_Class FC (READUNCOMMITTED) ON FC.lng_Fare_Class_Id_Nmbr = CFX.lng_Fare_Class_Id_Nmbr 
                JOIN dbo.tbl_Fare_Family_Definition (READUNCOMMITTED) FFD on FFD.lng_Fare_Family_Definition_Id_Nmbr = fc.lng_Fare_Family_Definition_Id_Nmbr	
                join [dbo].[tbl_Fare_Category] (READUNCOMMITTED) fcate on fcate.lng_Fare_Category_Id_Nmbr=fc.lng_Fare_Category_Id_Nmbr
                JOIN tbl_Res_Pax_Group (READUNCOMMITTED) pg ON pg.lng_Res_Pax_Group_Id_Nmbr = leg.lng_Res_Pax_Group_Id_Nmbr
                JOIN tbl_Pax (READUNCOMMITTED) pax ON pax.lng_Pax_Id_Nmbr = pg.lng_Pax_Id_Nmbr
                LEFT JOIN dbo.tbl_Legs_Connecting (READUNCOMMITTED) LEGC ON 
                            leg.lng_Dep_Airport_Id_Nmbr = LEGC.lng_Dep_Airport_Id_Nmbr AND
                            leg.lng_Arr_Airport_Id_Nmbr = LEGC.lng_Arr_Airport_Id_Nmbr
                LEFT JOIN dbo.tbl_Legs_Connecting_Segments (READUNCOMMITTED) LEGS ON LEGS.lng_Legs_Connecting_Id_Nmbr = LEGC.lng_Legs_Connecting_Id_Nmbr
                            AND LEGS.lng_Dep_Airport_Id_Nmbr = SKED.lng_Dep_Airport_Id_Nmbr
                            AND LEGS.lng_Arr_Airport_Id_Nmbr = SKED.lng_Arr_Airport_Id_Nmbr
                LEFT JOIN dbo.tbl_GL_Charge_Category (READUNCOMMITTED) CC ON CC.str_GL_Charge_Type_Ident = cty.str_GL_Charge_Type_Ident
                where 1=1
                AND leg.str_Leg_Status = 'C'
                and c.lng_GL_Charge_Type_Id_Nmbr=4
                and str_Visible_Flag='Y'
                and str_Sked_Detail_Type='S'
                and str_Airline_Codes_Ident = 'VJ'
                group by 
                    res.lng_Seats,
                    leg.lng_Leg_Nmbr,
                    RES.dtm_Creation_Date,
                    cur.str_Currency_Ident,
                    res.lng_Reservation_Nmbr,
                    res.lng_Agency_Id_Nmbr,
                    dtm_Local_ETD_Date,
                    SKED.str_Dep,
                    SKED.str_Arr,
                    leg.lng_Res_Pax_Group_Id_Nmbr,
                    str_Fare_Class_Short,
                    str_Fare_Family_Ident,
                    str_Fare_Category_Ident,
                    lng_Capacity,
                    sked.lng_Sked_Detail_Id_Nmbr,
                    sked.str_Flight_Nmbr,
                    CASE WHEN pax.str_Gender not in ('C','X', 'Y', 'I') THEN 1 ELSE 0 END;

                WITH cte_1_base AS (
                    SELECT DISTINCT CAST(dtm_Creation_Date AS DATE) dtm_Creation_Date, lng_Sked_Detail_Id_Nmbr 
                    FROM #tmp
                )
                ,cte_1_agg AS (
                    SELECT 
                        a.dtm_Creation_Date,
                        a.lng_Sked_Detail_Id_Nmbr,
                        sked.lng_Capacity,
                        COUNT(DISTINCT leg.lng_Res_Pax_Group_Id_Nmbr) AS LF_Count,
                        COUNT(DISTINCT CASE WHEN res.dtm_Creation_Date > DATEADD(HOUR, -7, DATEADD(DAY, -3, CAST(a.dtm_Creation_Date AS DATETIME)))
                                            THEN leg.lng_Res_Pax_Group_Id_Nmbr END) AS Vel_3d_Count,
                        COUNT(DISTINCT CASE WHEN res.dtm_Creation_Date > DATEADD(HOUR, -7, DATEADD(DAY, -7, CAST(a.dtm_Creation_Date AS DATETIME)))
                                            THEN leg.lng_Res_Pax_Group_Id_Nmbr END) AS Vel_7d_Count
                    FROM cte_1_base a
                    JOIN dbo.tbl_Sked_Detail (READUNCOMMITTED) sked ON sked.lng_Sked_Detail_Id_Nmbr = a.lng_Sked_Detail_Id_Nmbr
                    JOIN dbo.tbl_Sked_Header (READUNCOMMITTED) SH ON sked.lng_Sked_Header_Id_Nmbr = SH.lng_Sked_Header_Id_Nmbr
                    JOIN dbo.tbl_Res_Segments (READUNCOMMITTED) seg ON seg.lng_Sked_Detail_id_Nmbr = sked.lng_Sked_Detail_Id_Nmbr        
                    JOIN dbo.tbl_Res_Legs (READUNCOMMITTED) leg ON leg.lng_Res_Legs_Id_Nmbr = seg.lng_Res_Legs_Id_Nmbr
                    JOIN dbo.tbl_Res_Header (READUNCOMMITTED) res ON res.lng_Reservation_Nmbr = leg.lng_Reservation_Nmbr
                    WHERE leg.str_Leg_Status = 'C'
                      AND res.dtm_Creation_Date < DATEADD(HOUR, -7, CAST(a.dtm_Creation_Date AS DATETIME)) 
                    GROUP BY 
                        a.dtm_Creation_Date,
                        a.lng_Sked_Detail_Id_Nmbr,
                        sked.lng_Capacity
                ),
                cte_1 AS (
                    SELECT 
                        dtm_Creation_Date,
                        lng_Sked_Detail_Id_Nmbr,
                        CASE WHEN ISNULL(lng_Capacity, 0) = 0 THEN 0 ELSE 1.0 * ISNULL(LF_Count, 0) / lng_Capacity END AS LF_by_date,
                        CASE WHEN ISNULL(lng_Capacity, 0) = 0 THEN 0 ELSE 1.0 * ISNULL(Vel_3d_Count, 0) / lng_Capacity END AS booking_velocity_3d,
                        CASE WHEN ISNULL(lng_Capacity, 0) = 0 THEN 0 ELSE 1.0 * ISNULL(Vel_7d_Count, 0) / lng_Capacity END AS booking_velocity_7d
                    FROM cte_1_agg
                ),
                cte_2_base AS (
                    SELECT DISTINCT CAST(dtm_Creation_Date AS DATE) dtm_Creation_Date, lng_Sked_Detail_Id_Nmbr, str_Fare_Family_Ident 
                    FROM #tmp
                ),
                cte_2_agg AS (
                    SELECT 
                        a.dtm_Creation_Date,
                        a.lng_Sked_Detail_Id_Nmbr,
                        a.str_Fare_Family_Ident,
                        sked.lng_Capacity,
                        COUNT(DISTINCT leg.lng_Res_Pax_Group_Id_Nmbr) AS LF_Count
                    FROM cte_2_base a
                    JOIN dbo.tbl_Sked_Detail (READUNCOMMITTED) sked ON sked.lng_Sked_Detail_Id_Nmbr = a.lng_Sked_Detail_Id_Nmbr
                    JOIN dbo.tbl_Sked_Header (READUNCOMMITTED) SH ON sked.lng_Sked_Header_Id_Nmbr = SH.lng_Sked_Header_Id_Nmbr
                    JOIN dbo.tbl_Res_Segments (READUNCOMMITTED) seg ON seg.lng_Sked_Detail_id_Nmbr = sked.lng_Sked_Detail_Id_Nmbr        
                    JOIN dbo.tbl_Res_Legs (READUNCOMMITTED) leg ON leg.lng_Res_Legs_Id_Nmbr = seg.lng_Res_Legs_Id_Nmbr
                    JOIN dbo.tbl_Res_Header (READUNCOMMITTED) res ON res.lng_Reservation_Nmbr = leg.lng_Reservation_Nmbr
                    JOIN dbo.tbl_Charges_FareClass_XRef CFX (READUNCOMMITTED) ON CFX.lng_Res_Legs_Id_Nmbr = leg.lng_Res_Legs_Id_Nmbr
                    JOIN dbo.tbl_Fare_Class FC (READUNCOMMITTED) ON FC.lng_Fare_Class_Id_Nmbr = CFX.lng_Fare_Class_Id_Nmbr 
                    JOIN dbo.tbl_Fare_Family_Definition (READUNCOMMITTED) FFD ON FFD.lng_Fare_Family_Definition_Id_Nmbr = fc.lng_Fare_Family_Definition_Id_Nmbr	
                    WHERE leg.str_Leg_Status = 'C'
                      AND FFD.str_Fare_Family_Ident = a.str_Fare_Family_Ident
                      AND res.dtm_Creation_Date < DATEADD(HOUR, -7, CAST(a.dtm_Creation_Date AS DATETIME))
                    GROUP BY 
                        a.dtm_Creation_Date,
                        a.lng_Sked_Detail_Id_Nmbr,
                        a.str_Fare_Family_Ident,
                        sked.lng_Capacity
                ),
                cte_2 AS (
                    SELECT 
                        dtm_Creation_Date,
                        lng_Sked_Detail_Id_Nmbr,
                        str_Fare_Family_Ident,
                        CASE WHEN ISNULL(lng_Capacity, 0) = 0 THEN 0 ELSE 1.0 * ISNULL(LF_Count, 0) / lng_Capacity END AS LF_by_fare
                    FROM cte_2_agg
                ),
                cte_3 as
                (
                    select lng_Reservation_Nmbr,case when max_Leg_Nmbr <= 1 then 1 else 0 end is_oneway
                    from (
                        select lng_Reservation_Nmbr, max(lng_Leg_Nmbr) as max_Leg_Nmbr from #tmp group by lng_Reservation_Nmbr
                    ) a
                ),
                cte_4 as
                (
                    select CAST(dtm_Local_ETD_Date AS DATE) dtm_Local_ETD_Date,str_Dep,str_Arr,count(distinct lng_Sked_Detail_Id_Nmbr) count_sked 
                    from #tmp 
                    group by CAST(dtm_Local_ETD_Date AS DATE),str_Dep,str_Arr
                ),
                cte_tbl_AI_dinhnb_2 as
                (
                    SELECT 
                        a.*, 
                        ISNULL(b.booking_velocity_3d, 0) AS booking_velocity_3d, 
                        ISNULL(b.booking_velocity_7d, 0) AS booking_velocity_7d, 
                        ISNULL(b.LF_by_date, 0) AS LF_by_date, 
                        ISNULL(c.LF_by_fare, 0) AS LF_by_fare, 
                        f.Weekday, 
                        f.IsHoliday,
                        d.is_oneway,
                        e.count_sked,
                        f.lng_fuel
                    FROM #tmp a
                    join cte_3 d on a.lng_Reservation_Nmbr=d.lng_Reservation_Nmbr
                    join cte_4 e on CAST(a.dtm_Local_ETD_Date AS DATE)=e.dtm_Local_ETD_Date and a.str_Dep=e.str_Dep and a.str_Arr=e.str_Arr
                    JOIN cte_1 b ON CAST(a.dtm_Creation_Date AS DATE) = b.dtm_Creation_Date AND a.lng_Sked_Detail_Id_Nmbr = b.lng_Sked_Detail_Id_Nmbr
                    JOIN cte_2 c ON CAST(a.dtm_Creation_Date AS DATE) = c.dtm_Creation_Date AND a.lng_Sked_Detail_Id_Nmbr = c.lng_Sked_Detail_Id_Nmbr AND a.str_Fare_Family_Ident = c.str_Fare_Family_Ident
                    JOIN [dbo].[DimDate] f ON f.Date = CAST(a.dtm_Local_ETD_Date AS DATE)
                )
                INSERT INTO flights (
                    flight_no,
                    flight_date,
                    str_Dep,
                    str_Arr,
                    str_Fare_Category,
                    mny_GL_Charges_Total,
                    LF_by_date,
                    LF_by_fare,
                    lead_time_days,
                    booking_velocity_3d,
                    booking_velocity_7d,
                    Weekday,
                    IsHoliday,
                    is_oneway,
                    lng_Capacity,
                    lng_Seats,
                    count_sked,
                    fare_family,
                    lng_fuel
                )
                SELECT DISTINCT
                    'VJ' + cast(str_Flight_Nmbr AS VARCHAR(50)) AS flight_no,
                    CAST(dtm_Local_ETD_Date AS DATE) AS flight_date,
                    str_Dep,
                    str_Arr,
                    ISNULL(str_Fare_Category_Ident, 'N/A') AS str_Fare_Category,
                    ISNULL(mny_GL_Charges_Total, 0) AS mny_GL_Charges_Total,
                    ISNULL(LF_by_date, 0) AS LF_by_date,
                    LF_by_fare,
                    lead_time_days,
                    booking_velocity_3d,
                    booking_velocity_7d,
                    Weekday,
                    IsHoliday,
                    is_oneway,
                    lng_Capacity,
                    lng_Seats,
                    count_sked,
                    str_Fare_Family_Ident AS fare_family,
                    lng_fuel
                FROM cte_tbl_AI_dinhnb_2;

                DROP TABLE #tmp;
            """
            
            self.log("Đang khởi chạy truy vấn SQL làm sạch dữ liệu lớn (Pure SQL Server CTEs)...")
            cursor.execute(user_query)
            
            # Consume all result sets generated by the multi-statement script
            result_sets = 0
            while cursor.nextset():
                result_sets += 1
                
            conn.commit()
            self.log(f"Đã hoàn thành thực thi toàn bộ các câu lệnh SQL ({result_sets} result sets).")
            
            # Verify final count in flights table
            cursor.execute("SELECT COUNT(*) FROM flights")
            cnt = cursor.fetchone()[0]
            
            # Get basic routing stats
            cursor.execute("SELECT COUNT(DISTINCT str_Dep + '-' + str_Arr) FROM flights")
            routes_cnt = cursor.fetchone()[0]
            
            cursor.close()
            conn.close()
            
            elapsed = time.time() - t0
            self.log(f"Hoàn thành làm sạch dữ liệu! Đã nạp thành công {cnt:,} dòng vào bảng flights.")
            self.log(f"Tổng thời gian chạy: {elapsed:.2f} giây.")
            
            stats = {
                "status": "success",
                "rows_processed": cnt,
                "elapsed_seconds": round(elapsed, 2),
                "flight_dates": "2026-06-01 đến 2026-06-30",
                "unique_flights": cnt,  # Each row represents a flight schedule/date combination
                "routes_count": routes_cnt
            }
            return stats
            
        except Exception as e:
            self.log(f"Lỗi quy trình làm sạch dữ liệu: {e}")
            import traceback
            self.log(traceback.format_exc())
            return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    agent = DataCleaningAgent()
    res = agent.run_cleaning_and_materialization()
    print("RESULT:", json.dumps(res, indent=2))
