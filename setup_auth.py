import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly', 'https://www.googleapis.com/auth/calendar.events', 'https://www.googleapis.com/auth/gmail.modify']

def main():
    print("--- Google Calendar Local Auth Setup ---")
    
    if not os.path.exists('credentials.json'):
        print("Error: credentials.json not found in the current directory.")
        print("Please ensure you have downloaded the OAuth 2.0 Client ID JSON from Google Cloud Console.")
        return

    flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
    
    # This will open your local browser for authentication
    creds = flow.run_local_server(port=0)
    
    # Save the credentials to token.json
    with open('token.json', 'w') as token:
        token.write(creds.to_json())
    
    print("\n✅ Success! 'token.json' has been created.")
    ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
    print(f"Now, upload 'token.json' to your server in {ROOT_DIR}/")

if __name__ == '__main__':
    main()
