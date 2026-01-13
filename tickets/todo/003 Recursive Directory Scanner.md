# Feature: Recursive Directory Scanner
## Description

Create a script folder_scanner.py in projects/repo_analyzer_v1/src/ that finds all files in the current workspace, but excludes the agent's own project folder to avoid an infinite loop.

## Requirements

    Recursively search for all .py and .md files.

    Constraint: Skip the directory projects/ entirely.

    For every file found, call the file_analyzer.py logic.

    Save a "Master Index" titled full_repo_index.json in the output/ folder.