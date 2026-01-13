import os
import time
import shutil
import warnings
from crewai import Agent, Task, Crew, LLM
from crewai_tools import FileWriterTool, FileReadTool
from git import Repo
import subprocess
import urllib.request
import urllib.error

# Force CPU-only mode for Ollama (disable GPU to prevent crashes)
os.environ["OLLAMA_NUM_GPU"] = "0"
# Enable CrewAI tracing to capture raw LLM outputs for debugging
os.environ["CREWAI_TRACING_ENABLED"] = "true"

# Suppress Pydantic warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

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


def call_file_writer_from_dict(payload: dict) -> dict:
    """
    Normalize a payload dict and call the FileWriterTool correctly.

    Accepts keys: filename, directory or path, overwrite, content.
    Normalizes relative directories to live under WORKSPACE_DIR.
    Returns a dict with status and target path or error.
    """
    try:
        fn = payload.get("filename")
        if not fn:
            return {"ok": False, "error": "missing filename"}

        # map aliases
        dir_in = payload.get("directory") or payload.get("path") or "./"

        # Normalize directory into workspace if relative
        if dir_in == "." or dir_in == "./" or not os.path.isabs(dir_in):
            # strip leading ./
            rel = dir_in[2:] if dir_in.startswith("./") else (dir_in.lstrip("./") or "")
            target_dir = os.path.normpath(os.path.join(WORKSPACE_DIR, rel))
        else:
            target_dir = dir_in

        os.makedirs(target_dir, exist_ok=True)

        # Prepare args for file_writer.run
        args = {
            "filename": fn,
            "directory": target_dir,
            "overwrite": payload.get("overwrite", True),
            "content": payload.get("content", ""),
        }

        # use the run(**kwargs) API
        res = file_writer.run(**args)

        # Determine written path
        written = os.path.join(target_dir, fn)
        return {"ok": True, "path": os.path.relpath(written), "detail": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}

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
    print("[INIT] Running in CPU-only mode (OLLAMA_NUM_GPU=0)")
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
        # Start in background with CPU-only mode
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
    print("[INFO] Tip: Start with CPU-only: OLLAMA_NUM_GPU=0 ollama serve")

# 2. LLM & AGENTS
# ---------------------------------------------------------
# Using local Ollama models for cost/privacy/hardware reasons
# neural-chat:7b with stricter prompts, temperature=0, and enhanced fallback for JSON tool-calling
logic_llm = LLM(model="ollama/neural-chat:7b", base_url="http://localhost:11434", temperature=0)
coding_llm = LLM(model="ollama/neural-chat:7b", base_url="http://localhost:11434", temperature=0)

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
    goal='Write clean, functional code based on the technical plan. MUST actually create files using the File Writer Tool.',
    backstory='You are a pragmatic developer. You MUST write code to disk using the File Writer Tool. Do NOT describe what you would do - ACTUALLY DO IT by calling the tool with filename, content, and directory.',
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
    
    try:
        _execute_crew_workflow(ticket_content, in_progress_path, filename)
    except Exception as e:
        print(f"[ERROR] Crew execution failed: {e}")
        print("[INFO] Moving ticket back to todo for retry...")
        shutil.move(in_progress_path, os.path.join(DIRS["todo"], filename))
        raise

