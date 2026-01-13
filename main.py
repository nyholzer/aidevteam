import os
import time
import shutil
from crewai import Agent, Task, Crew, LLM
from crewai_tools import FileWriterTool, FileReadTool
from git import Repo
import subprocess
import urllib.request
import urllib.error

# 1. SETUP
# ---------------------------------------------------------
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
LOGS_DIR = "./logs"

# Ensure directories exist
for d in DIRS.values():
    os.makedirs(d, exist_ok=True)
if not os.path.exists(WORKSPACE_DIR):
    os.makedirs(WORKSPACE_DIR)
if not os.path.exists(LOGS_DIR):
    os.makedirs(LOGS_DIR)

# Git Setup
try:
    repo = Repo('.')
except:
    repo = Repo.init('.')

# Tools
file_writer = FileWriterTool(directory=WORKSPACE_DIR)
file_reader = FileReadTool(directory=WORKSPACE_DIR)

# Logging Helper
def log_agent_step(step_output):
    """
    Callback to log agent thought process to a file.
    """
    logfile = os.path.join(LOGS_DIR, "activity.log")
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    
    # step_output is typically a tuple or object from CrewAI, 
    # we'll try to extract relevant text (thought/tool/result).
    # CrewAI step_callback receives the AgentStep object.
    
    try:
        # Depending on CrewAI version, this might vary.
        # We'll log the raw output or formatted message.
        log_message = f"[{timestamp}] {step_output}\n"
        
        # If it's an object with a 'thought' or 'result' attribute:
        if hasattr(step_output, 'thought'):
            log_message = f"[{timestamp}] [THOUGHT] {step_output.thought}\n"
        if hasattr(step_output, 'tool'):
            log_message += f"    [TOOL] Using {step_output.tool} with input: {step_output.tool_input}\n"
        if hasattr(step_output, 'result'):
            log_message += f"    [RESULT] {step_output.result}\n"
            
    except Exception as e:
        log_message = f"[{timestamp}] [RAW] {str(step_output)}\n"

    with open(logfile, "a") as f:
        f.write(log_message)
    
    # Also print to stdout for visibility if running interactively
    # Also print to stdout for visibility if running interactively
    print(log_message.strip())

# Ollama Check
def ensure_ollama_running():
    print("[INIT] Checking Ollama status...")
    url = "http://localhost:11434"
    
    # Try connecting
    try:
        urllib.request.urlopen(url, timeout=1)
        print("[INIT] Ollama is running.")
        return
    except (urllib.error.URLError, ConnectionRefusedError):
        pass

    # Not running, attempt to start
    print("[INIT] Ollama not found. Attempting to start 'ollama serve'...")
    try:
        # Start in background
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        print("[ERROR] 'ollama' command not found. Please install Ollama (https://ollama.com) or start it manually.")
        return

    # Wait for startup
    print("[INIT] Waiting for Ollama to start...", end="", flush=True)
    for _ in range(30):
        try:
            urllib.request.urlopen(url, timeout=1)
            print(" Done!")
            return
        except:
            time.sleep(1)
            print(".", end="", flush=True)
            
    print("\\n[ERROR] Timed out waiting for Ollama to start. Please check logs or start manually.")

# 2. LLM & AGENTS
# ---------------------------------------------------------
# Using local Ollama models for cost/privacy/hardware reasons
logic_llm = LLM(model="ollama/phi3:mini", base_url="http://localhost:11434")
coding_llm = LLM(model="ollama/phi3:mini", base_url="http://localhost:11434")

spec_architect = Agent(
    role='Spec Architect',
    goal='Analyze user requirements and create a technical execution plan.',
    backstory='You are a senior technical lead. You digest the high-level request and create atomic developer tasks.',
    llm=logic_llm,
    verbose=True,
    step_callback=log_agent_step
)

full_stack_dev = Agent(
    role='Full Stack Developer',
    goal='Write clean, functional code based on the technical plan.',
    backstory='You are a pragmatic developer. You write code to the workspace using tools.',
    llm=coding_llm,
    tools=[file_writer, file_reader],
    verbose=True,
    step_callback=log_agent_step
)

qa_engineer = Agent(
    role='QA Engineer',
    goal='Verify that all planned files were actually created and contain real, functional code (not hallucinations or placeholder content).',
    backstory='You are a meticulous QA engineer. You validate that deliverables exist AND are implemented correctly. You read files, check code logic, and run tests.',
    llm=coding_llm,
    tools=[file_reader],
    verbose=True,
    step_callback=log_agent_step
)

