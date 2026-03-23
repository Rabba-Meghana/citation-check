import os
import asyncio
import json
import httpx
from scraper import fetch_all_urls

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama3-70b-8192"

async def groq_chat(prompt: str, max_tokens: int = 1000) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": MODEL, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1}
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


async def analyze_single_citation(claim: str, source: dict) -> dict:
    if source.get("error"):
        return {
            "url": source["url"], "title": source.get("title", "Unknown"), "claim": claim,
            "status": "unverifiable", "status_label": "⚠️ Unverifiable", "faithfulness_score": 0,
            "explanation": f"Could not fetch source: {source['error']}", "what_source_says": None,
            "fabricated_parts": None, "error": source["error"]
        }

    prompt = f"""You are a forensic fact-checker. Compare this AI-generated claim against the actual source content.

CLAIM: \"\"\"{claim}\"\"\"
SOURCE ({source['url']}): \"\"\"{source['content']}\"\"\"

Respond ONLY with JSON, no markdown, no extra text:
{{
  "faithfulness_score": <0-100>,
  "status": "<faithful|exaggerated|misleading|hallucinated|unrelated>",
  "explanation": "<2-3 sentences>",
  "what_source_says": "<1-2 sentences>",
  "fabricated_parts": "<specific fabricated parts or null>",
  "direct_contradiction": <true|false>
}}"""

    raw = await groq_chat(prompt, max_tokens=600)
    clean = raw.replace("```json", "").replace("```", "").strip()
    result = json.loads(clean[clean.find("{"):clean.rfind("}")+1])

    labels = {"faithful": "✅ Faithful", "exaggerated": "🟠 Exaggerated", "misleading": "🟡 Misleading", "hallucinated": "🔴 Hallucinated", "unrelated": "⚫ Unrelated"}
    return {
        "url": source["url"], "title": source.get("title", "Unknown Source"), "claim": claim,
        "status": result["status"], "status_label": labels.get(result["status"], "❓ Unknown"),
        "faithfulness_score": result["faithfulness_score"], "explanation": result["explanation"],
        "what_source_says": result.get("what_source_says"), "fabricated_parts": result.get("fabricated_parts"),
        "direct_contradiction": result.get("direct_contradiction", False), "error": None
    }


async def generate_overall_verdict(answer: str, results: list) -> dict:
    avg = sum(r["faithfulness_score"] for r in results) / len(results) if results else 0
    hallucinated = sum(1 for r in results if r["status"] == "hallucinated")
    faithful = sum(1 for r in results if r["status"] == "faithful")

    prompt = f"""Senior AI reliability analyst. Given these citation results, write a verdict.

RESULTS:
{chr(10).join([f"- [{r['status'].upper()}] {r['explanation']}" for r in results])}
STATS: avg faithfulness {avg:.0f}%, hallucinated {hallucinated}/{len(results)}, faithful {faithful}/{len(results)}

Respond ONLY with JSON, no markdown:
{{"verdict": "<2-3 sentence verdict>", "trust_level": "<high|medium|low|very_low>", "key_issue": "<biggest problem or null>"}}"""

    raw = await groq_chat(prompt, max_tokens=300)
    clean = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(clean[clean.find("{"):clean.rfind("}")+1])


async def analyze_citations(answer: str, citations: list) -> dict:
    sources = await fetch_all_urls([c["url"] for c in citations])
    source_map = {s["url"]: s for s in sources}

    results = await asyncio.gather(*[
        analyze_single_citation(claim=citations[i]["claim"], source=source_map.get(citations[i]["url"], {"url": citations[i]["url"], "error": "Not fetched"}))
        for i in range(len(citations))
    ])

    verdict_data = await generate_overall_verdict(answer, list(results))
    overall_score = int(sum(r["faithfulness_score"] for r in results) / len(results))

    return {
        "overall_score": overall_score, "verdict": verdict_data["verdict"],
        "trust_level": verdict_data["trust_level"], "key_issue": verdict_data.get("key_issue"),
        "results": list(results),
        "summary": f"{len([r for r in results if r['status'] == 'faithful'])} of {len(results)} citations verified faithful"
    }
