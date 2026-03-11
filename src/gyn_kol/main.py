from fastapi import FastAPI

from gyn_kol.routers import clinicians, exports, graph, ingestion, mbs, scores

app = FastAPI(title="GYN KOL Identification API", version="0.1.0")

app.include_router(clinicians.router)
app.include_router(scores.router)
app.include_router(graph.router)
app.include_router(exports.router)
app.include_router(ingestion.router)
app.include_router(mbs.router)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
