# 📋 Ambient Expense Agent: Deployment & Setup Summary

This document summarizes all the steps, commands, and configurations performed to successfully build, configure, and deploy the **Ambient Expense Agent** system on Google Cloud.

---

## 🛠️ Step-by-Step Action Log

### Phase 1: Local Setup & Scaffolding
1. **Scaffolded Agent Runtime deployment files**:
   Added the necessary configuration files for Agent Runtime deployment using `agents-cli`:
   ```bash
   agents-cli scaffold enhance . --deployment-target agent_runtime --agent-directory expense_agent
   ```
2. **Updated Agent Configurations**:
   - Set the agent region to `us-central1` in [agents-cli-manifest.yaml](file:///Users/aryalkatkar/Desktop/day4.1/ambient-expense-agent/agents-cli-manifest.yaml) and [env.tfvars](file:///Users/aryalkatkar/Desktop/day4.1/ambient-expense-agent/deployment/terraform/single-project/vars/env.tfvars).
   - Changed the LLM model in [config.py](file:///Users/aryalkatkar/Desktop/day4.1/ambient-expense-agent/expense_agent/config.py) to `gemini-2.5-flash` to resolve compute engine service account permission constraints.
3. **Locked Python Dependencies**:
   ```bash
   uv lock
   ```

---

### Phase 2: Agent Runtime Deployment
1. **Validated configuration with a dry-run**:
   ```bash
   agents-cli deploy --dry-run --project YOUR_PROJECT_ID
   ```
2. **Deployed the agent to Vertex AI Agent Runtime**:
   ```bash
   agents-cli deploy --project YOUR_PROJECT_ID
   ```
   * **Resulting Agent Runtime ID**: `projects/YOUR_PROJECT_NUMBER/locations/us-central1/reasoningEngines/YOUR_ENGINE_ID`

---

### Phase 3: Pub/Sub Event Ingestion Pipeline
We set up an asynchronous event ingestion pipeline using Google Cloud Pub/Sub:
1. **Created Pub/Sub Topics**:
   ```bash
   gcloud pubsub topics create expense-reports --project=YOUR_PROJECT_ID
   gcloud pubsub topics create expense-reports-dead-letter --project=YOUR_PROJECT_ID
   ```
2. **Created Push Invoker Service Account**:
   ```bash
   gcloud iam service-accounts create pubsub-invoker --display-name="Pub/Sub Invoker Service Account" --project=YOUR_PROJECT_ID
   ```
3. **Granted Invocation Permissions**:
   ```bash
   gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
       --member="serviceAccount:pubsub-invoker@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
       --role="roles/aiplatform.user"
   ```
4. **Authorized Pub/Sub to generate OIDC tokens**:
   ```bash
   gcloud iam service-accounts add-iam-policy-binding pubsub-invoker@YOUR_PROJECT_ID.iam.gserviceaccount.com \
       --member="serviceAccount:service-YOUR_PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com" \
       --role="roles/iam.serviceAccountTokenCreator" \
       --project=YOUR_PROJECT_ID
   ```
5. **Granted Dead-Letter Publishing Permissions**:
   ```bash
   gcloud pubsub topics add-iam-policy-binding expense-reports-dead-letter \
       --member="serviceAccount:service-YOUR_PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com" \
       --role="roles/pubsub.publisher" \
       --project=YOUR_PROJECT_ID
   ```
6. **Created the Push Subscription**:
   Points directly to the Agent Runtime `:query` REST API, unwraps the payload, has a 10-minute ack deadline, and routes to the dead-letter topic after 5 failed attempts:
   ```bash
   gcloud pubsub subscriptions create expense-reports-push \
       --topic=expense-reports \
       --push-endpoint="https://us-central1-aiplatform.googleapis.com/v1/projects/YOUR_PROJECT_NUMBER/locations/us-central1/reasoningEngines/YOUR_ENGINE_ID:query" \
       --push-no-wrapper \
       --push-auth-service-account="pubsub-invoker@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
       --push-auth-token-audience="https://us-central1-aiplatform.googleapis.com/v1/projects/YOUR_PROJECT_NUMBER/locations/us-central1/reasoningEngines/YOUR_ENGINE_ID:query" \
       --ack-deadline=600 \
       --dead-letter-topic=expense-reports-dead-letter \
       --max-delivery-attempts=5 \
       --project=YOUR_PROJECT_ID
   ```
7. **Granted Subscription Acknowledgment Permissions**:
   ```bash
   gcloud pubsub subscriptions add-iam-policy-binding expense-reports-push \
       --member="serviceAccount:service-YOUR_PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com" \
       --role="roles/pubsub.subscriber" \
       --project=YOUR_PROJECT_ID
   ```

---

### Phase 4: Manager Dashboard & Cloud Run Deployment
We developed a standalone FastAPI manager dashboard under the `submission_frontend/` directory and deployed it to Cloud Run:
1. **Wrote the Dashboard backend & frontend**:
   - [main.py](file:///Users/aryalkatkar/Desktop/day4.1/ambient-expense-agent/submission_frontend/main.py): Queries the `VertexAiSessionService` to find unresolved interrupts and resumes them using `client.agent_engines._stream_query`.
   - [dashboard.html](file:///Users/aryalkatkar/Desktop/day4.1/ambient-expense-agent/submission_frontend/templates/dashboard.html): A premium glassmorphic UI to list pending approvals and submit decisions.
2. **Created the Dockerfile**:
   Configured [Dockerfile](file:///Users/aryalkatkar/Desktop/day4.1/ambient-expense-agent/submission_frontend/Dockerfile) to build the FastAPI app container.
3. **Deployed to Cloud Run**:
   ```bash
   gcloud run deploy expense-manager-dashboard \
       --source submission_frontend \
       --region us-central1 \
       --allow-unauthenticated \
       --set-env-vars GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID,AGENT_RUNTIME_ID=projects/YOUR_PROJECT_NUMBER/locations/us-central1/reasoningEngines/YOUR_ENGINE_ID
   ```
   * **Dashboard URL**: `https://expense-manager-dashboard-YOUR_PROJECT_NUMBER.us-central1.run.app`
4. **Granted Cloud Run Service Account Permissions**:
   Allowed the dashboard to query and resume Agent Runtime sessions:
   ```bash
   gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
       --member="serviceAccount:YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
       --role="roles/aiplatform.user"
   ```

---

### Phase 5: Workflow Order Optimization (Human-in-the-Loop First)
To improve the user experience in the chat playground and dashboard, we restructured the workflow graph:
1. **Swapped Node Order**:
   Modified [agent.py](file:///Users/aryalkatkar/Desktop/day4.1/ambient-expense-agent/expense_agent/agent.py) so `human_review` executes before `risk_analyzer`.
2. **Added `rerun_on_resume=True`**:
   Decorated the `human_review` function with `@node(rerun_on_resume=True)` so that when a session is resumed, the workflow engine executes the node's code, processes the manager's decision, and routes the execution forward rather than fast-forwarding it.
3. **Redeployed the updated Agent**:
   ```bash
   agents-cli deploy --project YOUR_PROJECT_ID
   ```

---

### Phase 6: E2E Verification & Testing

#### 1. Verifying via CLI
- **Initial run**:
  ```bash
  agents-cli run --url https://us-central1-aiplatform.googleapis.com/v1/projects/YOUR_PROJECT_NUMBER/locations/us-central1/reasoningEngines/YOUR_ENGINE_ID --mode adk '{"amount": 150.0, "submitter": "user@example.com", "category": "meals", "description": "Client dinner", "date": "2026-06-04"}'
  ```
  *Result*: The agent prints the alert message and pauses, yielding a Session ID.
- **Resuming run**:
  ```bash
  agents-cli run "yes" --session-id <SESSION_ID> --url https://us-central1-aiplatform.googleapis.com/v1/projects/YOUR_PROJECT_NUMBER/locations/us-central1/reasoningEngines/YOUR_ENGINE_ID --mode adk
  ```
  *Result*: The agent resumes, executes the LLM risk assessment, and prints the final approval outcome.

#### 2. Verifying via Dashboard / Cloud Playground
- Submit the `$150` expense in the Vertex AI Agent Playground.
- Click **Approve** on the Cloud Run Dashboard.
- The session resumes, executes the LLM risk assessment, and completes.
- Refreshing the Agent Playground chat displays the risk assessment details and the final approved outcome.
