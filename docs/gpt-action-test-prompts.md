# GPT Action Test Prompts

Use these prompts after importing `gpt-actions.openapi.yaml` into a private Custom GPT.

1. Show system info for this machine.
2. Create `C:\Users\SHAHID\Documents\GPT-Connect\scratch\hello.txt` with a short greeting.
3. Read that file back and summarize it.
4. Replace the greeting in that file with a different sentence.
5. Search for files named `hello` under `C:\Users\SHAHID\Documents\GPT-Connect`.
6. Search file contents under `C:\Users\SHAHID\Documents\GPT-Connect` for the new sentence.
7. Run `whoami` and tell me the account name.
8. Start an async job that waits 5 seconds and prints `done`, then poll until it completes.
9. Delete the scratch file and report the result.
10. Run a command like `Remove-Item C:\Temp\not-real.txt` and explain the command result cleanly.
11. Ask for a missing path and explain the error cleanly.
12. List running processes whose name contains `python`.
