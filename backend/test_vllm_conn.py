import os
import sys
import httpx
import json

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

def test_vllm():
    vllm_url = os.getenv("VLLM_URL", "http://localhost:8001/v1")
    api_key = os.getenv("VLLM_API_KEY") or os.getenv("NVIDIA_API_KEY")

    if vllm_url.endswith("/"):
        vllm_url = vllm_url[:-1]

    print("=" * 60)
    print("VLLM MODELS LISTING DIAGNOSTIC")
    print("=" * 60)
    
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    models_url = f"{vllm_url}/models"
    try:
        resp = httpx.get(models_url, headers=headers, timeout=10.0)
        if resp.status_code == 200:
            data = resp.json()
            model_ids = [m["id"] for m in data.get("data", [])]
            
            # Print total count
            print(f"Total available models: {len(model_ids)}")
            
            # Filter models containing 'qwen' or 'nemotron' or 'meta' or 'nvidia'
            nvidia_models = [mid for mid in model_ids if "nvidia" in mid.lower() or "nemotron" in mid.lower()]
            qwen_models = [mid for mid in model_ids if "qwen" in mid.lower()]
            other_notable = [mid for mid in model_ids if "meta" in mid.lower() or "mistral" in mid.lower()]
            
            print("\n--- NVIDIA / Nemotron Models ---")
            for m in sorted(nvidia_models)[:20]:
                print(f"  {m}")
            if len(nvidia_models) > 20:
                print(f"  ... and {len(nvidia_models) - 20} more NVIDIA models")
                
            print("\n--- Qwen Models ---")
            for m in sorted(qwen_models):
                print(f"  {m}")
                
            print("\n--- Other Notable Models (First 10) ---")
            for m in sorted(other_notable)[:10]:
                print(f"  {m}")
                
        else:
            print(f"Failed to query models list. Status: {resp.status_code}")
            print(resp.text)
    except Exception as e:
        print(f"Connection failed: {e}")
    print("=" * 60)

if __name__ == "__main__":
    test_vllm()
