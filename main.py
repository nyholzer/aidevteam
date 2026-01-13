import os
import time
import shutil
from crewai import Agent, Task, Crew, LLM
from crewai_tools import FileWriterTool, FileReadTool
from git import Repo

# 1. SETUP
# ---------------------------------------------------------
TICKETS_DIR = "./tickets"
DIRS = {
    "todo": os.path.join(TICKETS_DIR, "todo"),
    "in_progress": os.path.join(TICKETS_DIR, "in_progress"),
    "in_review": os.path.join(TICKETS_DIR, "in_review"),
    "done": os.path.join(TICKETS_DIR, "done"),
}
WORKSPACE_DIR = "./workspace"

# Ensure directories exist
for d in DIRS.values():
    os.makedirs(d, exist_ok=True)
if not os.path.exists(WORKSPACE_DIR):
    os.makedirs(WORKSPACE_DIR)

# Git Setup
try:
    repo = Repo('.')
except:
    repo = Repo.init('.')

# Tools
file_writer = FileWriterTool(directory=WORKSPACE_DIR)
file_reader = FileReadTool(directory=WORKSPACE_DIR)

# 2. LLM & AGENTS
# ---------------------------------------------------------
# Using local Ollama models for cost/privacy/hardware reasons
logic_llm = LLM(model="ollama/llama3.2:latest", base_url="http://localhost:11434")
coding_llm = LLM(model="ollama/phi3:mini", base_url="http://localhost:11434")

spec_architect = Agent(
    role='Spec Architect',
    goal='Analyze user requirements and create a technical execution plan.',
    backstory='You are a senior technical lead. You digest the high-level request and create atomic developer tasks.',
    llm=logic_llm,
    verbose=True
)

full_stack_dev = Agent(
    role='Full Stack Developer',
    goal='Write clean, functional code based on the technical plan.',
    backstory='You are a pragmatic developer. You write code to the workspace using tools.',
    llm=coding_llm,
    tools=[file_writer, file_reader],
    verbose=True
)

# 3. KANBAN LOGIC
# ---------------------------------------------------------

def process_ticket(ticket_path):
    filename = os.path.basename(ticket_path)
    in_progress_path = os.path.join(DIRS["in_progress"], filename)
    
    print(f"\n[KANBAN] Picking up: {filename}")
    shutil.move(ticket_path, in_progress_path)

    # Read Ticket Content
    with open(in_progress_path, 'r') as f:
        ticket_content = f.read()

    # Define Crew Tasks
    plan_task = Task(
        description=f"Analyze this ticket:\n{ticket_content}\nCreate a step-by-step implementation plan.",
        expected_output="A list of files to create and the logic for each.",
        agent=spec_architect
    )

    build_task = Task(
        description="Implement the code based on the plan. Save files to ./workspace/ directory.",
        expected_output="Source code files written to disk.",
        agent=full_stack_dev,
        context=[plan_task]
    )

    crew = Crew(
        agents=[spec_architect, full_stack_dev],
        tasks=[plan_task, build_task],
        verbose=True
    )

    # Execute
    result = crew.kickoff()

    # Append Report
    report = f"\n\n## AI Report\n**Status**: Implementation Complete.\n**Summary**: {result}\n\n**Instructions**: Review the files in `workspace/`. If satisfied, change [ ] Approved to [x] Approved below (or just write 'Status: Approved').\n[ ] Approved"
    
    with open(in_progress_path, 'a') as f:
        f.write(report)

    # Move to Review
    in_review_path = os.path.join(DIRS["in_review"], filename)
    shutil.move(in_progress_path, in_review_path)
    print(f"[KANBAN] Moved to Review: {filename}")

def check_approvals():
    for filename in os.listdir(DIRS["in_review"]):
        if not filename.endswith(".md"): continue
        
        path = os.path.join(DIRS["in_review"], filename)
        with open(path, 'r') as f:
            content = f.read()
        
        # Check for approval signature
        if "[x] Approved" in content or "Status: Approved" in content:
            print(f"\n[KANBAN] Approval Detected: {filename}")
            
            # Move to Done
            done_path = os.path.join(DIRS["done"], filename)
            shutil.move(path, done_path)
            
            # Git Commit
            try:
                repo.git.add(A=True)
                repo.index.commit(f"Completed Ticket: {filename}")
                print(f"[GIT] Snapshot saved.")
            except Exception as e:
                print(f"[GIT] Warning: {e}")

def run_loop():
    print("--- AI Dev Team Started ---")
    print(f"Monitoring {DIRS['todo']}...")
    
    while True:
        # 1. Check Todo
        todo_files = sorted([f for f in os.listdir(DIRS["todo"]) if f.endswith(".md")])
        if todo_files:
            process_ticket(os.path.join(DIRS["todo"], todo_files[0]))
            continue # Immediately look for next task if one finished (or check review)
        
        # 2. Check Approvals
        check_approvals()

        # Sleep to avoid CPU spin
        time.sleep(2)

if __name__ == "__main__":
    run_loop()