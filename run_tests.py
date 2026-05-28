import requests
import time

base_url = "http://127.0.0.1:5100"
headers = {"X-Token": "sk-dev-123"} # Mock token, checking flask_server.py to see if it requires one. It uses _check_token()

# We need to know what the valid token is.
# Let's write the script to test /train
def test_train():
    print("Testing /train with .webm file...")
    try:
        with open("test_audio.webm", "rb") as f:
            files = {"files": ("test_audio.webm", f, "audio/webm")}
            # flask_server.py line 407: API_KEYS = {"sk-dev-123"} or similar usually. I'll pass a dummy token first.
            response = requests.post(f"{base_url}/train", files=files, headers={"X-Token": "test"})
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.text}")
    except Exception as e:
        print(f"Error: {e}")

def test_tts():
    print("\nTesting /tts endpoint...")
    try:
        payload = {"text": "This is a test of the emergency broadcast system."}
        response = requests.post(f"{base_url}/tts", json=payload, headers={"X-Token": "test"})
        print(f"Status Code: {response.status_code}")
        print(f"Response Headers: {response.headers}")
        print(f"Content Length: {len(response.content)} bytes")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # Wait for server to start
    time.sleep(2)
    test_train()
    test_tts()
