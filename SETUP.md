# Airline Revenue Optimizer -- Setup Guide

## Yeu cau
- Python 3.11+
- Node.js 18+
- Data file: `ai.xlsx` dat tai `data/raw/` hoac CSV files tai `data/`

---

> **Note**: Copy `.env.gpu` to `.env` and fill in your database credentials
> and any API keys before running any of the steps below.

---

## Buoc 1 -- Train Models (Kaggle Pipeline)

```bash
pip install -r kaggle/requirements.txt
python kaggle/scripts/run_pipeline.py
```

Ket qua train se luu tai:
```
outputs/kaggle_models/
  xgboost_model.pkl
  lightgbm_model.pkl
  catboost_model.pkl
  random_forest_model.pkl
  gradient_boosting_model.pkl
  mlp_model.pkl
  label_encoders.pkl
  imputation_values.pkl
  feature_names.txt
  model_comparison.csv
  final_report.json   <<< bao cao model tot nhat
```

---

## Buoc 2 -- Start Backend API

```bash
cd backend
pip install -r requirements.txt

uvicorn backend.src.api.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

### Endpoints

| Method | URL         | Mo ta |
|--------|-------------|-------|
| GET    | /health     | Health check + model status |
| GET    | /models     | List all 6 models |
| GET    | /summary    | KPI tong quan |
| GET    | /flights    | Danh sach chuyen + AI price |
| GET    | /routes     | Thong ke theo tuyen |
| POST   | /predict    | Du doan gia ve |
| POST   | /optimize   | Tinh gia toi uu |
| POST   | /simulate   | What-if revenue simulation |

---

## Buoc 3 -- Start Frontend

```bash
cd frontend
npm install
npm run dev
# Mo: http://localhost:3000
```

---

## Deploy voi Docker

### Dev mode
```bash
docker compose -f docker-compose.gpu.yml --profile dev up

# Train model trong container
docker compose -f docker-compose.gpu.yml --profile dev run --rm backend python kaggle/scripts/run_pipeline.py
```

### Production
```bash
docker build -t airline-optimizer .
docker compose -f docker-compose.gpu.yml --profile prod up -d
# Dashboard: http://localhost
```

---

## Cau truc cua moi folder

### backend/src/
- `api/main.py` -- FastAPI server, load models tu outputs/kaggle_models/
- `models/trainer.py` -- Chi load models, khong train (model da train boi kaggle/)
- `models/optimizer.py` -- Revenue optimizer (scipy, tinh gia toi uu, khong can model ML)

### kaggle/src/
- `data_loader.py` -- Load data tu Google Drive / local CSV
- `preprocessor.py` -- Clean data + feature engineering (22 features, NO leakage)
- `trainer.py` -- Train 6 models: XGBoost, LightGBM, CatBoost, RF (ho tro GPU qua cuML), GB, MLP
- `visualizer.py` -- Charts: MAPE comparison, Actual vs Predicted, Feature Importance
- `shap_analysis.py` -- SHAP summary cho best model

---

## Huong dan Cai dat RAPIDS cuML de Tang toc GPU

Mô hình Random Forest và các bước xử lý dữ liệu có thể được tăng tốc từ 10x - 50x trên GPU NVIDIA bằng cách cài đặt hệ sinh thái **RAPIDS**.

### Yeu cau phan cung:
* GPU NVIDIA có kiến trúc Pascal trở lên (Compute Capability >= 6.0).
* Đã cài đặt NVIDIA Driver và CUDA Toolkit (khuyên dùng CUDA 11.8 hoặc 12.x).

### Cach cai dat:
Chúng tôi khuyến nghị sử dụng môi trường **Conda** để cài đặt RAPIDS dễ dàng nhất:

```bash
# Tao mot moi truong conda moi va cai dat rapids
conda create -n rapids-24.04 -c rapidsai -c conda-forge -c nvidia \
    rapids=24.04 python=3.11 cuda-version=12.0 -y

# Kich hoat moi truong
conda activate rapids-24.04

# Cai dat cac dependency bo sung cua project
pip install -r kaggle/requirements.txt
```

Sau khi cài đặt thành công, khi chạy pipeline huấn luyện `run_pipeline.py`, hệ thống sẽ tự động phát hiện GPU và sử dụng `cuml.ensemble.RandomForestRegressor` để tăng tốc huấn luyện mô hình.
