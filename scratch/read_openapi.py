import urllib.request
import json

try:
    with urllib.request.urlopen("http://localhost:9000/v1/registry") as response:
        registry = json.loads(response.read().decode('utf-8'))
    
    print("Registry Models:")
    for model in registry.get("data", []):
        print(f" - {model.get('id')} ({model.get('task')})")
except Exception as e:
    print("Error:", e)
