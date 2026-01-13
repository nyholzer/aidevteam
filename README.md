# AI Dev Team (Local CPU Edition)

A file-system based Kanban board for orchestrating AI agents to build software using local LLMs (Ollama).

## 🚀 Overview

This system transforms your VS Code file explorer into a project management tool. You "manage" AI agents simply by moving markdown files between directories.

**Key Features:**
- **Privacy First**: Runs 100% locally using Ollama.
- **No API Costs**: Uses open-source models via Ollama.
- **Kanban Workflow**: `Todo` -> `In Progress` -> `In Review` -> `Done`.
- **Auto-Approval**: Marking a ticket as `[x] Approved` triggers an automatic Git commit.

## 🛠️ Setup

1.  **Prerequisites**:
    - [Ollama](https://ollama.com/) installed and running.
    - Python 3.12+
    - Pull required models (defaults are configured in `main.py`):
      ```bash
      ollama pull neural-chat:7b
      ```
    - Install pytest (used for automated test runs):
      ```bash
      pip install pytest
      ```

2.  **Installation**:
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ```

3.  **Run**:
    ```bash
    python main.py
    ```

## 📋 usage (The Workflow)

1.  **Create a Task**:
    - Create a new file in `tickets/todo/` (e.g., `feature-login.md`).
    - Describe what you want built. Paste plans from Gemini/ChatGPT here.

2.  **AI Works**:
    - The system detects the file and moves it to `tickets/in_progress/`.
    - Agents analyze the spec and generate code in the `workspace/` folder.
    - Automated checks verify that files exist and `pytest` passes before a ticket can move to review.
    - **Note**: This can take minutes on CPU.

3.  **Review**:
    - When finished, the AI moves the ticket to `tickets/in_review/`.
    - Open the file. You will see a `## AI Report` appended to the bottom.
    - Inspect the generated code in `workspace/`.

4.  **Approve**:
    - To accept the work, edit the ticket file and add the following line anywhere (or check the box if present):
      ```markdown
      [x] Approved
      ```
    - Save the file.
    - The system moves it to `tickets/done/` and **automatically commits** to Git.

## ⚠️ Limitations

- **Hardware Speed**: Since this is optimized for a 64GB CPU (no GPU), generation speed is significantly slower than cloud APIs. A complex task might take 5-10 minutes.
- **Model Intelligence**: Smaller local models (Phi-3, Llama 3) are capable but not perfect. They may make syntax errors or hallucinate libraries. Logic checks are recommended.
- **Context Window**: Extremely large files or very long conversation histories may exceed the context window of local models. Keep tasks atomic (one feature per ticket).
- **Single Threaded**: Currently processes one ticket at a time to avoid melting your CPU.

## 📂 Directory Structure

```text
.
├── tickets/
│   ├── todo/         # Inbox
│   ├── in_progress/  # AI busy processing
│   ├── in_review/    # Waiting for you
│   └── done/         # Completed & Committed
├── workspace/        # Generated Source Code
└── main.py           # Orchestrator
```
