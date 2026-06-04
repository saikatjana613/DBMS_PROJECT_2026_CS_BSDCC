# LLM-R2 Multi-Provider Quick Start

## One-Command Setup

### Gemini API
```powershell
# 1. Get your free API key from https://aistudio.google.com/apikey
# 2. Set environment variable
$env:GEMINI_API_KEY = "your-key-here"

# 3. Run
python main_pipeline.py --demo
```

### Ollama (Local)
```powershell
# 1. Download model (one-time)
ollama pull mistral

# 2. Start server (background)
ollama serve

# 3. Run (in another terminal)
python main_pipeline.py --demo
```

### Fallback (No Setup)
```powershell
# Just run - uses rule heuristics
python main_pipeline.py --demo
```

---

## What Changed?

Added multi-provider LLM support to `gemini_interface.py`:
- ✅ Ollama HTTP API caller (`call_ollama_api()`)
- ✅ Provider selection logic in `predict_rules()`
- ✅ Config fields for Ollama in `config.py`
- ✅ Updated `main_pipeline.py` to pass config to LLM functions
- ✅ Comprehensive setup guide (`OLLAMA_GEMINI_SETUP_GUIDE.md`)

## Key Files Modified

| File | Changes |
|------|---------|
| `gemini_interface.py` | Added `call_ollama_api()`, multi-provider `predict_rules()` |
| `config.py` | Added `llm_provider`, `ollama_*` fields, `LLM_CONFIG` instance |
| `main_pipeline.py` | Updated `predict_rules()` calls to pass `config` |

---

## Configuration

Edit `DBMS PROJECT/config.py`:

```python
@dataclass
class LLMConfig:
    # Choose: "gemini", "ollama", or "simulation"
    llm_provider: str = "gemini"
    
    # Gemini settings
    gemini_api_key: Optional[str] = None  # Reads GEMINI_API_KEY if None
    gemini_model: str = "gemini-2.0-pro"
    gemini_temperature: float = 0.3
    
    # Ollama settings
    ollama_model: str = "mistral"
    ollama_base_url: str = "http://localhost:11434"
    ollama_temperature: float = 0.3
    ollama_top_p: float = 0.9
```

---

## Full Details

See `OLLAMA_GEMINI_SETUP_GUIDE.md` for:
- Detailed setup instructions
- Model recommendations
- Troubleshooting
- Performance expectations
- Configuration examples

---

## Next Steps

1. **Choose provider** → Edit config.py or set environment variable
2. **Verify setup** → Run `python main_pipeline.py --demo`
3. **Run benchmarks** → Run `python main_pipeline.py --dataset all`
4. **View results** → Run `python main_pipeline.py --charts-only`

Check logs for `[✓]`, `[⚠]`, or `[!]` messages to see system status!
