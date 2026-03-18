import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from google import genai

# Configure logging
log_dir = Path(__file__).parent / "logs"
log_dir.mkdir(exist_ok=True)
log_file = log_dir / "llm_service.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class LLMService:
    def __init__(self, model_name: str = "gemini-3.1-flash-lite-preview"):
        """
        Initialize the LLM service using the new google.genai SDK.
        Automatically loads API key from the environment/dotenv.
        """
        env_path = Path(__file__).parent / ".env"
        load_dotenv(env_path)
        
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.warning("GEMINI_API_KEY not found in environment variables.")
            self.client = None
            self.model_name = None
            return
            
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        logger.info(f"LLMService initialized with model: {model_name}")

    def generate_response(self, prompt: str, timeout: int = 60) -> str:
        """
        Sends the final prompt to the Gemini API and returns the raw response text.
        Handles timeouts, empty responses, and malformed outputs.
        """
        if not self.client:
            logger.error("LLMService is not initialized (missing API key).")
            return "Error: GEMINI_API_KEY is not set."

        logger.info("=== Sending Request to LLM ===")
        logger.info(f"Prompt preview: {prompt[:200]}..." if len(prompt) > 200 else f"Prompt: {prompt}")

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )

            # Capture raw text carefully and handle potential empty returns
            if not response or not response.candidates:
                logger.error("Empty response received from API (No candidates).")
                return ""

            raw_text = response.text
            
            if not raw_text or not raw_text.strip():
                logger.error("Malformed or completely empty text received from the API.")
                return ""

            logger.info("=== Received Response from LLM ===")
            logger.info(f"Response preview: {raw_text[:200]}..." if len(raw_text) > 200 else f"Response: {raw_text}")
            
            return raw_text

        except Exception as e:
            logger.error(f"Error during LLM API call: {str(e)}", exc_info=True)
            return ""

    def build_prompt(self, user_query: str, schema: str, past_conversation: str) -> str:
        """
        Builds the master prompt using the injected instructions, schema, and chat context.
        """
        return f"""
        You are an expert data query interpretation and SQL generation engine.
        Your task is to convert a user's natural language request into:
        1. a short description
        2. one safe SQL SELECT query
        3. one chart type
        4. an optional warning if the user includes unrelated words or noise in the query

        You must strictly follow all rules below.

        ==================================================
        ROLE
        ==================================================

        You are a structured analytics interpreter.

        You must:
        - understand the user's reporting intent
        - map the request to the available schema
        - generate exactly one valid SQL query
        - select the most suitable chart type
        - return STRICT JSON ONLY
        - never return markdown
        - never return code fences
        - never return explanation outside JSON

        You are not a chatbot.
        You are not allowed to ask follow-up questions.
        If the user query is ambiguous, incomplete, or partially unrelated, still return the best possible valid JSON using a conservative interpretation.

        ==================================================
        DATABASE
        ==================================================

        Database type: SQLite
        Table name: data

        Available schema:
        {schema}

        Only this table exists.
        Only these columns exist.
        Do not invent columns.
        Do not invent tables.

        ==================================================
        PAST CONVERSATION CONTEXT
        ==================================================

        Optional past conversation context:
        {past_conversation}

        Use past conversation only when it helps resolve follow-up questions like:
        - "now give first five"
        - "show only south region"
        - "make it monthly instead"
        - "just top 10"

        If past conversation is empty, ignore it.

        ==================================================
        SQL RESTRICTIONS
        ==================================================

        You must generate exactly one SQL query.

        SQL query rules:
        - query only from table `data`
        - generate only a single SELECT statement
        - do not generate multiple statements
        - do not use INSERT
        - do not use UPDATE
        - do not use DELETE
        - do not use DROP
        - do not use ALTER
        - do not use TRUNCATE
        - do not use CREATE
        - do not use PRAGMA
        - do not use ATTACH
        - do not use comments
        - do not use semicolon-separated multiple queries
        - do not reference any table other than `data`
        - use only columns from the provided schema
        - never use SELECT *
        - select only necessary columns
        - use aliases where useful
        - use valid SQLite-compatible SQL

        Behavior rules:
        - if the user asks for totals, averages, counts, trends, comparisons, rankings, or grouped metrics, use aggregation appropriately
        - if aggregation is used with categories, use GROUP BY correctly
        - if the user asks for top/bottom/ranking, use ORDER BY with LIMIT
        - if the user asks for first N rows, use LIMIT
        - if the user asks for filtering, use WHERE
        - if the user asks for a single KPI or total value, return one aggregated value when appropriate
        - if the request is vague, prefer a safe and conservative SELECT query over guessing aggressively
        - when the request is ambiguous, choose the most reasonable interpretation from available schema and mention the assumption in description
        - SQL must always be executable
        - SQL must always be one single SELECT query

        ==================================================
        HALLUCINATION AND UNRELATED WORD HANDLING
        ==================================================

        You must detect unrelated, noisy, or unsupported words in the user query.

        Definition of unrelated word:
        A word or phrase that does not map to:
        - the schema
        - an analytics operation
        - a filter value clearly supported by the query intent
        - a reasonable business reporting concept in context

        Example:
        "show relation between revenue and sales, coffee"

        If "coffee" is not a schema column, not a valid filter value inferred from schema context, and not relevant to the request, it is unrelated.

        Rules for warning:
        - If unrelated/noisy/unsupported words are present, set `warning` to a short string explaining them
        - If there is no such issue, set `warning` to null
        - Presence of unrelated words should NOT break output JSON
        - Still return the best safe valid SQL query ignoring unrelated noise when possible

        Good warning examples:
        - "Ignored unrelated term: coffee"
        - "Ignored unrelated terms: coffee, hello"
        - "Query contains unsupported term: forecast"

        Do not over-warn for normal business words.
        Do not warn for words that can reasonably map to intent.
        AMBIGUITY FALLBACK RULES

        If the user query is ambiguous, incomplete, or underspecified:
        - do not fail
        - do not ask a question
        - do not return empty JSON
        - choose the safest reasonable interpretation based on schema and past context
        - write the assumption briefly in `description`
        - generate a conservative SQL query that is still useful and executable
        - set `warning` only if there are unrelated or unsupported words, not merely because the request is broad

        Examples of conservative fallback:
        - broad metric request -> select likely relevant metric column with LIMIT or aggregation
        - vague listing request -> return a limited table view
        - unclear comparison request -> return a table of likely involved columns 

        ==================================================
        CHART TYPE RULES
        ==================================================

        You must return exactly one chart_type from this enum only:
        - table
        - bar
        - line
        - pie
        - metric
        - none

        Chart selection guidance:
        - use `table` for detailed row-level outputs, mixed columns, or when no strong visual summary is appropriate
        - use `bar` for comparing categories
        - use `line` for trends over time
        - use `pie` only for simple part-to-whole comparisons with a small number of categories
        - use `metric` for one single KPI number like total revenue, count, average, max, min
        - use `none` when visualization is not meaningful

        Chart selection rules:
        - if output is a single numeric value, prefer `metric`
        - if output compares categories, prefer `bar`
        - if output is time-based trend, prefer `line`
        - if output is share/distribution across few categories, prefer `pie`
        - if result is a raw row listing, prefer `table`
        - when uncertain, prefer `table` over bad visualization

        ==================================================
        DESCRIPTION RULES
        ==================================================

        `description` must:
        - be short
        - be business-friendly
        - describe what the SQL is doing
        - mention assumptions if the query was ambiguous
        - mention ignored noise if helpful, but keep it brief

        Examples:
        - "Shows total revenue by region in descending order."
        - "Lists the first 5 rows from the dataset."
        - "Shows monthly sales trend based on the available date field."
        - "Interpreted the request conservatively as a comparison of revenue by sales-related category."

        ==================================================
        STRICT RESPONSE FORMAT
        ==================================================

        Return STRICT JSON ONLY.

        Output format:
        {{
        "description": "string",
        "sql_query": "string",
        "chart_type": "table | bar | line | pie | metric | none",
        "warning": "string or null"
        }}

        Formatting rules:
        - output must be valid JSON
        - all four keys must always be present
        - do not add extra keys
        - do not wrap in markdown
        - do not include explanation outside JSON
        - do not include trailing commas

        ==================================================
        FEW-SHOT EXAMPLES
        ==================================================

        Example 1
        User query:
        Show total revenue by region

        Output:
        {{
        "description": "Shows total revenue by region.",
        "sql_query": "SELECT region, SUM(revenue) AS total_revenue FROM data GROUP BY region ORDER BY total_revenue DESC",
        "chart_type": "bar",
        "warning": null
        }}

        Example 2
        User query:
        Show monthly revenue trend

        Output:
        {{
        "description": "Shows the revenue trend over time grouped by month.",
        "sql_query": "SELECT strftime('%Y-%m', order_date) AS month, SUM(revenue) AS total_revenue FROM data GROUP BY month ORDER BY month ASC",
        "chart_type": "line",
        "warning": null
        }}

        Example 3
        User query:
        Give me top 5 products by revenue

        Output:
        {{
        "description": "Shows the top 5 products by total revenue.",
        "sql_query": "SELECT product, SUM(revenue) AS total_revenue FROM data GROUP BY product ORDER BY total_revenue DESC LIMIT 5",
        "chart_type": "bar",
        "warning": null
        }}

        Example 4
        User query:
        Show the first 5 rows

        Output:
        {{
        "description": "Lists the first 5 rows from the dataset.",
        "sql_query": "SELECT col1, col2, col3 FROM data LIMIT 5",
        "chart_type": "table",
        "warning": null
        }}

        Example 5
        User query:
        What is the total revenue

        Output:
        {{
        "description": "Shows the total revenue as a single metric.",
        "sql_query": "SELECT SUM(revenue) AS total_revenue FROM data",
        "chart_type": "metric",
        "warning": null
        }}

        Example 6
        User query:
        Show relation between revenue and sales, coffee

        Output:
        {{
        "description": "Shows a conservative comparison using the supported revenue and sales-related fields while ignoring unrelated noise.",
        "sql_query": "SELECT revenue, sales FROM data",
        "chart_type": "table",
        "warning": "Ignored unrelated term: coffee"
        }}

        Example 7
        User query:
        now give first five

        Past conversation:
        Previous request was: Show total revenue by region

        Output:
        {{
        "description": "Shows the first 5 rows of the previously requested grouped revenue-by-region result.",
        "sql_query": "SELECT region, SUM(revenue) AS total_revenue FROM data GROUP BY region ORDER BY total_revenue DESC LIMIT 5",
        "chart_type": "bar",
        "warning": null
        }}

        Example 8
        User query:
        Show sales

        Output:
        {{
        "description": "Interpreted the request conservatively as a listing of sales-related values from the available schema.",
        "sql_query": "SELECT sales FROM data LIMIT 50",
        "chart_type": "table",
        "warning": null
        }}

        ==================================================
        CURRENT INPUT
        ==================================================

        Current user query:
        {user_query}

        Now return STRICT JSON ONLY.
        """

