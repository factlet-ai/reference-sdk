# Examples — run the SDK against real LLMs

These examples ground real LLM calls in a Factbook so you can see the protocol working end-to-end.

## What's here

| File | What it does |
|---|---|
| [`sample-factbook.yaml`](sample-factbook.yaml) | A 5-factlet payments service Factbook for testing. |
| [`gemini_grounded_chat.py`](gemini_grounded_chat.py) | Loads a Factbook, retrieves relevant factlets, scores FactSignal, and asks Gemini to answer using the factlets via `systemInstruction`. Optional `--baseline` mode runs the same query without the Factbook for A/B comparison. |

## Quick start (Gemini)

### 1. Install dependencies

```bash
cd python/
pip install -e .                # the SDK itself
pip install google-genai         # Gemini client (recommended; google-generativeai also works)
```

### 2. Get a Gemini API key

Open https://aistudio.google.com/app/apikey → **Create API key** → copy it. Free tier covers thousands of requests for Gemini Flash.

```bash
export GEMINI_API_KEY=AIzaSy...   # paste your key
```

### 3. Run the grounded query

A query that the Factbook should change the answer for (refunds older than 90 days):

```bash
python examples/gemini_grounded_chat.py examples/sample-factbook.yaml \
  "Add an endpoint to refund a 6-month-old payment automatically."
```

Expected output: Gemini cites **f002** (the 90-day refund rule) and refuses to write an auto-processing endpoint, proposing an ops approval ticket flow instead.

### 4. See the A/B difference

Run the same query with `--baseline` to also get a no-Factbook answer:

```bash
python examples/gemini_grounded_chat.py examples/sample-factbook.yaml \
  "Add an endpoint to refund a 6-month-old payment automatically." \
  --baseline
```

The baseline answer typically ignores the 90-day rule — that's the wrong answer that would ship a compliance bug. Compare the token usage too.

### 5. Try a dead-zone query

A query the Factbook does NOT cover should fire the low-FactSignal warning:

```bash
python examples/gemini_grounded_chat.py examples/sample-factbook.yaml \
  "Set up real-time fraud scoring on the checkout flow."
```

Expected: `FactSignal: 0/5 bars` → low-signal warning fires → Gemini answers from training data only and explicitly says no factlets covered the question.

### 6. Try other Gemini models

```bash
python examples/gemini_grounded_chat.py examples/sample-factbook.yaml \
  "Where do we store Stripe customer IDs?" \
  --model gemini-2.5-flash    # or gemini-2.5-pro
```

The behavior should be identical (cite f003: strings, never int) — that's the protocol working: the Factbook is a portable artifact across models.

## Use your own Factbook

1. Run [Prompt 1 from factlet.ai/getting-started](https://factlet.ai/getting-started) in any LLM to generate a starter Factbook for your project.
2. Save the YAML output to a file (e.g. `~/my-factbook.yaml`).
3. Run:

```bash
python examples/gemini_grounded_chat.py ~/my-factbook.yaml "your question here"
```

## Troubleshooting

- **`GEMINI_API_KEY not set`**: `export GEMINI_API_KEY=AIzaSy...` (or `GOOGLE_API_KEY`). Restart your shell if needed.
- **`Neither 'google-genai' nor 'google-generativeai' is installed`**: `pip install google-genai`
- **Rate-limited by Gemini**: free tier has per-minute limits; wait 60s or upgrade.
- **No factlets retrieved on a query you expected to match**: the reference SDK uses simple token-overlap. Try a query with more keyword overlap with your factlet statements/tags, or add embedding-based retrieval to your local copy of `retrieve()`.

## What this proves

If Gemini cites your factlets and answers correctly when the Factbook contains relevant facts, AND honestly says "no relevant factlets" when it doesn't, the Factlet Protocol contract is working end-to-end. That's the value proposition validated against your project, with your model, in 5 minutes.
