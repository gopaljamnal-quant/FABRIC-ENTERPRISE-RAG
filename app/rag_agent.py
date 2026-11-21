from typing import TypedDict, List
from pydantic import BaseModel, Field
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery, QueryType
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from langgraph.graph import StateGraph, END
from app.config import settings

credential = DefaultAzureCredential()
token_provider = get_bearer_token_provider(credential, "https://azure.com")

llm = AzureChatOpenAI(
    azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
    azure_ad_token_provider=token_provider,
    azure_deployment=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
    api_version=settings.AZURE_OPENAI_API_VERSION,
    temperature=0
)

embeddings = AzureOpenAIEmbeddings(
    azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
    azure_ad_token_provider=token_provider,
    azure_deployment=settings.AZURE_OPENAI_EMBED_DEPLOYMENT,
    api_version=settings.AZURE_OPENAI_API_VERSION
)

search_client = SearchClient(
    endpoint=settings.AZURE_SEARCH_ENDPOINT,
    index_name=settings.AZURE_SEARCH_INDEX,
    credential=credential
)

class RagState(TypedDict):
    question: str
    current_query: str
    user_groups: List[str]
    documents: List[str]
    sources: List[str]
    is_relevant: bool
    retries: int
    answer: str

class GradeResult(BaseModel):
    is_relevant: bool = Field(description="True if retrieved documents help answer the question.")

grader_llm = llm.with_structured_output(GradeResult)

def retrieve_node(state: RagState):
    if not state["user_groups"]:
        return {"documents": [], "sources": []}

    query_vector = embeddings.embed_query(state["current_query"])
    group_filter = " or ".join([f"allowed_groups/any(g: g eq '{grp}')" for grp in state["user_groups"]])
    vector_query = VectorizedQuery(vector=query_vector, k_nearest_neighbors=50, fields="content_vector")

    results = search_client.search(
        search_text=state["current_query"],
        vector_queries=[vector_query],
        filter=group_filter,
        query_type=QueryType.SEMANTIC,
        semantic_configuration_name="rag-semantic-config",
        top=5
    )

    seen_parents = set()
    docs, sources = [], []
    for r in results:
        if r["parent_id"] not in seen_parents:
            seen_parents.add(r["parent_id"])
            docs.append(f"[Source: {r['title']}]\n{r['parent_content']}")
            if r["title"] not in sources:
                sources.append(r["title"])

    return {"documents": docs, "sources": sources}

def grade_documents_node(state: RagState):
    if not state["documents"]:
        return {"is_relevant": False}
    context = "\n\n".join(state["documents"])
    prompt = (
        "Assess whether the retrieved context contains factual information needed to answer the question.\n\n"
        f"Question: {state['question']}\n\nContext:\n{context}"
    )
    result = grader_llm.invoke(prompt)
    return {"is_relevant": result.is_relevant}

def rewrite_query_node(state: RagState):
    prompt = (
        "Rewrite this search query to improve keyword and semantic retrieval from corporate documents. "
        "Keep it concise and expand obvious acronyms.\n"
        f"Original: {state['current_query']}"
    )
    better_query = llm.invoke(prompt).content.strip()
    return {"current_query": better_query, "retries": state["retries"] + 1}

def generate_node(state: RagState):
    if not state["is_relevant"] or not state["documents"]:
        return {
            "answer": "I cannot find verified information on this topic within your authorized documents.",
            "sources": []
        }

    context = "\n\n---\n\n".join(state["documents"])
    prompt = (
        "Answer the user's question using ONLY the provided context. "
        "Cite the exact source document using [Source: Title] for every claim. "
        "Do not speculate or use outside knowledge.\n\n"
        f"Context:\n{context}\n\nQuestion: {state['question']}"
    )
    response = llm.invoke(prompt)
    return {"answer": response.content}

def decide_next_step(state: RagState):
    if state["is_relevant"]:
        return "generate"
    return "rewrite" if state["retries"] < 1 else "generate"

workflow = StateGraph(RagState)
workflow.add_node("retrieve", retrieve_node)
workflow.add_node("grade", grade_documents_node)
workflow.add_node("rewrite", rewrite_query_node)
workflow.add_node("generate", generate_node)

workflow.set_entry_point("retrieve")
workflow.add_edge("retrieve", "grade")
workflow.add_conditional_edges("grade", decide_next_step, {"generate": "generate", "rewrite": "rewrite"})
workflow.add_edge("rewrite", "retrieve")
workflow.add_edge("generate", END)

rag_app = workflow.compile()
