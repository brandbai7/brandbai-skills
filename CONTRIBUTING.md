# Contributing to BrandBAI Skills

BrandBAI Skills welcomes issue reports and focused proposals that improve portable, evidence-aware content-commerce workflows.

## Before contributing

- Open an issue before proposing a new top-level Skill or a material change to the public capability boundary.
- Keep each Skill self-contained under `skills/<skill-name>/` and follow [AGENTS.md](AGENTS.md).
- Use synthetic fixtures. Never submit live comments, downloaded media, customer data, browser profiles, cookies, tokens, request headers, private prompts, or local absolute paths.
- Do not add CAPTCHA automation, signature generation, credential extraction, access-control bypasses, or hidden rate-limit evasion.
- Make partial, unavailable, unknown, empty, and confirmed-zero states explicit.

## Code and content contributions

The repository uses a public noncommercial license and may also be offered under separate commercial agreements. To keep that dual-licensing chain clear, external code, Skill content, templates, and other copyrightable pull requests are not accepted until the contributor has signed a separate BrandBAI contributor agreement.

Issues, bug reports, reproduction steps, and general suggestions remain welcome. Do not attach confidential information, personal data, live collection output, or third-party material you do not have permission to share.

An authorized contributor must also sign each commit using the [Developer Certificate of Origin 1.1](https://developercertificate.org/) by adding a line in this form to the commit message:

```text
Signed-off-by: Your Name <your-email@example.com>
```

Use `git commit -s` to add the line automatically. DCO sign-off does not replace the separate contributor agreement required for a copyrightable contribution.

## Validate changes

Run the repository checks before submitting:

```bash
python -m pip install -r requirements-dev.txt
python scripts/validate_repo.py
cd skills/brandbai-douyin-download/scripts
python -m unittest test_download_creator_works.py test_browser_collect_comments.py test_run_foundation.py test_build_foundation_workbooks.py
```

Add or update tests when behavior changes. Real-page verification must be reported separately from synthetic unit tests and must not add collected output to the repository.

## Pull request notes

Explain the user-facing change, the evidence or failure mode behind it, the checks run, and any platform or operating-system boundary that remains unverified. Do not describe a public beta or partial validation as full production coverage.