test_engineer = Agent(
    role='Test Engineer',
    goal='Create comprehensive tests based on requirements to validate implementation before and after development.',
    backstory='You are a TDD advocate. You write test cases that verify the ticket requirements are met. Tests must be runnable and catch real bugs.',
    llm=coding_llm,
    tools=[file_writer, file_reader],
    verbose=True,
    step_callback=log_agent_step
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

    # Define Crew Tasks - TEST DRIVEN DEVELOPMENT WORKFLOW
    plan_task = Task(
        description=f"Analyze this ticket:\n{ticket_content}\nCreate a step-by-step implementation plan with clear success criteria.",
        expected_output="A detailed plan listing files to create, code logic, and testable success criteria.",
        agent=spec_architect
    )

    test_task = Task(
        description="Based on the plan, create test cases and test files that verify all requirements. Write these tests to ./workspace/tests/ directory. Tests must be specific and catch real bugs.",
        expected_output="Test files written to ./workspace/tests/ that validate the requirements.",
        agent=test_engineer,
        context=[plan_task]
    )

    build_task = Task(
        description="Implement the code based on the plan. Write actual, functional code to ./workspace/ directory. Make sure tests pass.",
        expected_output="Source code files written to disk that pass all tests.",
        agent=full_stack_dev,
        context=[plan_task, test_task]
    )

    qa_task = Task(
        description=f"CRITICAL: Read EVERY file created in ./workspace/ (excluding tests). Verify:\n1. Files actually exist\n2. Code is NOT empty, placeholder, or hallucinated\n3. Code implements the plan logically\n4. Tests pass when run\n5. No 'TODO' or incomplete sections remain\nReport any issues found.",
        expected_output="Detailed QA report: list each file, confirm it has real code, note any issues. If anything is missing or hallucinated, explicitly say 'FAILED: [reason]'",
        agent=qa_engineer,
        context=[plan_task, test_task, build_task]
    )

    crew = Crew(
        agents=[spec_architect, test_engineer, full_stack_dev, qa_engineer],
        tasks=[plan_task, test_task, build_task, qa_task],
        verbose=True
    )

    # Execute
    result = crew.kickoff()
    
    # Convert result to string (CrewOutput object)
    qa_result = str(result) if result else ""
    test_failed = "failed:" in qa_result.lower() or "missing" in qa_result.lower() or "not found" in qa_result.lower() or "hallucinated" in qa_result.lower() or "empty" in qa_result.lower()
    
    retry_count = 0
    while test_failed and retry_count < 2:
        retry_count += 1
        print(f"\n[QA FEEDBACK] Issues detected on attempt {retry_count}:")
        print(qa_result)
        print(f"\n[RETRY] Asking Full Stack Dev to fix based on QA feedback...")
        
        # Create a fix task with explicit QA feedback
        fix_task = Task(
            description=f"""The QA Engineer found these issues with your code:

{qa_result}

Please fix EVERY issue mentioned above. Re-read the plan and ensure:
1. All required files are created
2. All code is real and functional (not placeholder or hallucinated)
3. Files are in the correct locations
4. Tests pass
5. No empty sections or TODOs

Save corrected files to ./workspace/ directory.""",
            expected_output="All issues fixed. Code is complete and ready for re-validation.",
            agent=full_stack_dev,
            context=[plan_task, test_task]
        )
        
        # Re-run fix + QA validation
        retry_crew = Crew(
            agents=[full_stack_dev, qa_engineer],
            tasks=[fix_task, qa_task],
            verbose=True
        )
        result = retry_crew.kickoff()
        qa_result = str(result) if result else ""
        test_failed = "failed:" in qa_result.lower() or "missing" in qa_result.lower() or "not found" in qa_result.lower() or "hallucinated" in qa_result.lower() or "empty" in qa_result.lower()

    # Append Report
    report = f"\n\n## AI Report\n**Status**: {'Implementation Complete.' if not test_failed else 'Completed with issues - manual review needed.'}\n**Summary**: {result}\n\n**Instructions**: Review the files in `workspace/`. If satisfied, change [ ] Approved to [x] Approved below (or just write 'Status: Approved').\n[ ] Approved"
    
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
    
    # Check Ollama
    ensure_ollama_running()
    
    print(f"Monitoring {DIRS['todo']}...")
    
    while True:
        # 1. Check In Progress (priority - resume interrupted tickets first)
        # sorted() ensures lexicographical order i.e. 001, 002, 003...
        in_progress_files = sorted([f for f in os.listdir(DIRS["in_progress"]) if f.endswith(".md")])
        if in_progress_files:
            print(f"\n[KANBAN] Resuming in-progress ticket: {in_progress_files[0]}")
            process_ticket(os.path.join(DIRS["in_progress"], in_progress_files[0]))
            continue
        
        # 2. Check Todo
        # sorted() ensures lexicographical order i.e. 001, 002, 003...
        todo_files = sorted([f for f in os.listdir(DIRS["todo"]) if f.endswith(".md")])
        if todo_files:
            process_ticket(os.path.join(DIRS["todo"], todo_files[0]))
            continue # Immediately look for next task if one finished (or check review)
        
        # 3. Check Approvals
        check_approvals()

        # Sleep to avoid CPU spin
        time.sleep(2)

if __name__ == "__main__":
    run_loop()