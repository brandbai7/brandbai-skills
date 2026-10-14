# Third-Party Notices

BrandBAI Skills uses the following third-party packages. Each package remains subject to its own license; the BrandBAI public license does not replace or restrict those third-party terms.

| Package | Purpose | License | Project |
|---|---|---|---|
| Playwright for Python | Visible browser automation | Apache License 2.0 | <https://github.com/microsoft/playwright-python> |
| openpyxl | Portable Excel generation and verification | MIT License | <https://foss.heptapod.net/openpyxl/openpyxl> |
| PyYAML | Repository metadata validation | MIT License | <https://github.com/yaml/pyyaml> |

The packages are not redistributed in this repository. They are installed separately from their normal package sources. Their copyright notices and full license texts are available from the linked upstream projects and installed package distributions.

The Douyin Skill additionally redistributes the exact local OCR resources listed in its manifests: PaddleOCR / RapidOCR detection and recognition model exports, ONNX Runtime Web, and OpenCC. Their original licenses and notices are bundled beside the resources under `skills/brandbai-douyin-download/assets/subtitles/vendor/` and `skills/brandbai-douyin-download/assets/subtitles-native/`. The Skill's noncommercial license applies to BrandBAI code, not as a replacement for those third-party licenses. The native runtime is frozen from v201; public version metadata does not rewrite its resource hashes.

The live-recorder Skill also uses separately installed StreamGet 4.0.10 and external FFmpeg / FFprobe executables for public live-stream resolution and local recording. Their distributions and license notices remain separate; neither dependency binaries nor downloaded live media are bundled in the Skill or repository. The BrandBAI license does not replace their upstream terms.
