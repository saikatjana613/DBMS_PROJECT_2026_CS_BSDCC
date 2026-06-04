# Multi-Provider LLM Setup Guide

This guide shows how to use the LLM-R2 query optimizer with either **Google Gemini API** or **Ollama** (local models).

## Quick Overview

The system now supports three LLM providers:

1. **Gemini API** (cloud) - Requires API key
2. **Ollama** (local) - Requires Ollama installed locally
3. **Simulation** (fallback) - No setup needed, uses rule heuristics

---

## Option 1: Using Google Gemini API

### Step 1: Get Your API Key

1. Visit [Google AI Studio](https://aistudio.google.com/apikey)
2. Click **"Create API Key"**
3. Copy the generated API key

### Step 2: Configure LLM-R2

There are two ways to provide your Gemini API key:

#### Option A: Environment Variable (Recommended)

**Windows PowerShell:**
```powershell
$env:GEMINI_API_KEY = "your-api-key-here"
python main_pipeline.py
```

**Windows Command Prompt:**
```cmd
set GEMINI_API_KEY=your-api-key-here
python main_pipeline.py
```

**Linux/Mac:**
```bash
export GEMINI_API_KEY="your-api-key-here"
python main_pipeline.py
```

#### Option B: Edit config.py

Open `DBMS PROJECT/config.py` and modify:

```python
@dataclass
class LLMConfig:
    # ... other fields ...
    
    # Set your API key directly
    gemini_api_key: Optional[str] = "your-api-key-here"
    
    # Set provider to "gemini"
    llm_provider: str = "gemini"
```

### Step 3: Verify Setup

Run the demo to verify:
```powershell
python main_pipeline.py --demo
```

You should see logs like:
```
[✓ USING REAL GEMINI API] Calling gemini-2.0-pro with XXX chars
[✓ GEMINI RESPONSE] Got N rule(s): [...] (latency: X.XXXs)
```

---

## Option 2: Using Ollama (Local Models)

### Step 1: Install Ollama

1. Download from [ollama.ai](https://ollama.ai)
2. Install and run the installer
3. Ollama will start automatically and listen on `http://localhost:11434`

### Step 2: Pull a Model

Open PowerShell/Terminal and run:

```powershell
# Download Mistral (recommended, ~4GB)
ollama pull mistral

# Or other models:
ollama pull llama2          # ~7GB, good reasoning
ollama pull neural-chat     # ~4GB, chat optimized
ollama pull orca-mini       # ~2GB, lightweight
```

**Note:** First pull will take a few minutes depending on your internet speed.

### Step 3: Start Ollama Server

Ollama typically runs as a background service, but you can explicitly start it:

```powershell
ollama serve
```

Verify it's running at: `http://localhost:11434/api/generate`

### Step 4: Configure LLM-R2

Edit `DBMS PROJECT/config.py`:

```python
@dataclass
class LLMConfig:
    # ... other fields ...
    
    # Set provider to "ollama"
    llm_provider: str = "ollama"
    
    # Configure Ollama settings
    ollama_model: str = "mistral"           # or "llama2", "neural-chat", etc.
    ollama_base_url: str = "http://localhost:11434"
    ollama_temperature: float = 0.3         # 0.0=deterministic, 1.0=creative
    ollama_top_p: float = 0.9               # nucleus sampling
```

### Step 5: Verify Setup

Run the demo:
```powershell
python main_pipeline.py --demo
```

You should see logs like:
```
[✓ USING OLLAMA] Calling mistral at http://localhost:11434
[✓ OLLAMA RESPONSE] Got N rule(s): [...] (latency: X.XXXs)
```

---

## Configuration Examples

### Example 1: Use Gemini (API Key in Environment)

**config.py:**
```python
llm_provider: str = "gemini"
gemini_api_key: Optional[str] = None  # Will read from GEMINI_API_KEY env var
```

**PowerShell:**
```powershell
$env:GEMINI_API_KEY = "sk-..."
python main_pipeline.py
```

### Example 2: Use Ollama with Llama2

**config.py:**
```python
llm_provider: str = "ollama"
ollama_model: str = "llama2"
ollama_temperature: float = 0.3
```

**Terminal:**
```powershell
ollama pull llama2
ollama serve
# In another terminal:
python main_pipeline.py --demo
```

### Example 3: Fallback to Simulation (No API/Model Needed)

**config.py:**
```python
llm_provider: str = "simulation"
```

**Terminal:**
```powershell
python main_pipeline.py  # Works immediately, no setup needed
```

---

## Available Models for Ollama

| Model | Size | Speed | Quality | Use Case |
|-------|------|-------|---------|----------|
| **mistral** | 4GB | ⚡⚡⚡ Fast | ⭐⭐⭐ Good | Default, balanced |
| **llama2** | 7GB | ⚡⚡ Medium | ⭐⭐⭐⭐ Excellent | Better reasoning |
| **neural-chat** | 4GB | ⚡⚡⚡ Fast | ⭐⭐⭐ Good | Chat-optimized |
| **orca-mini** | 2GB | ⚡⚡⚡ Very Fast | ⭐⭐ Fair | Lightweight |
| **openchat** | 4GB | ⚡⚡ Medium | ⭐⭐⭐ Good | Fast reasoning |

### Recommendation

**Best for LLM-R2:** Use `mistral` or `llama2`
- Good at SQL understanding
- Fast inference
- Reasonable memory usage

---

## Troubleshooting

### Gemini Issues

#### "API key not valid"
- Verify key from [Google AI Studio](https://aistudio.google.com/apikey)
- Check environment variable is set correctly:
  ```powershell
  echo $env:GEMINI_API_KEY  # Should print your key
  ```

#### "google-genai not installed"
- Install the library:
  ```powershell
  pip install -U google-genai
  ```

#### "Quota exceeded"
- Gemini API has rate limits
- Wait a few seconds and retry
- Check your API quota at Google Cloud Console

### Ollama Issues

#### "Cannot connect to Ollama at http://localhost:11434"
- Start Ollama server:
  ```powershell
  ollama serve
  ```
- Check it's running:
  ```powershell
  curl http://localhost:11434/api/generate
  ```

#### "Model not found"
- Download the model first:
  ```powershell
  ollama pull mistral
  ```
- Verify model is installed:
  ```powershell
  ollama list
  ```

#### "requests library not available"
- Install requests:
  ```powershell
  pip install requests
  ```

#### "Ollama API timed out"
- Model might be too large for your system
- Try smaller model: `ollama pull mistral` (smaller than `llama2`)
- Increase timeout in code if needed

### General Issues

#### "SIMULATION MODE" when expecting real LLM
- Check logs for which provider is being used
- Verify configuration in `config.py`
- For Gemini: Check API key is set
- For Ollama: Check server is running
- Check logs for specific error messages

#### Verify Which Provider is Active

Run demo with verbose output:
```powershell
python main_pipeline.py --demo 2>&1 | Select-String "GEMINI|OLLAMA|SIMULATION"
```

---

## Configuration File Reference

### Full LLMConfig Structure

```python
@dataclass
class LLMConfig:
    # =========== Provider Selection ===========
    llm_provider: str = "gemini"  # "gemini", "ollama", or "simulation"
    
    # =========== Gemini Settings ===========
    gemini_api_key: Optional[str] = None  # Read from GEMINI_API_KEY env var if None
    gemini_model: str = "gemini-2.0-pro"
    gemini_temperature: float = 0.3
    gemini_max_tokens: int = 1024
    
    # =========== Ollama Settings ===========
    ollama_model: str = "mistral"
    ollama_base_url: str = "http://localhost:11434"
    ollama_temperature: float = 0.3
    ollama_top_p: float = 0.9
    
    # =========== Database Settings ===========
    databases: list = field(default_factory=lambda: ["tpc-h", "imdb", "dsb"])
    simulation_mode: bool = False  # Set to False to use real LLM
```

---

## Performance Expectations

### Gemini API
- **Latency:** ~0.5-1.5 seconds per query
- **Cost:** Free tier has daily limits (~60 requests)
- **Quality:** Highest (best model)

### Ollama (Local)
- **Latency:** ~2-10 seconds per query (depends on model & hardware)
- **Cost:** Free (one-time download)
- **Quality:** Good (varies by model)

### Simulation (Fallback)
- **Latency:** <100ms (instant)
- **Cost:** Free
- **Quality:** Fair (rule heuristics only)

---

## Running Full Benchmarks

### With Gemini API

```powershell
$env:GEMINI_API_KEY = "your-key-here"
python main_pipeline.py --dataset all
```

### With Ollama

```powershell
ollama serve  # In background

# In another terminal
python main_pipeline.py --dataset all
```

### Compare Results

Results are saved to `DBMS PROJECT/results/`:
- `tpc-h_results.json`
- `imdb_results.json`
- `dsb_results.json`

View results:
```powershell
python main_pipeline.py --charts-only
```

---

## Next Steps

1. **Choose your provider** (Gemini or Ollama)
2. **Run the setup commands** above
3. **Verify with:** `python main_pipeline.py --demo`
4. **Run full benchmarks:** `python main_pipeline.py --dataset all`
5. **Review results:** `python main_pipeline.py --charts-only`

For questions or issues, check the logs for `[!]`, `[⚠]`, or `[✗]` messages!
