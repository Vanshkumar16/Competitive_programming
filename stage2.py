from dotenv import load_dotenv
import os

# TODO 1: load the .env file into the environment
# Hint: there's a function called load_dotenv() — just call it, no arguments needed
load_dotenv()

# TODO 2: read the MY_TEST_SECRET value
# Hint: os.getenv("KEY_NAME_HERE")

secret_value = os.getenv("MY_TEST_SECRET")

print(f"My secret is: {secret_value}")