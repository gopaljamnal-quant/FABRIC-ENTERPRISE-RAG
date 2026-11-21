# Enterprise Fabric RAG API (Zero-Trust Azure Architecture)

A production-grade Retrieval-Augmented Generation (RAG) backend built with **FastAPI**, **LangGraph**, **Microsoft Fabric OneLake**, **Azure AI Document Intelligence**, **Azure AI Search**, and **Azure OpenAI**.

## Architecture Highlights
- **Zero-Trust Network Isolation:** All Azure resources operate behind Private Endpoints inside a locked-down VNet with public access disabled.
- **Keyless Authentication:** Uses Microsoft Entra ID Managed Identities (`DefaultAzureCredential`)—zero API keys stored in code or config.
- **Layout-Aware Chunking:** Converts complex PDFs/tables to Markdown via Document Intelligence and uses Parent-Child chunking to preserve context.
- **Document-Level Security Trimming:** Filters search results by the user's Entra ID security groups *before* vector/semantic scoring occurs.

---

## Project Structure
```text
fabric-enterprise-rag/
├── app/
│   ├── __init__.py
│   ├── config.py          # Environment settings
│   ├── setup_index.py     # Creates Azure AI Search hybrid + semantic index
│   ├── ingest.py          # Reads OneLake docs + permissions -> Chunks -> Indexes
│   ├── rag_agent.py       # LangGraph Corrective RAG workflow
│   └── main.py            # FastAPI server with Entra ID auth extraction
├── Dockerfile             # Non-root production container
├── requirements.txt       # Python dependencies
├── .env.example           # Local environment variable template
└── README.md
```

---

## Prerequisites
1. **Local Tools:** Python 3.11+, Visual Studio Code, and Azure CLI (`az`).
2. **Network Access:** Your workstation must be connected to your corporate Azure VNet (via Azure VPN Gateway, ExpressRoute, or an internal Jumpbox VM) to reach private endpoints.
3. **Fabric OneLake Setup:**
   - Upload source documents to `Files/raw_documents/` in your Fabric Lakehouse.
   - Upload `document_permissions.csv` to `Files/governance/` with columns:
     ```csv
     file_name,allowed_groups
     ISO_Audit_Policy.pdf,entra-group-guid-1;entra-group-guid-2
     Finance_Report_Q3.docx,entra-group-guid-1
     ```
4. **RBAC Roles Assigned (to your Developer Account & Container App Managed Identity):**
   - **Fabric Workspace:** `Viewer` role.
   - **Azure AI Search:** `Search Index Data Contributor` & `Search Service Contributor`.
   - **Azure OpenAI & Document Intelligence:** `Cognitive Services OpenAI User` & `Cognitive Services User`.

---

## Step-by-Step Local Setup & Testing (VS Code)

### 1. Create Virtual Environment & Install Packages
Open the project folder in VS Code, open a terminal (`Ctrl + ~`), and run:
```bash
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your private Azure endpoints:
```env
ENV_MODE=local_dev
DEV_TEST_GROUPS=entra-group-guid-1,entra-group-guid-2
ALLOWED_ORIGINS=http://localhost:3000

FABRIC_WORKSPACE_NAME=YourFabricWorkspace
FABRIC_LAKEHOUSE_NAME=YourLakehouseName
ONELAKE_DOCS_FOLDER=Files/raw_documents
ONELAKE_PERMISSIONS_CSV=Files/governance/document_permissions.csv

AZURE_DOCINTEL_ENDPOINT=https://<your-docintel>://
AZURE_SEARCH_ENDPOINT=https://<your-search>.search.windows.net
AZURE_SEARCH_INDEX=enterprise-rag-index
AZURE_OPENAI_ENDPOINT=https://<your-openai>://
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o
AZURE_OPENAI_EMBED_DEPLOYMENT=text-embedding-3-large
```

### 3. Authenticate with Azure
Log in via Azure CLI so `DefaultAzureCredential` uses your Entra ID identity:
```bash
az login
```

### 4. Initialize the Search Index (Run Once)
```bash
python -m app.setup_index
```

### 5. Run Document Ingestion from Fabric OneLake
```bash
python -m app.ingest
```

### 6. Start the FastAPI Server Locally
```bash
uvicorn app.main:app --reload --port 8000
```
Open `http://localhost:8000/docs` in your browser to test the `POST /chat` endpoint interactively using Swagger UI.

---

## Production Deployment to Azure Container Apps

1. **Build the Container Image in Azure Container Registry (ACR):**
   ```bash
   az acr build --registry <your-acr-name> --image fabric-rag-api:v1 .
   ```

2. **Deploy to VNet-Isolated Container Apps:**
   ```bash
   az containerapp create \
     --name fabric-rag-api \
     --resource-group rg-enterprise-rag \
     --environment <your-vnet-container-env> \
     --image <your-acr-name>.azurecr.io/fabric-rag-api:v1 \
     --target-port 8000 \
     --ingress internal \
     --system-assigned \
     --env-vars \
       ENV_MODE="production" \
       ALLOWED_ORIGINS="https://internal.com" \
       FABRIC_WORKSPACE_NAME="YourFabricWorkspace" \
       FABRIC_LAKEHOUSE_NAME="YourLakehouseName" \
       AZURE_DOCINTEL_ENDPOINT="https://<your-docintel>://" \
       AZURE_SEARCH_ENDPOINT="https://<your-search>.search.windows.net" \
       AZURE_OPENAI_ENDPOINT="https://<your-openai>://"
   ```

3. **Enable Built-In Entra ID Auth (Easy Auth):**
   In the Azure Portal, go to your Container App -> **Authentication** -> **Add identity provider (Microsoft)** so Azure validates user JWT tokens and injects `X-MS-CLIENT-PRINCIPAL` automatically..