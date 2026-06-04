# Multi-Provider LLM Implementation Details

## Architecture Overview

The system now supports three LLM providers with a unified interface:

```
┌─────────────────────────────────────────────────────────────┐
│            predict_rules() - Main Entry Point               │
├─────────────────────────────────────────────────────────────┤
│ 1. Load LLMConfig from config.py                            │
│ 2. Check llm_provider setting                               │
│ 3. Route to appropriate LLM handler                         │
└─────────────────────────────────────────────────────────────┘
         │              │                  │
         ▼              ▼                  ▼
    ┌────────┐    ┌────────┐         ┌────────────┐
    │ Gemini │    │ Ollama │         │ Simulation │
    │ (API)  │    │(HTTP)  │         │ (Heuristic)│
    └────────┘    └────────┘         └────────────┘
         │              │                  │
         ▼              ▼                  ▼
    call_gemini_api() call_ollama_api()  simulate_prediction()
         │              │                  │
         └──────────────┴──────────────────┘
                    │
                    ▼
            parse_response()
                    │
                    ▼
          return {rules, latency, ...}
```

## Code Flow

### 1. predict_rules(sql, api_key, config) - Entry Point

**Location:** `gemini_interface.py:583`

```python
def predict_rules(sql, api_key=None, config=None):
    # Step 1: Load config if not provided
    if config is None:
        from config import LLM_CONFIG
        config = LLM_CONFIG
    
    # Step 2: Prepare demo and prompt
    demo, similarity = select_demo(sql)
    prompt = build_prompt(sql, demo)
    
    # Step 3: Choose provider
    provider = config.llm_provider  # "gemini", "ollama", or "simulation"
    
    # Step 4: Try provider in order
    if provider == "gemini":
        try:
            response_text, latency = call_gemini_api(prompt, api_key)
            rules = parse_response(response_text)
            return {rules, latency, used_simulation=False, similarity}
        except Exception as e:
            print(f"[✗ GEMINI ERROR] {e}")
            # Fall through to simulation
    
    elif provider == "ollama":
        try:
            response_text, latency = call_ollama_api(prompt, config)
            rules = parse_response(response_text)
            return {rules, latency, used_simulation=False, similarity}
        except Exception as e:
            print(f"[✗ OLLAMA ERROR] {e}")
            # Fall through to simulation
    
    # Fallback to simulation
    print(f"[! SIMULATION MODE]")
    rules, similarity, latency = simulate_prediction(sql)
    return {rules, latency, used_simulation=True, similarity}
```

### 2. call_gemini_api(prompt, api_key) - Existing

**Location:** `gemini_interface.py:293-349`

- Uses `google-genai` SDK
- Tries `gemini-2.0-pro` first, falls back to `gemini-2.0-flash`
- Returns (response_text, latency_sec)

### 3. call_ollama_api(prompt, config) - NEW

**Location:** `gemini_interface.py:352-432`

```python
def call_ollama_api(prompt, config):
    """
    Call Ollama REST API
    
    Args:
        prompt: The prompt text
        config: LLMConfig with ollama_* settings
    
    Returns:
        (response_text, latency_sec)
    
    HTTP Request:
        POST http://localhost:11434/api/generate
        {
            "model": "mistral",
            "prompt": "...",
            "stream": false,
            "temperature": 0.3,
            "top_p": 0.9
        }
    
    Response:
        {
            "model": "mistral",
            "created_at": "2024-...",
            "response": "The recommended rules are...",
            "done": true,
            "total_duration": ...,
            "load_duration": ...,
            "prompt_eval_duration": ...,
            "eval_duration": ...
        }
    """
    import requests
    
    url = f"{config.ollama_base_url}/api/generate"
    payload = {
        "model": config.ollama_model,
        "prompt": prompt,
        "stream": False,
        "temperature": config.ollama_temperature,
        "top_p": config.ollama_top_p,
    }
    
    response = requests.post(url, json=payload, timeout=60)
    result = response.json()
    text = result.get("response", "")
    return text, elapsed_time
```

**Key Features:**
- HTTP POST to Ollama `/api/generate` endpoint
- Non-streaming mode for simplicity
- Configurable temperature and top_p
- 60-second timeout
- Graceful error handling with clear error messages

**Error Handling:**
```python
- requests.ConnectionError → "Cannot connect to Ollama"
- requests.Timeout → "Ollama API timed out"
- HTTP 200 OK → Normal path
- HTTP != 200 → "Ollama API error {code}"
```

### 4. parse_response(response_text) - Existing

**Location:** `gemini_interface.py:468-545`

Parses LLM response and extracts rule names.
Works with both Gemini and Ollama responses.

### 5. simulate_prediction(sql) - Existing

**Location:** `gemini_interface.py:434-548`

Fallback: Uses structural SQL analysis to recommend rules heuristically.
No API needed, instant results.

---

## Configuration Flow

### LLMConfig Dataclass

**Location:** `config.py:88-127`

