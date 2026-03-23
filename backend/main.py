from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from analyzer import analyze_citations
import uvicorn

app = FastAPI(
    title="CitationCheck API",
    description="Fact-checks AI citations against their source URLs",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class CheckRequest(BaseModel):
    answer: str  # The full Perplexity answer
    citations: list[dict]  # [{ "url": "...", "claim": "..." }]

class CheckResponse(BaseModel):
    overall_score: int
    verdict: str
    results: list[dict]
    summary: str

@app.post("/check", response_model=CheckResponse)
async def check_citations(req: CheckRequest):
    if not req.citations:
        raise HTTPException(status_code=400, detail="No citations provided")
    if len(req.citations) > 10:
        raise HTTPException(status_code=400, detail="Max 10 citations per request")

    result = await analyze_citations(req.answer, req.citations)
    return result

@app.get("/health")
def health():
    return {"status": "ok", "service": "CitationCheck"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
