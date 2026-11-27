# Repository working conventions

This directory is the initial public source snapshot. Follow the current user's
task; historical private handoff instructions are not included.

- Preserve the existing PMM calculation, role isolation, legacy UI and protocols.
- The running frontend is plain JavaScript served by persona/server.py. There is
  no mandatory frontend build. Update the actual files loaded by index.html.
- Keep runtime state in data/ and .local-home/, never in source or fixtures.
- Use synthetic fixtures and explicit isolated directories for checks. Do not
  call cloud models, send QQ messages or inspect private databases implicitly.
- Do not treat missing data as measured personality or emotion. Keep source,
  unknown, failure and delivery states distinct.
- Read docs/KNOWN_LIMITATIONS.md before claiming a mechanism is complete.
- Document real changes and report PASS / FAIL / NOT RUN honestly.
- Never include credentials, personal paths, real chat logs or old git history
  in a public export. Do not assign a license on the owner's behalf.
