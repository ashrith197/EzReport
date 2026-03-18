import json
import re
import sqlite3
import logging
from typing import Dict, Any, Tuple

logger = logging.getLogger(__name__)

ALLOWED_CHART_TYPES = {"table", "bar", "line", "pie", "metric", "none"}

def clean_and_parse_json(raw_text: str) -> Dict[str, Any]:
    """
    Cleans markdown formatting and parses the LLM output as a JSON dictionary.
    Validates required keys and chart types.
    """
    # Remove potential markdown code fences: ```json ... ```
    cleaned = raw_text.strip()
    # Strip opening fence
    cleaned = re.sub(r'^```(?:json)?', '', cleaned, flags=re.MULTILINE|re.IGNORECASE).strip()
    # Strip closing fence
    cleaned = re.sub(r'```$', '', cleaned, flags=re.MULTILINE).strip()
    
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}. Raw text:\n{raw_text}")
        raise ValueError(f"Invalid JSON format. Expected a single valid JSON object.")

    if not isinstance(data, dict):
        raise ValueError(f"Invalid JSON format. Expected a dictionary, got {type(data).__name__}.")

    # Validate structure
    required_keys = {"description", "sql_query", "chart_type", "warning"}
    missing_keys = required_keys - set(data.keys())
    if missing_keys:
        raise ValueError(f"Missing required JSON keys: {missing_keys}")

    # Validate chart type
    if data["chart_type"] not in ALLOWED_CHART_TYPES:
        logger.warning(f"Invalid chart_type '{data['chart_type']}', defaulting to 'table'")
        data["chart_type"] = "table"

    return data

def validate_sql_semantics(sql: str, db_path: str = "data.db") -> Tuple[bool, str]:
    """
    Validates if the SQL is structurally safe (SELECT only) and semantically
    correct against the actual SQLite database schema.
    """
    if not sql or not isinstance(sql, str):
         return False, "Query is empty."

    sql_stripped = sql.strip()
    
    # 1. Basic safety checks (prevent obvious injection/mutations)
    # Ensure it starts with SELECT
    if not re.match(r"(?i)^\s*SELECT\b", sql_stripped):
        return False, "Query must be a SELECT statement."
        
    # Prevent destructive keywords
    forbidden_keywords = [
        r"\bDROP\b", r"\bDELETE\b", r"\bUPDATE\b", r"\bINSERT\b", 
        r"\bALTER\b", r"\bTRUNCATE\b", r"\bCREATE\b", r"\bPRAGMA\b",
        r"\bATTACH\b", r"\bREPLACE\b"
    ]
    for kw in forbidden_keywords:
        if re.search(kw, sql_stripped, re.IGNORECASE):
            return False, f"Query contains forbidden keyword: {kw.replace(r'\\b', '')}"

    # Prevent multiple statements or appended commands
    if ";" in sql_stripped.rstrip(";"):
         return False, "Multiple statements are not allowed."

    # 2. Semantic validation via SQLite EXPLAIN
    # We execute "EXPLAIN {query}" on the actual database. 
    # This prepares the statement, confirming the columns and tables exist and the syntax is valid,
    # without actually fetching the rows.
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # EXPLAIN validates syntax and schema references
        cursor.execute(f"EXPLAIN {sql_stripped}")
        conn.close()
        return True, "Valid"
    except sqlite3.OperationalError as e:
        return False, f"Semantic Error against database: {str(e)}"
    except Exception as e:
        return False, f"Unexpected validation error: {str(e)}"

if __name__ == "__main__":
    from pathlib import Path
    
    logging.basicConfig(level=logging.INFO)
    
    # Path to the database created by transform.py
    test_db_path = Path(__file__).parent / "data.db"
    
    sample_good_response = '''```json
    {
      "description": "Total sales by region",
      "sql_query": "SELECT revenue FROM data LIMIT 5",
      "chart_type": "table",
      "warning": null
    }
    ```'''
    
    print("--- Testing JSON Parser ---")
    try:
        parsed = clean_and_parse_json(sample_good_response)
        print("Successfully parsed:")
        print(json.dumps(parsed, indent=2))
    except Exception as e:
        print("Parse failed:", e)
        
    print("\n--- Testing SQL Validation (Good Query) ---")
    valid, msg = validate_sql_semantics(parsed['sql_query'], str(test_db_path))
    print(f"Result: {valid} - {msg}")
    
    print("\n--- Testing SQL Validation (Bad Semantic Query) ---")
    bad_semantic_sql = "SELECT fake_column FROM data"
    valid, msg = validate_sql_semantics(bad_semantic_sql, str(test_db_path))
    print(f"Result: {valid} - {msg}")
    
    print("\n--- Testing SQL Validation (Bad Syntax - Multiple Statements) ---")
    bad_syntax_sql = "SELECT revenue FROM data; DROP TABLE data"
    valid, msg = validate_sql_semantics(bad_syntax_sql, str(test_db_path))
    print(f"Result: {valid} - {msg}")
    
    print("\n--- Testing SQL Validation (Bad Syntax - Non-SELECT) ---")
    bad_syntax_sql = "UPDATE data SET revenue = 0"
    valid, msg = validate_sql_semantics(bad_syntax_sql, str(test_db_path))
    print(f"Result: {valid} - {msg}")