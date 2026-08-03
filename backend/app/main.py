"""FastAPI 入口。"""
from fastapi import FastAPI

app = FastAPI(title="Fitness Hub", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
