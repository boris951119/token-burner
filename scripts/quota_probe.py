import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
import litellm
key = os.environ.get("OPENAI_API_KEY", "")
base = os.environ.get("OPENAI_API_BASE", "")
for m in ("openai/deepseek-v4-flash", "openai/qwen3.7-max", "openai/deepseek-v4-pro"):
    try:
        r = litellm.completion(model=m, messages=[{"role":"user","content":"say ok"}],
                              max_tokens=4, api_key=key, api_base=base, timeout=30)
        print(m, "OK", r.choices[0].message.content[:20])
    except Exception as e:
        print(m, "ERR", str(e)[:120])
