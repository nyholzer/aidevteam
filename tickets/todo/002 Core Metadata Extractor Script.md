# Feature: Core Metadata Extractor Script

## Description
Create a Python script file_analyzer.py inside projects/repo_analyzer_v1/src/ that extracts key data from a single file and saves it as JSON.

## Requirements

    Use os and pathlib for file handling.

    Input: A single file path (e.g., main.py).

    Output: A JSON file in projects/repo_analyzer_v1/output/ with:

        filename: String

        size_kb: Float (rounded to 2 decimals)

        language: String (determined by file extension)

        preview: The first 100 characters of the file content.

    Error Handling: Print "Error: File Not Found" if the path is invalid.