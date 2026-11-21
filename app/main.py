from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import List
from app.rag_agent import rag_app
from app.ingest import run_ingestion

app = FastAPI(title="Enterprise Fabric RAG API", version="1.0.0")

class ChatRequest(BaseModel):
    question: str
    user_groups: List[str] # In production, extract these from validated Entra ID JWT claims

class ChatResponse(BaseModel):
    answer: str
    sources: List[str]

@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest):
    if not request.user_groups:
        raise HTTPException(status_code=403, detail="User has no assigned Entra ID security groups.")

    result = rag_app.invoke({
        "question": request.question,
        "current_query": request.question,
        "user_groups": request.user_groups,
        "documents": [],
        "sources": [],
        "is_relevant": False,
        "retries": 0,
        "answer": ""
    })

    return ChatResponse(answer=result["answer"], sources=result["sources"])

@app.post("/ingest")
def trigger_ingestion(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_ingestion)
    return {"status": "Ingestion job started in background."}