```python
@dataclass
class LLMConfig:
    # Provider selection
    llm_provider: str = "gemini"  # "gemini", "ollama", "simulation"
    
    # Gemini API settings
    gemini_api_key: Optional[str] = None  # Read from GEMINI_API_KEY env var
    gemini_model: str = "gemini-2.0-pro"
    gemini_temperature: float = 0.3
    gemini_max_tokens: int = 1024
    
    # Ollama local settings
    ollama_model: str = "mistral"
    ollama_base_url: str = "http://localhost:11434"
    ollama_temperature: float = 0.3
    ollama_top_p: float = 0.9
    
    # Database settings
    databases: list = field(default_factory=...)
    simulation_mode: bool = False  # Override: force simulation if True
```

### Loading Configuration

Two ways to load:

1. **Explicit (in main_pipeline.py):**
   ```python
   from config import LLM_CONFIG
   prediction = predict_rules(sql, api_key=None, config=LLM_CONFIG)
   ```

2. **Implicit (in predict_rules):**
   ```python
   # If config=None, predict_rules loads it automatically
   prediction = predict_rules(sql)
   ```

### Setting API Key

Three ways:

1. **Environment variable (recommended):**
   ```powershell
   $env:GEMINI_API_KEY = "sk-..."
   python main_pipeline.py
   ```

2. **Direct in config.py:**
   ```python
   gemini_api_key: Optional[str] = "sk-..."
   ```

3. **Passed to predict_rules():**
   ```python
   predict_rules(sql, api_key="sk-...", config=config)
   ```

---

## Changes to main_pipeline.py

### Before
```python
prediction = predict_rules(sql, api_key)
```

### After
```python
prediction = predict_rules(sql, api_key, self.config)
```

**Locations updated:**
1. Line 331: Main benchmark loop
2. Line 1102: Demo function

---

## Logging & Debugging

### Log Messages

**Gemini Success:**
```
[✓ USING REAL GEMINI API] Calling gemini-2.0-pro with 2156 chars
[✓ GEMINI RESPONSE] Got 2 rule(s): ['FILTER_INTO_JOIN', 'LIMIT_PUSH_DOWN'] (latency: 0.847s)
```

**Ollama Success:**
```
[✓ USING OLLAMA] Calling mistral at http://localhost:11434
[✓ Ollama API succeeded] Model: mistral, Time: 2.34s
[✓ OLLAMA RESPONSE] Got 2 rule(s): ['FILTER_INTO_JOIN', 'LIMIT_PUSH_DOWN'] (latency: 2.341s)
```

**Fallback to Simulation:**
```
[⚠ NO API KEY] GEMINI_API_KEY not set - using SIMULATION mode
[! SIMULATION MODE] Using structural analysis for rule prediction
```

**Errors:**
```
[✗ GEMINI ERROR] API key not valid
[✗ OLLAMA ERROR] Cannot connect to Ollama at http://localhost:11434
```

### Debug Tips

1. **Check which provider is active:**
   ```python
   print(f"Provider: {config.llm_provider}")
   ```

2. **Check API key is loaded:**
   ```python
   print(f"API Key: {config.gemini_api_key or 'Not set'}")
   ```

3. **Check Ollama is running:**
   ```bash
   curl http://localhost:11434/api/generate
   ```

4. **Check environment variable:**
   ```powershell
   echo $env:GEMINI_API_KEY
   ```

---

## Testing

### Test Gemini
```python
from gemini_interface import predict_rules
from config import LLMConfig

config = LLMConfig(llm_provider="gemini")
result = predict_rules(
    "SELECT * FROM table WHERE id = 1",
    api_key="your-key",
    config=config
)
print(result["rules"])
print(f"Used simulation: {result['used_simulation']}")
```

### Test Ollama
```python
# 1. Start Ollama: ollama serve
# 2. Pull model: ollama pull mistral
# 3. Run test:

config = LLMConfig(llm_provider="ollama")
result = predict_rules(
    "SELECT * FROM table WHERE id = 1",
    config=config
)
print(result["rules"])
print(f"Latency: {result['llm_latency_sec']}s")
```

### Test Simulation
```python
config = LLMConfig(llm_provider="simulation")
result = predict_rules(
    "SELECT * FROM a JOIN b ON a.id = b.id WHERE a.x > 10",
    config=config
)
print(result["used_simulation"])  # Should be True
```

---

## Performance Notes

| Provider | Speed | Setup | Cost | Quality |
|----------|-------|-------|------|---------|
| **Gemini** | 0.5-1.5s | API key | Free (~60/day) | Excellent |
| **Ollama** | 2-10s* | Download model | Free | Good |
| **Simulation** | <100ms | None | Free | Fair |

*Depends on model size and hardware

---

## Future Enhancements

1. **Streaming responses** for Ollama (faster perceived latency)
2. **Batch requests** to Ollama API
3. **Cost tracking** per provider
4. **Model auto-selection** based on query complexity
5. **Response caching** to avoid redundant calls
6. **Token counting** before sending to Gemini
7. **Finetuned Ollama models** for SQL optimization

---

## Files Modified Summary

| File | Lines | Changes |
|------|-------|---------|
| `gemini_interface.py` | +80 | call_ollama_api(), provider routing in predict_rules() |
| `config.py` | +5 | Ollama fields, LLM_CONFIG instance |
| `main_pipeline.py` | +2 | Pass config to predict_rules() |
| `OLLAMA_GEMINI_SETUP_GUIDE.md` | +400 | NEW: Comprehensive setup guide |
| `QUICK_START.md` | +60 | NEW: Quick reference |

**Total lines added:** ~550 lines of code + documentation
