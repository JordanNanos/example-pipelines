from typing import List, Union, Generator, Iterator

class Pipeline:
    def __init__(self):
        self.name = "00 Repeater Example"
        pass

    async def on_startup(self):
        # This function is called when the server is started.
        print(f"on_startup:{__name__}")
        pass

    async def on_shutdown(self):
        # This function is called when the server is started.
        print(f"on_shutdown:{__name__}")
        pass

    
    def pipe(self, user_message: str, messages: List[dict], body: dict) -> Union[str, Generator, Iterator]:
        # This function is called when a new user_message is receieved.
        
        print(f"received message from user: "{user_message}) #user_message to pipeline logs
        return (f"received message from user: "{user_message}) #user_message back to the UI
        
