import httpx
from bs4 import BeautifulSoup
import asyncio

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CitationCheck/1.0; +https://github.com/Rabba-Meghana/citation-check)"
}

async def fetch_url_content(url: str, max_chars: int = 4000) -> dict:
    """
    Fetches and extracts clean text content from a URL.
    Returns { "url", "content", "title", "error" }
    """
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(url, headers=HEADERS)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # Remove noise
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "ads"]):
                tag.decompose()

            # Get title
            title = soup.title.string.strip() if soup.title else "Unknown"

            # Extract main content — prefer article/main tags
            main = soup.find("article") or soup.find("main") or soup.find("body")
            text = main.get_text(separator=" ", strip=True) if main else soup.get_text()

            # Clean up whitespace
            import re
            text = re.sub(r'\s+', ' ', text).strip()
            text = text[:max_chars]  # Limit for API context

            return {
                "url": url,
                "title": title,
                "content": text,
                "error": None,
                "char_count": len(text)
            }

    except httpx.TimeoutException:
        return {"url": url, "title": None, "content": None, "error": "Timeout — source took too long to respond"}
    except httpx.HTTPStatusError as e:
        return {"url": url, "title": None, "content": None, "error": f"HTTP {e.response.status_code} — source returned an error"}
    except Exception as e:
        return {"url": url, "title": None, "content": None, "error": f"Could not fetch source: {str(e)}"}


async def fetch_all_urls(urls: list[str]) -> list[dict]:
    """Fetch multiple URLs concurrently."""
    tasks = [fetch_url_content(url) for url in urls]
    return await asyncio.gather(*tasks)
