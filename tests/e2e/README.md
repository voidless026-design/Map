# GUI end-to-end check (optional, not part of `make test`)

Serves the real app against a fake web (no network needed), then drives it with
headless Chromium: filter -> tiles -> autofilled command -> run -> evidence cards,
plus "no null text", unique tile titles, no idle animations and no JS errors.

```bash
pip install libzim                          # the mock serves a real ZIM book
python3 tests/e2e/serve_mock.py &          # http://127.0.0.1:8611
npm i playwright && npx playwright install chromium
node tests/e2e/gui_e2e.js /tmp/shots       # PASS/FAIL per check + screenshots
```
