import psycopg2
from psycopg2 import sql
import logging
from typing import List, Union, Generator, Iterator
import os
from pydantic import BaseModel
#from llama_index.llms.ollama import Ollama
from llama_index.llms.openai_like import OpenAILike
from llama_index.core.query_engine import NLSQLTableQueryEngine
from llama_index.core import SQLDatabase, PromptTemplate
from sqlalchemy import create_engine, inspect
import aiohttp
import asyncio

# inside the pipelines container, run: pip install llama-index==0.10.1 llama-index-core==0.10.1 llama-index-llms-openai-like==0.1.3
# pip install -U --force-reinstall nltk==3.8.1
# pip install llama-index-llms-openai-like==0.1.3

# good one to list column names in the DB: 
# SELECT json_object_keys(to_json(json_populate_record(NULL::public.movies, '{}'::JSON)))
# response for movies: [('Release Year',), ('title',), ('Origin/Ethnicity',), ('director',), ('Cast',), ('genre',), ('Wiki Page',), ('plot',)]


#import openai
#openai.api_key = 'abc-123'


logging.basicConfig(level=logging.DEBUG)

class Pipeline:
    class Valves(BaseModel):
        DB_HOST: str
        DB_PORT: str
        DB_USER: str
        DB_PASSWORD: str
        DB_DATABASE: str
        DB_TABLES: List[str]
        VLLM_HOST: str
        OPENAI_API_KEY: str
        TEXT_TO_SQL_MODEL: str

    def __init__(self):
        self.name = "01 Database RAG Pipeline vLLM llama"
        self.conn = None
        self.nlsql_response = ""

        self.valves = self.Valves(
            **{
                "pipelines": ["*"],
                "DB_HOST": os.getenv("PG_HOST", "http://10.30.164.243"),
                "DB_PORT": os.getenv("PG_PORT", '5432'),
                "DB_USER": os.getenv("PG_USER", "admin"),
                "DB_PASSWORD": os.getenv("PG_PASSWORD", "tester123"),
                "DB_DATABASE": os.getenv("PG_DB", "postgres"),
                "DB_TABLES": ["movies"],
                "VLLM_HOST": os.getenv("VLLM_HOST", "http://10.1.152.55:8012/v1"),
                "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", 'abc-123'),
                "TEXT_TO_SQL_MODEL": "NousResearch/Meta-Llama-3-8B-Instruct"
            }
        )

    def init_db_connection(self):
        connection_params = {
            'dbname': self.valves.DB_DATABASE,
            'user': self.valves.DB_USER,
            'password': self.valves.DB_PASSWORD,
            'host': self.valves.DB_HOST.split('//')[-1],  # Remove the http:// or https:// prefix if present
            'port': self.valves.DB_PORT
        }

        try:
            self.conn = psycopg2.connect(**connection_params)
            print("Connection to PostgreSQL established successfully")
        except Exception as e:
            print(f"Error connecting to PostgreSQL: {e}")

        # Create a cursor object
        self.cur = self.conn.cursor()

        # Query to get the list of tables
        self.cur.execute("""
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_type = 'BASE TABLE'
            AND table_schema NOT IN ('information_schema', 'pg_catalog');
        """)

        # Fetch and print the table names
        tables = self.cur.fetchall()
        print("Tables in the database:")
        for schema, table in tables:
            print(f"{schema}.{table}")
        
        
        # Query to get the column names
        self.cur.execute("""SELECT json_object_keys(to_json(json_populate_record(NULL::public.movies, '{}'::JSON)))""")
        
        #Fetch and print the column names
        columns = self.cur.fetchall()
        print("Columns in the database:")
        print(f"{columns}")
        

    async def on_startup(self):
        self.init_db_connection()

    async def on_shutdown(self):
        self.cur.close()
        self.conn.close()

    async def make_request_with_retry(self, url, params, retries=3, timeout=10):
        for attempt in range(retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params, timeout=timeout) as response:
                        response.raise_for_status()
                        return await response.text()
            except (aiohttp.ClientResponseError, aiohttp.ClientPayloadError, aiohttp.ClientConnectionError) as e:
                logging.error(f"Attempt {attempt + 1} failed with error: {e}")
                if attempt + 1 == retries:
                    raise
                await asyncio.sleep(2 ** attempt)  # Exponential backoff

    def extract_sql_query(self, response_object):
        for key, value in response_object.items():
            if isinstance(value, dict) and 'sql_query' in value:
                return value['sql_query']
            elif key == 'sql_query':
                return value
        return None

    def handle_streaming_response(self, response_gen):
        final_response = ""
        for chunk in response_gen:
            final_response += chunk
        return final_response

    def pipe(self, user_message: str, model_id: str, messages: List[dict], body: dict) -> Union[str, Generator, Iterator]:
        # Use the established psycopg2 connection to create a SQLAlchemy engine
        self.engine = create_engine(f"postgresql+psycopg2://{self.valves.DB_USER}:{self.valves.DB_PASSWORD}@{self.valves.DB_HOST.split('//')[-1]}:{self.valves.DB_PORT}/{self.valves.DB_DATABASE}")
        sql_database = SQLDatabase(self.engine, include_tables=self.valves.DB_TABLES)

        
        
        llm = OpenAILike(
            model="NousResearch/Meta-Llama-3-8B-Instruct",
            api_base="http://10.1.152.55:8012/v1",
            api_key="abc-123",
            max_tokens=100,
            stopping_ids=[128009, 128001, 128000]
        )
        
        

        text_to_sql_prompt = """
        <|begin_of_text|><|start_header_id|>system<|end_header_id|>    
        You are a helpful AI Assistant providing PostgreSQL commands to users.
        Make sure to always use the stop token you were trained on at the end of a response: <|eot_id|>
        
        Given an input question, create a syntactically correct PostgreSQL query to run.
        You can order the results by a relevant column to return the most interesting examples in the database.
        Unless the user specifies in the question a specific number of examples to obtain, query for at most 5 results using the LIMIT clause as per Postgres.
        Never query for all the columns from a specific table, only ask for a few relevant columns given the question.
        You should use DISTINCT statements and avoid returning duplicates wherever possible.
        Pay attention to use only the column names that you can see in the schema description. Be careful to not query for columns that do not exist. Pay attention to which column is in which table. Also, qualify column names with the table name when needed. 
        
        
        You are required to use the following format, each taking one line:
        <|start_header_id|>user<|end_header_id|>
        
        Only use tables listed below.
        movies
        
        Only use columns listed below.
        [('Release Year',), ('title',), ('Origin/Ethnicity',), ('director',), ('Cast',), ('genre',), ('Wiki Page',), ('plot',)]
        
        Question: How many rows in the database?<|eot_id|><|start_header_id|>assistant<|end_header_id|>
        
        SQLQuery: SELECT COUNT(*) FROM "movies"<|eot_id|>
        
        <|start_header_id|>user<|end_header_id|>
        Only use tables listed below.
        movies
        
        Only use columns listed below.
        [('Release Year',), ('title',), ('Origin/Ethnicity',), ('director',), ('Cast',), ('genre',), ('Wiki Page',), ('plot',)]
        
        Question: How many comedy movies in 1995?<|eot_id|><|start_header_id|>assistant<|end_header_id|>
        
        SQLQuery: SELECT COUNT(*) FROM "movies" WHERE "Release Year" = 1995 AND "genre" = 'comedy'<|start_header_id|>user<|end_header_id|>
        
        Only use tables listed below.
        movies
        
        Only use columns listed below.
        [('Release Year',), ('title',), ('Origin/Ethnicity',), ('director',), ('Cast',), ('genre',), ('Wiki Page',), ('plot',)]
        
        Question: {query_str}<|eot_id|><|start_header_id|>assistant<|end_header_id|>
        """
        
        
        
        synthesis_prompt = """
        <|begin_of_text|><|start_header_id|>system<|end_header_id|>    
        You are a helpful AI Assistant synthesizing the response from a PostgreSQL query.
        Make sure to always use the stop token you were trained on at the end of a response: <|eot_id|>
        
        You are required to use the following format, each taking one line:
        <|start_header_id|>user<|end_header_id|>
        
        SQLResponse: 
        
        
        
        ******** edit this *********
        
        
        
        Only use tables listed below.
        movies
        
        Only use columns listed below.
        [('Release Year',), ('title',), ('Origin/Ethnicity',), ('director',), ('Cast',), ('genre',), ('Wiki Page',), ('plot',)]
        
        Question: How many rows in the database?<|eot_id|><|start_header_id|>assistant<|end_header_id|>
        
        SQLQuery: SELECT COUNT(*) FROM "movies"<|eot_id|>
        
        <|start_header_id|>user<|end_header_id|>
        Only use tables listed below.
        movies
        
        Only use columns listed below.
        [('Release Year',), ('title',), ('Origin/Ethnicity',), ('director',), ('Cast',), ('genre',), ('Wiki Page',), ('plot',)]
        
        Question: How many comedy movies in 1995?<|eot_id|><|start_header_id|>assistant<|end_header_id|>
        
        SQLQuery: SELECT COUNT(*) FROM "movies" WHERE "Release Year" = 1995 AND "genre" = 'comedy'<|start_header_id|>user<|end_header_id|>
        
        Only use tables listed below.
        movies
        
        Only use columns listed below.
        [('Release Year',), ('title',), ('Origin/Ethnicity',), ('director',), ('Cast',), ('genre',), ('Wiki Page',), ('plot',)]
        
        Question: {query_str}<|eot_id|><|start_header_id|>assistant<|end_header_id|>
        """

        text_to_sql_template = PromptTemplate(text_to_sql_prompt)

        query_engine = NLSQLTableQueryEngine(
            sql_database=sql_database,
            tables=self.valves.DB_TABLES,
            llm=llm,
            embed_model="local",
            text_to_sql_prompt=text_to_sql_template,
            synthesize_response=False,
            #response_synthesis_prompt=synthesis_prompt,
            streaming=True
        )

        try:
            response = query_engine.query(user_message)
            sql_query = self.extract_sql_query(response.metadata)
            if hasattr(response, 'response_gen'):
                final_response = self.handle_streaming_response(response.response_gen)
                result = f"Generated SQL Query:\n```sql\n{sql_query}\n```\nResponse:\n{final_response}"
                return result
            else:
                final_response = response.response
                result = f"Generated SQL Query:\n```sql\n{sql_query}\n```\nResponse:\n{final_response}"
                return result
        except aiohttp.ClientResponseError as e:
            logging.error(f"ClientResponseError: {e}")
            return f"ClientResponseError: {e}"
        except aiohttp.ClientPayloadError as e:
            logging.error(f"ClientPayloadError: {e}")
            return f"ClientPayloadError: {e}"
        except aiohttp.ClientConnectionError as e:
            logging.error(f"ClientConnectionError: {e}")
            return f"ClientConnectionError: {e}"
        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            return f"Unexpected error: {e}"