def _execute_crew_workflow(ticket_content, in_progress_path, filename):

    # Define Crew Tasks - TEST DRIVEN DEVELOPMENT WORKFLOW
    plan_task = Task(
        description=f"Analyze this ticket:\n{ticket_content}\n\nCreate a CLEAR step-by-step implementation plan with:\n1. List of files to create (with exact filenames and purpose)\n2. Code logic summary\n3. Testable success criteria\n\nNOTE: You are NOT responsible for writing code now. Just plan. The developers will execute.",
        expected_output="Structured plan: List of files needed, code requirements, and how to validate success.",
        agent=spec_architect
    )

    test_task = Task(
        description="""CRITICAL: You MUST use the File Writer Tool. Do NOT describe actions.

Follow this exact format for EACH file:

Thought: I need to create a test file
Action: File Writer Tool
Action Input: {"filename": "test_case.py", "directory": "./workspace/tests", "overwrite": true, "content": "import pytest\\ndef test_example():\\n    assert True"}

Repeat for each test file (at least 2-3 times). Replace test_case.py with actual names and [content] with real pytest code.""",
        expected_output="Test files created in ./workspace/tests with real pytest code.",
        agent=test_engineer,
        context=[plan_task]
    )

    build_task = Task(
        description="""CRITICAL: You MUST use the File Writer Tool. Do NOT describe actions.

Follow this exact format for EACH file:

Thought: I need to create a source file
Action: File Writer Tool
Action Input: {"filename": "module.py", "directory": "./workspace", "overwrite": true, "content": "[complete functional code here]"}

Then verify by reading it back:
Thought: I should verify the file was created
Action: Read a file's content
Action Input: {"file_path": "./workspace/module.py", "start_line": 1, "line_count": null}

Repeat tool calls for each file. Use real, complete code (no TODOs or placeholders).""",
        expected_output="Source code files created in ./workspace with complete code, verified by reading them back.",
        agent=full_stack_dev,
        context=[plan_task, test_task]
    )

    qa_task = Task(
        description=f"""CRITICAL VALIDATION: Use the File Reader Tool to actually verify files exist and contain real code.

For EVERY file in the plan:
1. Use File Reader Tool to read each file from ./workspace/
2. Check that file exists (if not found, report FAILED: [filename] not found)
3. Check that content is NOT empty or placeholder text (report FAILED if empty)
4. Check that code actually implements the requirements (not just "TODO" or "pass")
5. Report the actual content you read

Report format:
- File: ./workspace/[filename] - EXISTS/MISSING
  Content preview: [first 100 chars]
  Status: PASSED / FAILED: [reason]

If ANY file is missing, says FAILED in your report.""",
        expected_output="Detailed validation report using File Reader Tool. Report PASSED only if all files exist with real code. Report FAILED: [issue] if anything is wrong.",
        agent=qa_engineer,
        context=[plan_task, test_task, build_task]
    )

    crew = Crew(
        agents=[spec_architect, test_engineer, full_stack_dev, qa_engineer],
        tasks=[plan_task, test_task, build_task, qa_task],
        verbose=True,
        tracing=True
    )

    # Execute
    try:
        print("[CREW] Starting workflow...")
        result = crew.kickoff()
    except Exception as e:
        error_msg = str(e).lower()
        if "failed to parse llm response" in error_msg:
            print("[ERROR] LLM response parsing failed. This usually means:")
            print(f"  - Ollama crashed or is unresponsive")
            print(f"  - Model weights corrupt")
            print("  Try: pkill -9 ollama && sleep 2 && ollama serve &")
        raise
    
    # Fallback executor: parse agent output for JSON-like tool-call objects
    # and actually write files if the agent described writes instead of using the tool.
    try:
        import json, re

        def _extract_json_objects(text):
            objs = []
            # crude scanner to find balanced braces and parse JSON
            for i, ch in enumerate(text):
                if ch == '{':
                    depth = 0
                    for j in range(i, len(text)):
                        if text[j] == '{':
                            depth += 1
                        elif text[j] == '}':
                            depth -= 1
                            if depth == 0:
                                snippet = text[i:j+1]
                                try:
                                    objs.append(json.loads(snippet))
                                except Exception:
                                    pass
                                break
            return objs

        raw = str(result) if result else ""
        candidates = _extract_json_objects(raw)
        wrote_any = False
        for obj in candidates:
            # support either a single dict or nested structure
            if isinstance(obj, dict):
                items = [obj]
            elif isinstance(obj, list):
                items = obj
            else:
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue
                # normalize keys
                if 'filename' in item and 'content' in item:
                    # Use the wrapper to reliably call the FileWriterTool
                    res = call_file_writer_from_dict(item)
                    if res.get('ok'):
                        print(f"[FALLBACK] Wrote file: {res.get('path')}")
                        wrote_any = True
                    else:
                        print(f"[FALLBACK] Failed to write file from described action: {res.get('error')}")

        # Detect prose action descriptions and warn
        prose_actions = re.findall(r"Action:\s*([^:\n]+(?:Create|Write|Generate|Setup|Initialize)[^:\n]*)", raw, re.IGNORECASE)
        if prose_actions:
            print("[FALLBACK] WARNING: Agent output prose actions instead of tool calls:")
            for action in prose_actions[:3]:
                print(f"  - {action.strip()}")
            print("[FALLBACK] This indicates agent didn't invoke tools properly. Qwen2 model should help, but check task prompts.")

        if wrote_any:
            print("[FALLBACK] Completed executing described FileWriter actions found in agent output.")
    except Exception as e:
        print(f"[FALLBACK] Error while attempting to execute described tool calls: {e}")
    def _list_workspace_files():
        files = []
        for root, _, filenames in os.walk(WORKSPACE_DIR):
            for name in filenames:
                rel = os.path.relpath(os.path.join(root, name), WORKSPACE_DIR)
                files.append(rel)
        return sorted(files)

    def _check_required_outputs():
        files = _list_workspace_files()
        issues = []
        if not files:
            issues.append("No files were created in workspace.")
        tests = [f for f in files if f.startswith("tests/")]
        if not tests:
            issues.append("No tests were created in workspace/tests.")
        return issues

    def _run_tests():
        tests_dir = os.path.join(WORKSPACE_DIR, "tests")
        if not os.path.isdir(tests_dir):
            return False, "Tests directory not found; skipping test run."
        try:
            completed = subprocess.run(
                ["pytest", "-q", tests_dir],
                cwd=WORKSPACE_DIR,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return False, "pytest not available in environment."
        output = (completed.stdout or "") + (completed.stderr or "")
        return completed.returncode == 0, output.strip()

    # Convert result to string (CrewOutput object)
    qa_result = str(result) if result else ""
    qa_result_lower = qa_result.lower()
    test_failed = "failed:" in qa_result_lower or "missing" in qa_result_lower or "not found" in qa_result_lower or "hallucinated" in qa_result_lower or "empty" in qa_result_lower
    
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
            verbose=True,
            tracing=True
        )
        result = retry_crew.kickoff()
        qa_result = str(result) if result else ""
        qa_result_lower = qa_result.lower()
        test_failed = "failed:" in qa_result_lower or "missing" in qa_result_lower or "not found" in qa_result_lower or "hallucinated" in qa_result_lower or "empty" in qa_result_lower

    output_issues = _check_required_outputs()
    tests_passed, test_output = _run_tests()
    if output_issues:
        test_failed = True
    if not tests_passed:
        test_failed = True

    # Append Report
    report = f"\n\n## AI Report\n**Status**: {'Implementation Complete.' if not test_failed else 'Completed with issues - manual review needed.'}\n**Summary**: {result}\n\n**Automated Checks**:\n- Output checks: {'PASS' if not output_issues else 'FAIL'}\n- Test run: {'PASS' if tests_passed else 'FAIL'}\n\n**Output Check Details**:\n{os.linesep.join(output_issues) if output_issues else 'All required outputs detected.'}\n\n**Test Output**:\n{test_output or 'No test output.'}\n\n**Instructions**: Review the files in `workspace/`. If satisfied, change [ ] Approved to [x] Approved below (or just write 'Status: Approved').\n[ ] Approved"
    
    # DEBUG: Check what files were actually created
    print("\n[DEBUG] Files in workspace after crew execution:")
    for root, dirs, files in os.walk(WORKSPACE_DIR):
        for file in files:
            filepath = os.path.join(root, file)
            rel_path = os.path.relpath(filepath, WORKSPACE_DIR)
            try:
                with open(filepath, 'r') as f:
                    content = f.read()
                    lines = len(content.split('\n'))
                    print(f"  ✓ {rel_path} ({len(content)} bytes, {lines} lines)")
            except:
                print(f"  ✗ {rel_path} (error reading)")
    
    with open(in_progress_path, 'a') as f:
        f.write(report)

    if test_failed:
        print(f"[KANBAN] Keeping ticket in progress due to failed checks: {filename}")
        return

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
