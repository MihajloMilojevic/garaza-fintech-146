import sys
from pathlib import Path

# Add repo root to sys.path so `ai.model.predict` is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from data.loader import load_all
from routers import screen, accounts, screening, dashboard, llm_review

app = FastAPI(
    title="Sanctions Screening API",
    description="AI-powered sanctions screening: dynamic thresholds, audit narratives, risk scoring.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    load_all()


app.include_router(screen.router)
app.include_router(accounts.router)
app.include_router(screening.router)
app.include_router(dashboard.router)
app.include_router(llm_review.router)


@app.get("/")
def root():
    return {"status": "ok", "docs": "/docs"}
