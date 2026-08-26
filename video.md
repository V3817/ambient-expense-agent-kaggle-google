# 📹 Ambient Expense Agent: Video Production Guide & Script

This guide is designed to help you record a highly compelling, **5-minute (or less)** demonstration video for your Kaggle Capstone Project submission. 

---

## ⏱️ Video Structure & Timeline

| Section | Duration | Focus |
|---|---|---|
| **1. The Pitch & Problem** | 0:00 - 0:45 (45s) | Explain why expense reports are broken and introduce the Ambient Agent. |
| **2. Architecture Overview** | 0:45 - 1:30 (45s) | Walk through the Mermaid sequence diagram (Pub/Sub + Agent Runtime + Dashboard). |
| **3. Live Demo: Auto-Approve** | 1:30 - 2:15 (45s) | Show publishing a < $100 expense and it auto-approving instantly in the logs. |
| **4. Live Demo: Human-in-the-Loop** | 2:15 - 3:45 (90s) | Show publishing a >= $100 expense, pausing, appearing on the Dashboard, and resuming. |
| **5. Technical Highlights & Outro** | 3:45 - 5:00 (75s) | Explain `rerun_on_resume=True` and the zero-trust OIDC security model. |

---

## 🖥️ What to Prepare (Screencast Setup)

Before you start recording, open the following tabs and windows on your screen:
1. **Tab 1**: The **Manager Dashboard** (deployed on Cloud Run).
2. **Tab 2**: The **Vertex AI Agent Playground** (Google Cloud Console).
3. **Tab 3**: The **Mermaid Sequence Diagram** (from [README.md](file:///Users/aryalkatkar/Desktop/day4.1/ambient-expense-agent/README.md) or [write_up.md](file:///Users/aryalkatkar/Desktop/day4.1/ambient-expense-agent/write_up.md)).
4. **Terminal Window**: Split into two panes:
   - *Pane 1*: A command ready to publish a `$50` expense to Pub/Sub.
   - *Pane 2*: A command ready to publish a `$150` expense to Pub/Sub.

---

## 🎙️ Voiceover Script & Visual Cues

### Section 1: The Pitch & Problem (0:00 - 0:45)
* **Visual**: Show your face on camera, or show the premium **Manager Dashboard** homepage.
* **What to Speak**:
  > "Hi everyone! Welcome to my Capstone Project for the Kaggle 5-Day AI Agents course. Today, I'm excited to show you the **Ambient Expense Agent**.
  >
  > In most companies, expense management is a slow, manual bottleneck. Managers waste time approving minor $15 coffee receipts, while high-value expenses often lack thorough context-aware risk analysis. 
  > 
  > To solve this, I built an ambient, event-driven agent that runs silently in the background. It auto-approves low-risk receipts instantly, but seamlessly loops in managers for high-value expenses, conducting an intelligent AI risk assessment only after the manager gives the green light."

---

### Section 2: Architecture Overview (0:45 - 1:30)
* **Visual**: Switch to the **Mermaid Sequence Diagram** in your README.
* **What to Speak**:
  > "Let's look at how the system works under the hood. 
  > 
  > 1. When an employee submits an expense, it is published to a **Google Cloud Pub/Sub** topic.
  > 2. An OIDC-authenticated **Push Subscription** delivers the raw payload directly to our agent hosted on **Vertex AI Agent Runtime**.
  > 3. If the expense is under $100, the agent auto-approves it. If it's $100 or more, the agent saves its state in the **Vertex AI Session Service**, yields a `RequestInput` interrupt, and pauses.
  > 4. Our **Manager Dashboard**—hosted on **Cloud Run**—polls the Session Service for pending approvals. 
  > 5. When the manager clicks Approve, the dashboard securely resumes the session, triggering a `gemini-2.5-flash` model to perform a context-aware risk analysis before finalizing the outcome."

---

### Section 3: Live Demo - Auto-Approval (1:30 - 2:15)
* **Visual**: Switch to your Terminal window.
* **What to Speak**:
  > "Let's see it in action. I will publish a low-value expense of **$50** for a lunch receipt to the Pub/Sub topic."
* **Action**: Run the `$50` Pub/Sub publish command:
  ```bash
  gcloud pubsub topics publish expense-reports --message='{"input": {"user_id": "user-1", "message": "{\"amount\": 50.0, \"submitter\": \"user@example.com\", \"category\": \"meals\", \"description\": \"Lunch\", \"date\": \"2026-06-04\"}"}, "class_method": "query"}'
  ```
* **What to Speak**:
  > "The message is published. Behind the scenes, the push subscription triggers the Agent Runtime. Since the amount is under $100, the agent auto-approves the transaction instantly in the background without any manual routing or LLM cost."

---

### Section 4: Live Demo - Human-in-the-Loop (2:15 - 3:45)
* **Visual**: Switch back to the Terminal.
* **What to Speak**:
  > "Now, let's publish a high-value expense of **$150** for a client dinner."
* **Action**: Run the `$150` Pub/Sub publish command:
  ```bash
  gcloud pubsub topics publish expense-reports --message='{"input": {"user_id": "user-2", "message": "{\"amount\": 150.0, \"submitter\": \"user@example.com\", \"category\": \"meals\", \"description\": \"Client dinner\", \"date\": \"2026-06-04\"}"}, "class_method": "query"}'
  ```
* **What to Speak**:
  > "This expense exceeds our threshold. The agent has received the event, yielded an alert, and paused. Let's open our Manager Dashboard."
* **Action**: Switch to the **Manager Dashboard** tab and click **Refresh** (or wait for auto-poll). The new `$150` pending card will appear.
* **What to Speak**:
  > "As you can see, the pending card for the $150 client dinner appears on our glassmorphic dashboard. I will click **Approve**."
* **Action**: Click the **Approve** button on the card.
* **What to Speak**:
  > "When I clicked approve, the dashboard sent a secure resume request to the Vertex AI Agent Runtime. Let's look at the Agent Playground in the Cloud Console to see the result."
* **Action**: Switch to the **Vertex AI Agent Playground** tab, refresh the page, and show the completed session history.
* **What to Speak**:
  > "The session has resumed successfully! The agent invoked Gemini to perform a risk assessment—explaining that $150 is reasonable for a client dinner—and recorded the final approved outcome."

---

### Section 5: Technical Highlights & Outro (3:45 - 5:00)
* **Visual**: Switch to your IDE (VS Code / cursor) showing `expense_agent/agent.py`.
* **What to Speak**:
  > "To build this, I leveraged key concepts from the Kaggle course. 
  > 
  > First, the **ADK Graph Workflow API** was used to manage the state machine and handle the pause-and-resume interrupts. 
  >
  > Second, we implemented a critical optimization: **Human-in-the-Loop First**. The agent pauses *before* running the LLM, saving token costs on expenses that get rejected anyway. To make this work, I configured the `human_review` node with `rerun_on_resume=True` so that the node's code executes on resumption to process the decision and route the graph.
  > 
  > Finally, the system is highly secure. We use **OIDC token authentication** for the Pub/Sub push subscription, ensuring only authorized Google Cloud events can trigger our agent.
  > 
  > Thank you for watching! All code and deployment playbooks are available on my GitHub repository linked below."

---

## 🏆 Key Concepts to Emphasize (Kaggle Evaluation Checklist)

Make sure your video explicitly mentions or shows these three concepts to get maximum points:
1. **Agent Workflow (ADK)**: Mention the **ADK Graph API** and show the `edges` definition in `agent.py`.
2. **Security**: Mention the **OIDC token authentication** on the Pub/Sub push subscription.
3. **Deployability**: Mention that the agent is deployed as a **Vertex AI Reasoning Engine** (Agent Runtime) and the dashboard is on **Cloud Run**.
