# Testing PentestGPT Resume Feature

Target: https://www.kingcodes.net/

## 1. Build and Start Container

```bash
make install
make connect
```

## 2. Run Initial Pentest

```bash
pentestgpt --target https://www.kingcodes.net/
```

Let it run through Phase 1 (or more). When it completes or you stop it (Ctrl+C), note the session ID shown at the end.

## 3. Verify Session ID Was Captured

```bash
cat ~/.pentestgpt/sessions/*.json
```

Look for:
- `"backend_session_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"` (full UUID)

If `backend_session_id` is `null`, the fix didn't work.

## 4. List Sessions

```bash
ls ~/.pentestgpt/sessions/
# Example output: 9af676d1.json

# Or use built-in command:
pentestgpt --list-sessions
```

## 5. Test Resume

Option A - Resume latest session for target:
```bash
pentestgpt --target https://www.kingcodes.net/ --resume
```

Option B - Resume specific session:
```bash
pentestgpt --target https://www.kingcodes.net/ --session-id <session-id>
```

## 6. Verify Resume Worked

Success indicators:
- Shows "Resumed session xxxxxxxx"
- Continues from where it left off (doesn't repeat Phase 1)
- Has context from previous run

Failure indicators:
- Starts fresh reconnaissance
- Error "Command failed with exit code 1"
- No mention of resume

## 7. Quick Code Verification

Inside container, verify fixes are applied:

```bash
# Check session ID capture in backend
grep -A2 "Capture Claude" /app/pentestgpt/core/backend.py

# Check mode selection fix
grep "get_prompt" /app/pentestgpt/core/controller.py

# Check auto-continue rules
grep -A5 "AUTOMATIC EXECUTION" /app/pentestgpt/prompts/pentesting.py
```

## Expected Behavior

1. **Auto-continue**: Agent should NOT stop after Phase 1 asking "IF client authorizes"
2. **Resume**: Should continue from exact point using Claude Code's session ID
3. **Mode**: Should show "PentestGPT Pentest" in header, not "CTF Solver"

## Troubleshooting

If resume fails:
```bash
# Check Claude Code sessions directly
claude --resume <backend_session_id_from_json>
```

If auto-continue fails:
- Check the system prompt is updated
- Add `--instruction "Continue automatically through all phases"`
