"""Gemini grounded chat using a Factbook.

Loads a Factbook YAML, retrieves relevant factlets for a query, scores
FactSignal coverage, and asks Gemini to answer using the factlets via
the systemInstruction field.

Usage:

    export GEMINI_API_KEY=...   # get one at https://aistudio.google.com/app/apikey
    pip install google-genai     # newer client; google-generativeai also works
    python examples/gemini_grounded_chat.py examples/sample-factbook.yaml \\
        "Add an endpoint to refund a 6-month-old payment automatically."

Optional: --model gemini-2.0-flash (default) | gemini-2.5-flash | gemini-2.5-pro
          --threshold 2 (default — fires low-FactSignal warning if score < this)
          --baseline (run a second Gemini call WITHOUT the Factbook for A/B comparison)
"""

from __future__ import annotations

import argparse
import os
import sys

from factlet import (
    factsignal,
    load_factbook,
    on_low_factsignal,
    render_for_gemini,
    retrieve,
)


def _import_gemini():
    """Try the newer google-genai client first; fall back to google-generativeai."""
    try:
        from google import genai  # google-genai (new client, recommended)
        return ("genai", genai)
    except ImportError:
        try:
            import google.generativeai as gen_ai  # google-generativeai (older)
            return ("generativeai", gen_ai)
        except ImportError:
            print(
                "Neither 'google-genai' nor 'google-generativeai' is installed.\n"
                "Install one:\n"
                "  pip install google-genai      # recommended\n"
                "  pip install google-generativeai  # older client",
                file=sys.stderr,
            )
            sys.exit(2)


def call_gemini(model_name, query, system_instruction):
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print(
            "GEMINI_API_KEY not set. Get one at https://aistudio.google.com/app/apikey "
            "and run: export GEMINI_API_KEY=...",
            file=sys.stderr,
        )
        sys.exit(2)

    flavor, mod = _import_gemini()

    if flavor == "genai":
        # Newer google-genai client
        client = mod.Client(api_key=api_key)
        config = mod.types.GenerateContentConfig(
            system_instruction=system_instruction
        ) if system_instruction else None
        response = client.models.generate_content(
            model=model_name, contents=query, config=config
        )
        return response.text, getattr(response, "usage_metadata", None)
    else:
        # Older google-generativeai client
        mod.configure(api_key=api_key)
        model_kwargs = {}
        if system_instruction:
            model_kwargs["system_instruction"] = system_instruction
        model = mod.GenerativeModel(model_name, **model_kwargs)
        response = model.generate_content(query)
        return response.text, getattr(response, "usage_metadata", None)


def warn_low_signal(query, score, retrieved, threshold):
    print(
        f"\n  ⚠️  Low FactSignal: {score}/{threshold} bars — model is "
        f"answering with thin grounding. Consider adding more factlets.",
        file=sys.stderr,
    )


def fmt_usage(usage):
    if not usage:
        return "(usage metadata unavailable)"
    # Both clients expose .prompt_token_count and .candidates_token_count
    inp = getattr(usage, "prompt_token_count", None) or getattr(usage, "promptTokenCount", None)
    out = getattr(usage, "candidates_token_count", None) or getattr(usage, "candidatesTokenCount", None)
    return f"input={inp} tok, output={out} tok"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("factbook", help="Path to factbook YAML")
    ap.add_argument("query", help="Query to ask Gemini")
    ap.add_argument("--model", default="gemini-2.0-flash",
                    help="Gemini model id (default: gemini-2.0-flash)")
    ap.add_argument("--threshold", type=int, default=2,
                    help="Low-FactSignal threshold (default: 2)")
    ap.add_argument("--baseline", action="store_true",
                    help="Also run Gemini WITHOUT the Factbook for A/B ROI comparison")
    args = ap.parse_args()

    fb = load_factbook(args.factbook)
    print(f"Loaded factbook: {fb.metadata.get('name', '(unnamed)')} "
          f"with {len(fb.content)} factlets\n")

    facts = retrieve(args.query, fb)
    bars = factsignal(args.query, fb)
    print(f"Query: {args.query}\n")
    print(f"FactSignal: {bars}/5 bars")
    if facts:
        print(f"Retrieved {len(facts)} factlet(s): {[f.id for f in facts]}")
    else:
        print("Retrieved 0 factlets — dead zone.")

    # Fire low-signal callback if applicable
    on_low_factsignal(args.query, fb, threshold=args.threshold, callback=warn_low_signal)

    print("\n--- GROUNDED ANSWER (with Factbook) ---")
    sys_inst = render_for_gemini(facts)
    grounded_text, grounded_usage = call_gemini(args.model, args.query, sys_inst)
    print(grounded_text)
    print(f"\n  Usage: {fmt_usage(grounded_usage)}")

    if args.baseline:
        print("\n--- BASELINE ANSWER (no Factbook) ---")
        baseline_text, baseline_usage = call_gemini(args.model, args.query, None)
        print(baseline_text)
        print(f"\n  Usage: {fmt_usage(baseline_usage)}")
        print("\n--- A/B comparison ---")
        print(f"  Grounded usage: {fmt_usage(grounded_usage)}")
        print(f"  Baseline usage: {fmt_usage(baseline_usage)}")
        print(
            "  Compare quality: did baseline contradict any factlet? "
            "If yes, the Factbook prevented a wrong answer (the ROI win)."
        )


if __name__ == "__main__":
    main()
