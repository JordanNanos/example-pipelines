import psycopg2
from psycopg2 import sql
import logging
from typing import List, Union, Generator, Iterator
import os
from pydantic import BaseModel

import aiohttp
import asyncio

logging.basicConfig(level=logging.DEBUG)

class Pipeline:
    class Valves(BaseModel):
        DB_HOST: str
        DB_PORT: str
        DB_USER: str
        DB_PASSWORD: str
        DB_DATABASE: str
        DB_TABLES: List[str]

    def __init__(self):
        self.name = "02 Database Query"
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

    def pipe(self, user_message: str, model_id: str, messages: List[dict], body: dict) -> Union[str, Generator, Iterator]:
        # Use the established psycopg2 connection to create a SQLAlchemy engine
        #self.engine = create_engine(f"postgresql+psycopg2://{self.valves.DB_USER}:{self.valves.DB_PASSWORD}@{self.valves.DB_HOST.split('//')[-1]}:{self.valves.DB_PORT}/{self.valves.DB_DATABASE}")
        
        
        try:
            conn = psycopg2.connect(
                database=self.valves.DB_DATABASE,
                user=self.valves.DB_USER,
                password=self.valves.DB_PASSWORD,
                host=self.valves.DB_HOST.split('//')[-1],
                port=self.valves.DB_PORT
                )
            
            conn.autocommit=True
            cursor=conn.cursor()
            sql=user_message
                
            cursor.execute(sql)
            result = cursor.fetchall()
            return str(result)
            
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
