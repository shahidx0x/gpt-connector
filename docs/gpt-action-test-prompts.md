# GPT Action Test Prompts

Use these prompts after importing `gpt-actions.openapi.yaml` into a private Custom GPT.

1. Show system info for this Windows machine.
2. Create `C:\Users\SHAHID\Documents\LocalControl\scratch\hello.txt` with a short greeting.
3. Read that file back and summarize it.
4. Replace the greeting in that file with a different sentence.
5. Search for files named `hello` under `C:\Users\SHAHID\Documents\LocalControl`.
6. Search file contents under `C:\Users\SHAHID\Documents\LocalControl` for the new sentence.
7. Run `whoami` and tell me the Windows account name.
8. Start an async job that waits 5 seconds and prints `done`, then poll until it completes.
9. Try to delete the scratch file; when approval is required, show me the approval id and wait.
10. Try a risky command like `Remove-Item C:\Temp\not-real.txt`; confirm that approval is required before execution.
11. Ask for a missing path and explain the error cleanly.
12. List running processes whose name contains `python`.

