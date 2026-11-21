import os
import json
import base64
import jwt
from fastapi import FastAPI, BackgroundTasks, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from app.rag_agent import rag_app
from app.ingest import run_ingestion

app = FastAPI(title="Enterprise Fabric RAG API", version="1.0.0")

# Allow your custom web app origin (replace with your internal web app URL)
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

class ChatRequest(BaseModel):
    question: str

class ChatResponse(BaseModel):
    answer: str
    sources: List[str]

def get_user_groups(
    authorization: Optional[str] = Header(None),
    x_ms_client_principal: Optional[str] = Header(None), # Injected by Azure Container Apps Easy Auth
) -> List[str]:
    """
    Extracts Entra ID security group IDs securely from Azure Easy Auth 
    or a Bearer JWT token sent by your custom web app.
    """
    # 1. Production Azure Container Apps Built-In Auth (Recommended)
    if x_ms_client_principal:
        decoded = json.loads(base64.b64decode(x_ms_client_principal).decode("utf-8"))
        claims = decoded.get("claims", [])
        return [c["val"] for c in claims if c.get("typ") == "groups"]

    # 2. Direct Bearer Token from Custom Web App (MSAL)
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        # NOTE: In production without Easy Auth, verify signature against Entra ID JWKS public keys
        unverified_claims = jwt.decode(token, options={"verify_signature": False})
        return unverified_claims.get("groups", [])

    # 3. Local VS Code Testing Fallback (Disabled in Production)
    if os.getenv("ENV_MODE") == "local_dev":
        return os.getenv("DEV_TEST_GROUPS", "").split(",")

    raise HTTPException(status_code=401, detail="Missing or invalid Entra ID authentication token.")

@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest, user_groups: List[str] = Depends(get_user_groups)):
    if not user_groups or user_groups == [""]:
        raise HTTPException(status_code=403, detail="User has no assigned Entra ID security groups.")

    result = rag_app.invoke({
        "question": request.question,
        "current_query": request.question,
        "user_groups": user_groups,
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