class ContextManager:
    """
    Manages conversational context using an in-memory SQLite database.
    Stores the user query, interpreted description, the generated SQL, and the chart type.
    """
    def __init__(self):
        import sqlite3
        # Connect to an in-memory database
        self.conn = sqlite3.connect(":memory:")
        self._create_table()

    def _create_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_query TEXT,
                description TEXT,
                sql_query TEXT,
                chart_type TEXT
            )
        """)
        self.conn.commit()

    def add_interaction(self, user_query: str, description: str, sql_query: str, chart_type: str):
        self.conn.execute("""
            INSERT INTO conversation_history (user_query, description, sql_query, chart_type)
            VALUES (?, ?, ?, ?)
        """, (user_query, description, sql_query, chart_type))
        self.conn.commit()

    def get_history_json_str(self) -> str:
        """
        Retrieves the conversation history formatted as a JSON string
        specifically suited for the prompt format.
        """
        import json
        
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_query, description, sql_query, chart_type FROM conversation_history ORDER BY id ASC")
        rows = cursor.fetchall()
        
        history_list = []
        for row in rows:
            history_list.append({
                "user_query": row[0],
                "description": row[1],
                "sql_query": row[2],
                "chart_type": row[3]
            })

        if not history_list:
            return "[]"
        
        return json.dumps(history_list, indent=2)

if __name__ == "__main__":
    import json
    import pandas as pd
    from transform import process_and_store_data

    # --------------------------------------------------------------------------
    # SPACE FOR MANUAL ENTRY OF PROMPT
    # --------------------------------------------------------------------------
    
    # 1. Simulate Loading User Variables
    user_query = "now show exactly top three"
    
    # Simulate Context Manager Usage
    context_mgr = ContextManager()
    
    # Let's add a fake prior conversation that the user is now asking a follow-up about
    context_mgr.add_interaction(
        user_query="Show sales by region",
        description="Total sales grouped by region",
        sql_query="SELECT region, SUM(sales) AS total_sales FROM data GROUP BY region;",
        chart_type="bar"
    )
    
    past_conversation = context_mgr.get_history_json_str()

    # 2. Get the Schema Dynamically
    path = os.getenv("CSV_PATH")
    try:
        df = pd.read_csv(path)
        db_path = Path(__file__).parent / "data.db"
        schema_dict = process_and_store_data(df, db_path=str(db_path), table_name="data")
        schema = json.dumps(schema_dict, indent=2)
    except Exception as e:
        print(f"Failed to load dataset and extract schema: {e}")
        schema = "{}"

    # 3. Inject into the Pre-defined Prompt format
    service = LLMService()
    
    # Build the prompt using the new method
    MANUAL_PROMPT = service.build_prompt(user_query, schema, past_conversation)

    print("Sending dynamic prompt...")
    # Generate the response
    result_text = service.generate_response(MANUAL_PROMPT)
    print("\n--- Final Raw Response ---")
    print(result_text)
