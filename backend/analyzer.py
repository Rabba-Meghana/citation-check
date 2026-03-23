import anthropic
import asyncio
import json
from scraper import fetch_all_urls

client = anthropic.AsyncAnthropic()

async def analyze_single_citation(claim: str, source: dict) -> dict:
    """
    Uses Claude to compare a claim against source content.
    Returns a detailed verdict for one citation.
    """
    if source.get("error"):
        return {
            "url": source["url"],
            "title": source.get("title", "Unknown"),
            "claim": claim,
            "status": "unverifiable",
            "status_label": "⚠️ Unverifiable",
            "faithfulness_score": 0,
            "explanation": f"Could not fetch source: {source['error']}",
            "what_source_says": None,
            "fabricated_parts": None,
            "error": source["error"]
        }

    prompt = f"""You are a forensic fact-checker. Compare this AI-generated claim against the actual source content.

CLAIM (what the AI said, citing this source):
\"\"\"{claim}\"\"\"

ACTUAL SOURCE CONTENT (from {source['url']}):
\"\"\"{source['content']}\"\"\"

Analyze carefully and respond ONLY with a JSON object (no markdown, no extra text):
{{
  "faithfulness_score": <0-100, how faithful the claim is to the source>,
  "status": "<faithful|exaggerated|misleading|hallucinated|unrelated>",
  "explanation": "<2-3 sentences explaining your verdict>",
  "what_source_says": "<what the source actually says about this topic, in 1-2 sentences>",
  "fabricated_parts": "<specific parts of the claim NOT supported by source, or null if faithful>",
  "direct_contradiction": <true if source directly contradicts the claim, false otherwise>
}}

Status definitions:
- faithful: claim accurately reflects source content
- exaggerated: claim overstates what source says
- misleading: claim uses source out of context or cherry-picks
- hallucinated: claim contains information not in source at all
- unrelated: source doesn't cover the topic of the claim
"""

    message = await client.messages.create(
        model="claude-opus-4-5",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text
    clean = raw.replace("```json", "").replace("```", "").strip()
    result = json.loads(clean)

    status_labels = {
        "faithful": "✅ Faithful",
        "exaggerated": "🟠 Exaggerated",
        "misleading": "🟡 Misleading",
        "hallucinated": "🔴 Hallucinated",
        "unrelated": "⚫ Unrelated"
    }

    return {
        "url": source["url"],
        "title": source.get("title", "Unknown Source"),
        "claim": claim,
        "status": result["status"],
        "status_label": status_labels.get(result["status"], "❓ Unknown"),
        "faithfulness_score": result["faithfulness_score"],
        "explanation": result["explanation"],
        "what_source_says": result.get("what_source_says"),
        "fabricated_parts": result.get("fabricated_parts"),
        "direct_contradiction": result.get("direct_contradiction", False),
        "error": None
    }


async def generate_overall_verdict(answer: str, results: list[dict]) -> dict:
    """Generate an overall verdict and summary for all citations."""

    results_summary = "\n".join([
        f"- [{r['status'].upper()}] {r['url']}: {r['explanation']}"
        for r in results
    ])

    avg_score = sum(r["faithfulness_score"] for r in results) / len(results) if results else 0
    hallucinated = sum(1 for r in results if r["status"] == "hallucinated")
    misleading = sum(1 for r in results if r["status"] in ["misleading", "exaggerated"])
    faithful = sum(1 for r in results if r["status"] == "faithful")

    prompt = f"""You are a senior AI reliability analyst. Given citation check results for an AI-generated answer, write a verdict.

ORIGINAL AI ANSWER:
\"\"\"{answer[:1000]}\"\"\"

CITATION RESULTS:
{results_summary}

STATS:
- Average faithfulness: {avg_score:.0f}%
- Hallucinated citations: {hallucinated}/{len(results)}
- Misleading/exaggerated: {misleading}/{len(results)}
- Faithful: {faithful}/{len(results)}

Respond ONLY with JSON (no markdown):
{{
  "verdict": "<2-3 sentence honest overall verdict about this AI answer's reliability>",
  "trust_level": "<high|medium|low|very_low>",
  "key_issue": "<the single biggest problem with this answer, or null if trustworthy>"
}}
"""

    message = await client.messages.create(
        model="claude-opus-4-5",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text
    clean = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(clean)


async def analyze_citations(answer: str, citations: list[dict]) -> dict:
    """
    Main entry point. Takes an AI answer + citations, returns full analysis.
    citations = [{ "url": "...", "claim": "..." }]
    """

    # Step 1: Fetch all URLs concurrently
    urls = [c["url"] for c in citations]
    sources = await fetch_all_urls(urls)

    # Map URL -> source content
    source_map = {s["url"]: s for s in sources}

    # Step 2: Analyze each citation concurrently
    tasks = [
        analyze_single_citation(
            claim=citations[i]["claim"],
            source=source_map.get(citations[i]["url"], {"url": citations[i]["url"], "error": "Not fetched"})
        )
        for i in range(len(citations))
    ]
    results = await asyncio.gather(*tasks)

    # Step 3: Overall verdict
    verdict_data = await generate_overall_verdict(answer, list(results))

    # Step 4: Overall score
    overall_score = int(sum(r["faithfulness_score"] for r in results) / len(results))

    return {
        "overall_score": overall_score,
        "verdict": verdict_data["verdict"],
        "trust_level": verdict_data["trust_level"],
        "key_issue": verdict_data.get("key_issue"),
        "results": list(results),
        "summary": f"{len([r for r in results if r['status'] == 'faithful'])} of {len(results)} citations verified faithful"
    }
