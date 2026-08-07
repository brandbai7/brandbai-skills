# BrandBAI Skills repository rules

This repository publishes portable Agent Skills for content commerce.

## Structure

- Put every public skill in `skills/<skill-name>/`.
- Require `SKILL.md`; use only `scripts/`, `references/`, `assets/`, and host metadata that the skill actually needs.
- Keep the skill name lowercase and hyphenated, and keep `metadata.version` explicit.
- Keep the root README catalog and the skill version in sync.

## Public-content boundary

- Never commit browser profiles, cookies, request headers, access tokens, customer data, real comment exports, downloaded media, QA previews, or local absolute paths.
- Use synthetic fixtures in tests. Do not use creator names or comment text from a live collection.
- Do not add platform-bypass logic, CAPTCHA automation, signature generation, credential extraction, or hidden rate-limit evasion.
- Preserve completion states and evidence limits. Never relabel partial output as complete.
- Keep third-party content and private BrandBAI method assets outside the repository license boundary defined in `IP_AND_DATA_POLICY.md`.

## Contributions

- Do not accept external copyrightable contributions without a separate BrandBAI contributor agreement; authorized contributors must also sign commits under the Developer Certificate of Origin.
- Do not accept material whose ownership, license, confidentiality, or data authorization is unclear.
- Treat BrandBAI brand permission and commercial permission separately from the public noncommercial source license.

## Portability

- Keep `SKILL.md` compliant with the Agent Skills specification.
- Treat the skill folder as the portable source of truth; keep host-specific metadata optional.
- State local runtime requirements and permissions in the skill.
- When a feature depends on one host-only tool, provide a documented fallback or mark that output as unavailable on other hosts.

## Validation

Run before committing:

```bash
python -m pip install -r requirements-dev.txt
python scripts/validate_repo.py
python -m unittest scripts/test_build_skill_release.py
cd skills/brandbai-douyin-download/scripts
python -m unittest test_download_creator_works.py test_selection_contract.py test_package_delivery.py test_browser_collect_comments.py test_run_foundation.py test_run_long_job.py test_build_foundation_workbooks.py
cd ../../brandbai-douyin-account-analysis/scripts
python -m unittest test_analysis_dataset.py test_analysis_delivery.py
cd ../../brandbai-tmall-download/scripts
python -m unittest test_collector_core.py test_browser_collect_tmall.py test_build_delivery.py test_run_foundation.py
cd ../../brandbai-xiaohongshu-download/scripts
python -m unittest test_collector_core.py test_browser_collect_xiaohongshu.py test_build_delivery.py test_run_foundation.py
cd ../../brandbai-product-value/scripts
python -B test_product_value_delivery.py
cd ../../brandbai-value-expression/scripts
python -X utf8 -B test_value_expression_delivery.py
```

Update the commands when a new skill adds its own tests.
