# OpenAtlas — Ethics & Scope

OpenAtlas is built for **lawful, authorized, public-source intelligence** work:
journalism, due diligence, security research, CTFs, and checking your *own* exposure.
These constraints are enforced in code, not just documented.

## Hard rules (enforced in code)

1. **Public, unauthenticated data only.** Engines read pages/APIs that are visible
   without logging in. We never authenticate to a target, submit credentials, or use
   session cookies to reach gated content.
2. **robots.txt is respected.** Every web-scraping call goes through
   `openatlas/utils/robots.py`, which fetches and enforces `robots.txt` for our
   user-agent. Disallowed URLs are skipped.
3. **No CAPTCHA solving, no paywall/anti-bot bypass.** When a page presents a login
   wall or CAPTCHA, engines stop and report it rather than defeating it.
4. **Truthful, contactable user-agent.** We identify ourselves honestly; "stealth" is
   limited to polite pacing, never evasion of sites that forbid automated access.
5. **Active scanning is authorization-gated.** The network-scan engine refuses to run
   unless the operator explicitly asserts authorization (`--authorized-target`), and
   only against hosts they own or are permitted to test.
6. **No stolen data.** OathNet-style *stealer-log* retrieval is disabled: those are
   credentials stolen from victims by malware, with no legitimate free source. Only
   defensive breach-*existence* checks (is this email in a known breach?) are provided.
7. **No paid keys, ever.** There is no field to store one and none is read. A secret
   lint (`openatlas/utils/secret_lint.py`) fails the build if a credential or paid-key
   literal is committed.

8. **Every investigation has a stated purpose.** `openatlas investigate` and the GUI
   refuse to start a case without one; it is stored with the case as an audit trail.
9. **Data-broker / people-search sites are never fetched** (`DATA_BROKERS` in
   `openatlas/net/client.py`): their terms forbid automated access and they sell personal
   data. Search results may still link to them; OpenAtlas will not open them.
10. **Findings are labelled, not asserted.** Every finding carries its source link and
    is automatically re-checked (confirmed / refuted / unverified with a reason), so
    unconfirmed claims are never presented as fact.

## Your responsibilities

- Have a lawful basis and, where required, authorization for your investigation.
- Respect each site's Terms of Service and applicable privacy law (GDPR/CCPA/etc.).
- Handle any personal data you collect lawfully, minimally, and securely.
- Do not use OpenAtlas to harass, stalk, dox, or endanger anyone.

If a use would require breaking one of the hard rules above, OpenAtlas is the wrong
tool — and it will refuse.
