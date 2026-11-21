import csv
import io
import hashlib
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.storage.filedatalake import DataLakeServiceClient
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import DocumentContentFormat
from azure.search.documents import SearchClient
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from openai import AzureOpenAI
from app.config import settings

credential = DefaultAzureCredential()
token_provider = get_bearer_token_provider(credential, "https://azure.com")

# 1. Connect to Microsoft Fabric OneLake
onelake_client = DataLakeServiceClient(
    account_url="https://microsoft.com",
    credential=credential
)
fs_client = onelake_client.get_file_system_client(file_system=settings.FABRIC_WORKSPACE_NAME)

# 2. Connect to Azure AI Services
doc_client = DocumentIntelligenceClient(endpoint=settings.AZURE_DOCINTEL_ENDPOINT, credential=credential)
openai_client = AzureOpenAI(
    azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
    azure_ad_token_provider=token_provider,
    api_version=settings.AZURE_OPENAI_API_VERSION
)
search_client = SearchClient(
    endpoint=settings.AZURE_SEARCH_ENDPOINT,
    index_name=settings.AZURE_SEARCH_INDEX,
    credential=credential
)

def load_permissions_map() -> dict[str, list[str]]:
    """Reads governance CSV from OneLake: filename,group_id_1;group_id_2"""
    perm_path = f"{settings.FABRIC_LAKEHOUSE_NAME}.Lakehouse/{settings.ONELAKE_PERMISSIONS_CSV}"
    file_client = fs_client.get_file_client(perm_path)
    raw_csv = file_client.download_file().readall().decode("utf-8")
    
    permissions = {}
    reader = csv.DictReader(io.StringIO(raw_csv))
    for row in reader:
        groups = [g.strip() for g in row["allowed_groups"].split(";") if g.strip()]
        permissions[row["file_name"].strip()] = groups
    return permissions

def run_ingestion():
    permissions_map = load_permissions_map()
    docs_dir = f"{settings.FABRIC_LAKEHOUSE_NAME}.Lakehouse/{settings.ONELAKE_DOCS_FOLDER}"
    paths = fs_client.get_paths(path=docs_dir)

    md_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "H1"), ("##", "H2"), ("###", "H3")],
        strip_headers=False
    )
    child_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1200,
        chunk_overlap=150,
        separators=["\n\n|", "\n\n", "\n", " ", ""]
    )

    for path in paths:
        if path.is_directory:
            continue

        file_name = path.name.split("/")[-1]
        allowed_groups = permissions_map.get(file_name)
        
        # Strict Zero-Trust: Skip any document missing explicit Entra ID group permissions
        if not allowed_groups:
            print(f"[SKIPPED - NO ACL] {file_name} has no allowed_groups defined.")
            continue

        print(f"Processing '{file_name}'...")
        file_bytes = fs_client.get_file_client(path.name).download_file().readall()

        # Extract layout to Markdown via Azure AI Document Intelligence
        poller = doc_client.begin_analyze_document(
            model_id="prebuilt-layout",
            body=file_bytes,
            output_content_format=DocumentContentFormat.MARKDOWN
        )
        markdown_text = poller.result().content
        parent_docs = md_splitter.split_text(markdown_text)

        batch = []
        for p_idx, parent in enumerate(parent_docs):
            parent_id = hashlib.sha256(f"{file_name}_{p_idx}".encode()).hexdigest()[:16]
            parent_text = parent.page_content
            child_chunks = child_splitter.split_text(parent_text)

            for c_idx, child_text in enumerate(child_chunks):
                emb = openai_client.embeddings.create(
                    input=child_text,
                    model=settings.AZURE_OPENAI_EMBED_DEPLOYMENT
                )
                batch.append({
                    "chunk_id": f"{parent_id}_{c_idx}",
                    "parent_id": parent_id,
                    "title": file_name,
                    "content": child_text,
                    "parent_content": parent_text,
                    "allowed_groups": allowed_groups,
                    "content_vector": emb.data.embedding
                })

        if batch:
            # Upload in chunks of 100 to stay within payload limits
            for i in range(0, len(batch), 100):
                search_client.upload_documents(documents=batch[i:i+100])
            print(f"[INDEXED] {len(batch)} chunks for '{file_name}'.")

if __name__ == "__main__":
    run_ingestion()
