from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Fabric OneLake Configuration
    FABRIC_WORKSPACE_NAME: str
    FABRIC_LAKEHOUSE_NAME: str
    ONELAKE_DOCS_FOLDER: str = "Files/raw_documents"
    ONELAKE_PERMISSIONS_CSV: str = "Files/governance/document_permissions.csv"

    # Azure AI Endpoints (Private Endpoints)
    AZURE_DOCINTEL_ENDPOINT: str
    AZURE_SEARCH_ENDPOINT: str
    AZURE_SEARCH_INDEX: str = "enterprise-rag-index"
    AZURE_OPENAI_ENDPOINT: str
    AZURE_OPENAI_CHAT_DEPLOYMENT: str = "gpt-4o"
    AZURE_OPENAI_EMBED_DEPLOYMENT: str = "text-embedding-3-large"
    AZURE_OPENAI_API_VERSION: str = "2024-06-01"

    class Config:
        env_file = ".env"

settings = Settings()
