# Example Pipelines for Open-WebUI

This repo includes some example pipelines for Open-WebUI and will be updated over time:

* `00_repeater_example.py` the simplest pipeline, where the user's input is repeated back to them. no external connections, so test that uploading a pipeline works in your setup with this one
* `01_text_to_sql_pipeline_vLLM_mistral.py` natural language input from user > text to SQL prompt > prompt/response from vLLM LLM endpoint (in this case, with default llama-index prompt and Mistral model assumed) > generated query runs against postgres DB > result of query sent to LLM > LLM synthesizes response, displays it for the user
* `02_sql_query_pipeline.py` after having an LLM generate a SQL query with the previous pipeline, edit and run another query with this
